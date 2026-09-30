"""
Tests d'intégration de la file de tâches (vrai PostgreSQL, voir test_sink.py)

Plusieurs tests ouvrent deux connexions à la fois
C'est la seule façon de vérifier ce qui se passe quand deux workers se disputent les mêmes tâches
"""
import os
from datetime import date
from pathlib import Path

import psycopg
import pytest

from pipeline import tasks

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL non défini")

SCHEMA = (Path(__file__).parents[1] / "sql" / "schema.sql").read_text()
D1, D2 = date(2026, 9, 1), date(2026, 9, 2)
ITEMS = [("x", D1, "raw/x/2026-09-01.jsonl"), ("x", D2, "raw/x/2026-09-02.jsonl")]


@pytest.fixture
def conn():
    with psycopg.connect(DB_URL, autocommit=True) as c:
        c.execute("DROP TABLE IF EXISTS tasks, daily_counts")
        c.execute(SCHEMA)
        with c.transaction(), c.cursor() as cur:
            tasks.submit(cur, ITEMS)
        yield c


def other():
    """Une deuxième connexion : un deuxième worker."""
    return psycopg.connect(DB_URL, autocommit=True)


def claim_one(c):
    with c.transaction(), c.cursor() as cur:
        return tasks.claim(cur)


def test_submit_is_idempotent(conn):
    with conn.transaction(), conn.cursor() as cur:
        assert tasks.submit(cur, ITEMS) == 0
    assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 2


def test_two_workers_never_get_the_same_task(conn):
    # chaque worker garde sa transaction ouverte
    with conn.transaction(), conn.cursor() as cur:
        first = tasks.claim(cur)                  # worker 1 prend une tâche...
        with other() as c2, c2.transaction(), c2.cursor() as cur2:
            second = tasks.claim(cur2)            # ...worker 2 prend l'AUTRE
            with other() as c3:
                third = claim_one(c3)             # worker 3: plus rien de libre
    assert {first.day, second.day} == {D1, D2}
    assert third is None


def test_dead_worker_releases_its_task(conn):
    c2 = other()
    c2.execute("BEGIN")
    with c2.cursor() as cur:
        taken = tasks.claim(cur)
    c2.close()                                     # le worker « meurt » sans valider
    assert claim_one(conn).day == taken.day       # la tâche est de nouveau disponible


def test_done_task_is_not_claimed_again(conn):
    with conn.transaction(), conn.cursor() as cur:
        task = tasks.claim(cur)
        tasks.mark_done(cur, task, "w1", {"lignes_gardees": 42})
    remaining = [claim_one(conn)]
    assert remaining[0].day != task.day


def test_failure_is_retried_later_then_marked_failed(conn):
    task = tasks.Task("x", D1, "raw/x/2026-09-01.jsonl", 0)
    with conn.cursor() as cur:
        assert tasks.record_failure(cur, task, "w1", "boom", max_attempts=2) == "pending"
        # délai avant le prochain essai: la tâche n'est pas disponible tout de suite
        assert conn.execute("SELECT available_at > now() FROM tasks "
                            "WHERE day = %s", (D1,)).fetchone()[0]
        assert tasks.record_failure(cur, task, "w1", "boom", max_attempts=2) == "failed"


def test_rerun_resets_everything(conn):
    with conn.transaction(), conn.cursor() as cur:
        tasks.mark_done(cur, tasks.claim(cur), "w1", {})
        assert tasks.rerun_all(cur) == 2
    assert conn.execute("SELECT count(*) FROM tasks WHERE status = 'pending' "
                        "AND attempts = 0").fetchone()[0] == 2


def test_summary_shows_running_tasks(conn):
    with conn.transaction(), conn.cursor() as cur:
        running = tasks.claim(cur)                 # verrou tenu pendant le résumé
        with other() as c2:
            states = {r["day"]: r["status"] for r in tasks.summary(c2)}
    assert states[running.day] == "running"
    assert list(states.values()).count("pending") == 1