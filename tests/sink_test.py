"""
Tests d'intégration

Ne tournent que si TEST_DATABASE_URL est défini
Sinon ils sont ignorés (« skipped », ça parle un solide anglais ici) et le reste des tests passe quand même
"""
import os
from datetime import date
from pathlib import Path

import psycopg
import pytest

from pipeline.sink import overwrite_partition
from pipeline.transform import DailyCount

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL non défini")

DAY = date(2026, 9, 1)
SCHEMA = (Path(__file__).parents[1] / "sql" / "schema.sql").read_text()


def row(value: str, posts: int = 10, originals: int = 5, platform: str = "x",
		day: date = DAY) -> DailyCount:
	return DailyCount(day, platform, "hashtag", value, posts, originals)


@pytest.fixture
def conn():
	with psycopg.connect(DB_URL, autocommit=True) as c:
		c.execute("DROP TABLE IF EXISTS daily_counts")
		c.execute(SCHEMA)
		yield c


def write(conn, rows, platform="x", day=DAY):
	with conn.transaction(), conn.cursor() as cur:
		return overwrite_partition(cur, platform, day, rows)


def table(conn):
	return conn.execute(
		"SELECT platform, day, value, posts FROM daily_counts ORDER BY 1, 2, 3").fetchall()


def test_writing_twice_gives_the_same_state(conn):
	write(conn, [row("climat"), row("sante")])
	first = table(conn)
	write(conn, [row("climat"), row("sante")])
	assert table(conn) == first
	assert len(first) == 2


def test_rewrite_removes_rows_that_disappeared(conn):
	# C'est ce qu'un UPSERT ne ferait pas
	write(conn, [row("climat"), row("sante")])
	write(conn, [row("climat", posts=12)])
	assert table(conn) == [("x", DAY, "climat", 12)]


def test_other_partitions_are_untouched(conn):
	write(conn, [row("climat")])
	write(conn, [row("climat", platform="facebook")], platform="facebook")
	write(conn, [row("climat", day=date(2026, 9, 2))], day=date(2026, 9, 2))
	write(conn, [row("vaccins")])  # ne remplace QUE x / 2026-09-01
	assert [(p, d, v) for p, d, v, _ in table(conn)] == [
		("facebook", DAY, "climat"), ("x", DAY, "vaccins"), ("x", date(2026, 9, 2), "climat")]


def test_crash_mid_write_keeps_previous_result(conn):
	write(conn, [row("climat")])
	with pytest.raises(RuntimeError):
		with conn.transaction(), conn.cursor() as cur:
			overwrite_partition(cur, "x", DAY, [row("vaccins")])
			raise RuntimeError("crash simulé après la suppression et l'insertion")
	assert table(conn) == [("x", DAY, "climat", 10)]  # rien n'a été validé


def test_row_from_another_partition_is_refused(conn):
	with pytest.raises(ValueError, match="hors partition"):
		write(conn, [row("climat", platform="facebook")], platform="x")


def test_database_rejects_inconsistent_counts(conn):
	with pytest.raises(psycopg.errors.CheckViolation):
		write(conn, [row("climat", posts=3, originals=5)])