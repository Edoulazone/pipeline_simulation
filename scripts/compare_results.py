"""
Compare le résultat de la version locale avec celui de la version distribuée

Usage (depuis ta machine, après avoir chargé le .env):
	python scripts/compare_results.py [output/daily_counts.csv]
Code de sortie: 0 si identique, 1 sinon (utilisable dans un script ou une CI)
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import psycopg

Key = tuple  # (day, platform, kind, value)


def load_local(path: Path) -> dict[Key, tuple[int, int]]:
	with path.open(encoding="utf-8", newline="") as f:
		return {(r["day"], r["platform"], r["kind"], r["value"]):
				(int(r["posts"]), int(r["originals"])) for r in csv.DictReader(f)}


def load_distributed(database_url: str) -> tuple[dict[Key, tuple[int, int]], int]:
	with psycopg.connect(database_url) as conn:
		rows = conn.execute(
			"SELECT day::text, platform, kind, value, posts, originals FROM daily_counts"
		).fetchall()
	result = {(d, p, k, v): (n, o) for d, p, k, v, n, o in rows}
	return result, len(rows) - len(result)  # doublons éventuels


def main() -> int:
	csv_path = Path(sys.argv[1] if len(sys.argv) > 1 else "output/daily_counts.csv")
	database_url = os.environ.get("DATABASE_URL")
	if not database_url:
		print("DATABASE_URL non défini : charger le .env d'abord")
		return 2
	if not csv_path.exists():
		print(f"{csv_path} introuvable : lancer d'abord python local_pipeline.py")
		return 2

	local = load_local(csv_path)
	distributed, duplicates = load_distributed(database_url)

	missing = local.keys() - distributed.keys()      # dans le CSV, pas en base
	extra = distributed.keys() - local.keys()        # en base, pas dans le CSV
	different = [k for k in local.keys() & distributed.keys() if local[k] != distributed[k]]

	print(f"version locale      : {len(local):>6} lignes")
	print(f"version distribuée  : {len(distributed):>6} lignes")
	print(f"manquantes en base  : {len(missing):>6}")
	print(f"en trop en base     : {len(extra):>6}")
	print(f"valeurs différentes : {len(different):>6}")
	print(f"doublons en base    : {duplicates:>6}")
	for label, keys in (("manquante", missing), ("en trop", extra), ("différente", different)):
		for key in sorted(keys)[:5]:
			print(f"  exemple {label} : {key}")

	identical = not (missing or extra or different or duplicates)
	print("\nRÉSULTAT :", "IDENTIQUE" if identical else "DIFFÉRENT")
	return 0 if identical else 1


if __name__ == "__main__":
	sys.exit(main())