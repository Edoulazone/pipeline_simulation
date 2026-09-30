"""
Affiche l'état de la file de tâches: le dashboard minimal du pipeline

Usage: python -m pipeline.status
"""
from __future__ import annotations

from collections import Counter

import psycopg

from . import config, tasks


def main() -> None:
    cfg = config.load()
    with psycopg.connect(cfg.database_url, autocommit=True) as conn:
        rows = tasks.summary(conn)
        results = conn.execute("SELECT count(*) FROM daily_counts").fetchone()[0]

    print(f"{'jour':<11} {'plateforme':<10} {'statut':<8} {'essais':>6}  "
          f"{'worker':<14} {'gardées':>8}  erreur")
    for r in rows:
        print(f"{r['day']!s:<11} {r['platform']:<10} {r['status']:<8} {r['attempts']:>6}  "
              f"{r['worker'] or '-':<14} {r['kept'] or '-':>8}  {(r['error'] or '')[:50]}")

    counts = Counter(r["status"] for r in rows)
    print(f"\n{len(rows)} tâches : " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
    print(f"{results} lignes dans daily_counts")


if __name__ == "__main__":
    main()