"""
Tests d'intégration du worker : faux S3 en mémoire (moto) + vrai PostgreSQL
"""
import os
from datetime import date
from pathlib import Path

import psycopg
import pytest
from moto import mock_aws

from pipeline import config, storage, tasks, transform, worker

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL non défini")

SCHEMA = (Path(__file__).parents[1] / "sql" / "schema.sql").read_text()
D1, D2 = date(2026, 9, 1), date(2026, 9, 2)


def post(pid: str, day: date, text: str) -> str:
    return (f'{{"post_id": "{pid}", "platform": "x", "author": "@a", '
            f'"created_at": "{day}T10:00:00Z", "text": "{text}", "repost_of": null}}')


FILES = {
    D1: "\n".join([post("x1", D1, "#climat https://a.example/1"), post("x2", D1, "#sante"),
                   "ligne corrompue"]),
    D2: post("x3", D2, "#climat"),
}


@pytest.fixture
def env():
    cfg = config.load({"DATABASE_URL": DB_URL, "S3_ENDPOINT": "https://s3.amazonaws.com",
                       "S3_ACCESS_KEY": "test", "S3_SECRET_KEY": "test",
                       "WORKER_ID": "w-test", "MAX_ATTEMPTS": "2"})
    with mock_aws(), psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS tasks, daily_counts")
        conn.execute(SCHEMA)
        s3 = storage.client(cfg)
        storage.ensure_bucket(s3, cfg.s3_bucket)
        items = []
        for day, content in FILES.items():
            key = storage.raw_key("x", day)
            s3.put_object(Bucket=cfg.s3_bucket, Key=key, Body=content.encode())
            items.append(("x", day, key))
        with conn.transaction(), conn.cursor() as cur:
            tasks.submit(cur, items)
        yield cfg, conn, s3


def results(conn):
    return conn.execute("SELECT day, kind, value, posts FROM daily_counts "
                        "ORDER BY 1, 2, 3").fetchall()


def test_processes_every_task_then_stops(env):
    cfg, conn, s3 = env
    assert worker.process_one(conn, s3, cfg) is True
    assert worker.process_one(conn, s3, cfg) is True
    assert worker.process_one(conn, s3, cfg) is False       # plus rien à faire
    assert conn.execute("SELECT count(*) FROM tasks WHERE status = 'done'").fetchone()[0] == 2


def test_results_match_the_local_version(env):
    """Même logique métier, même résultat : c'est la base de la comparaison avant/après."""
    cfg, conn, s3 = env
    while worker.process_one(conn, s3, cfg):
        pass
    expected = []
    for day, content in FILES.items():
        rows, _ = transform.run(content.splitlines(), "x", day)
        expected += [(r.day, r.kind, r.value, r.posts) for r in rows]
    assert results(conn) == sorted(expected)


def test_stats_and_worker_are_recorded(env):
    cfg, conn, s3 = env
    while worker.process_one(conn, s3, cfg):
        pass
    worker_id, stats = conn.execute(
        "SELECT worker_id, stats FROM tasks WHERE day = %s", (D1,)).fetchone()
    assert worker_id == "w-test"
    assert stats["json_invalide"] == 1 and stats["lignes_gardees"] == 2


def test_processing_twice_changes_nothing(env):
    cfg, conn, s3 = env
    while worker.process_one(conn, s3, cfg):
        pass
    before = results(conn)
    with conn.transaction(), conn.cursor() as cur:
        tasks.rerun_all(cur)
    while worker.process_one(conn, s3, cfg):
        pass
    assert results(conn) == before


def test_missing_file_is_retried_then_failed_without_blocking_others(env):
    cfg, conn, s3 = env
    s3.delete_object(Bucket=cfg.s3_bucket, Key=storage.raw_key("x", D1))

    while worker.process_one(conn, s3, cfg):
        pass
    status, attempts, error = conn.execute(
        "SELECT status, attempts, last_error FROM tasks WHERE day = %s", (D1,)).fetchone()
    assert (status, attempts) == ("pending", 1) and "NoSuchKey" in error
    assert results(conn) and all(r[0] == D2 for r in results(conn))  # D2 traité quand même

    conn.execute("UPDATE tasks SET available_at = now()")  # saute l'attente
    worker.process_one(conn, s3, cfg)
    assert conn.execute("SELECT status FROM tasks WHERE day = %s",
                        (D1,)).fetchone()[0] == "failed"