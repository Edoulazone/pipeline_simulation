"""
Opérations sur la file de tâches (table `tasks`)

Chaque fonction reçoit un curseur: c'est l'appelant qui décide des transactions
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

import psycopg
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class Task:
	platform: str
	day: date
	object_key: str
	attempts: int


def submit(cur: psycopg.Cursor, items: Iterable[tuple[str, date, str]]) -> int:
	"""
	Crée une tâche par (plateforme, jour, clé) et renvoie le nombre de nouvelles tâches

	Idempotent: une tâche qui existe déjà n'est ni dupliquée ni modifiée
	"""
	created = 0
	for platform, day, key in items:
		cur.execute(
			"INSERT INTO tasks (platform, day, object_key) VALUES (%s, %s, %s) "
			"ON CONFLICT (platform, day) DO NOTHING",
			(platform, day, key),
		)
		created += cur.rowcount  # 1 si insérée, 0 si existante
	return created


def rerun_all(cur: psycopg.Cursor) -> int:
	"""
	Remet toutes les tâches à traiter sans risque grâce à l'écriture idempotente des résultats
	"""
	cur.execute("UPDATE tasks SET status = 'pending', attempts = 0, last_error = NULL, "
				"available_at = now(), updated_at = now()")
	return cur.rowcount


def claim(cur: psycopg.Cursor) -> Task | None:
	"""
	Prend et verrouille une tâche disponible ou renvoie None s'il y en a pas

	Si le worker meurt sa connexion se coupe, PostgreSQL annule la transaction et libère le verrou
	"""
	cur.execute(
		"""SELECT platform, day, object_key, attempts
		FROM tasks
		WHERE status = 'pending' AND available_at <= now()
		ORDER BY available_at, day, platform
		FOR UPDATE SKIP LOCKED
		LIMIT 1"""
	)
	row = cur.fetchone()
	return Task(*row) if row else None


def mark_done(cur: psycopg.Cursor, task: Task, worker_id: str, stats: dict) -> None:
	cur.execute(
		"""UPDATE tasks SET status = 'done', attempts = attempts + 1, worker_id = %s,
				stats = %s, last_error = NULL, updated_at = now()
		WHERE platform = %s AND day = %s""",
		(worker_id, Jsonb(stats), task.platform, task.day),
	)


def record_failure(cur: psycopg.Cursor, task: Task, worker_id: str, error: str,
				max_attempts: int, base_delay_s: float = 10) -> str:
	"""
	Note un échec et renvoie le nouveau statut: 'pending' ou 'failed'

	Nouvel essai après un délai qui double à chaque fois (10 s, 20 s, 40 s...)
	C'est l'équivalent d'une « dead-letter queue »
	"""
	cur.execute(
		"""UPDATE tasks SET
			attempts = attempts + 1,
			status = CASE WHEN attempts + 1 >= %(max)s THEN 'failed' ELSE 'pending' END,
			available_at = now() + make_interval(secs => %(base)s * power(2, attempts)),
			last_error = %(err)s, worker_id = %(worker)s, updated_at = now()
		WHERE platform = %(platform)s AND day = %(day)s
		RETURNING status""",
		{"max": max_attempts, "base": base_delay_s, "err": error[:2000],
		"worker": worker_id, "platform": task.platform, "day": task.day},
	)
	return cur.fetchone()[0]


def summary(conn: psycopg.Connection) -> list[dict]:
	"""
	État de toutes les tâches pour la commande de statut

	Une tâche en cours de traitement est encore 'pending' dans la table
	Son passage à 'done' est dans une transaction pas encore validée
	On la détecte autrement: une tâche verrouillée est « sautée » par SKIP LOCKED
	Toutes les tâches pending que la requête ci-dessous ne renvoie pas sont donc en cours
	"""
	with conn.transaction(), conn.cursor() as cur:
		cur.execute("SELECT platform, day FROM tasks WHERE status = 'pending' "
					"FOR KEY SHARE SKIP LOCKED")
		not_locked = set(cur.fetchall())
		cur.execute("SELECT platform, day, status, attempts, worker_id, "
					"stats->>'lignes_gardees', last_error FROM tasks ORDER BY day, platform")
		rows = cur.fetchall()

	result = []
	for platform, day, status, attempts, worker, kept, error in rows:
		if status == "pending" and (platform, day) not in not_locked:
			status = "running"
		result.append({"platform": platform, "day": day, "status": status,
					"attempts": attempts, "worker": worker, "kept": kept,
					"error": error})
	return result