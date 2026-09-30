"""
Le worker prend une tâche, traite le fichier, écrit le résultat et recommence

Tous les workers sont identiques et sans état
Ils se coordonnent uniquement à travers la table `tasks`

Garantie centrale: prendre la tâche, écrire le résultat et marquer la tâche comme terminée se font dans une seule transaction PostgreSQL.
- Le worker meurt en plein travail => PostgreSQL annule la transaction, la tâche redevient disponible et un autre worker la reprend
- Le traitement échoue ? La transaction est annulée, l'échec est noté dans une nouvelle transaction et la tâche sera réessayée plus tard

Usage :
	python -m pipeline.worker               tourne en continu (un service)
	python -m pipeline.worker --until-empty s'arrête quand il n'y a plus rien à faire
"""
from __future__ import annotations

import argparse
import json
import signal
import time
from datetime import datetime, timezone

import psycopg

from . import config, sink, storage, tasks, transform

_stop_requested = False


def log(event: str, **fields) -> None:
	"""
	Une ligne JSON par événement sur la sortie standard

	Lisible par un humain, filtrable par une machine => Docker collecte les logs
	"""
	record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
			"event": event, **fields}
	print(json.dumps(record, ensure_ascii=False, default=str), flush=True)


def _request_stop(signum, frame) -> None:
	"""
	SIGTERM (« docker stop ») ou Ctrl+C
	"""
	global _stop_requested
	_stop_requested = True
	log("arret_demande", signal=signal.Signals(signum).name)


def connect(cfg: config.Config) -> psycopg.Connection:
	conn = psycopg.connect(cfg.database_url, autocommit=True)
	# Filet de sécurité: un worker MORT libère sa tâche tout seul (connexion coupée)
	# Mais un worker FIGÉ (genre bloqué sur un appel réseau) la garderait indéfiniment
	# PostgreSQL coupe donc toute session restée inactive trop longtemps au milieu d'une transaction
	conn.execute("SELECT set_config('idle_in_transaction_session_timeout', %s, false)",
				(f"{cfg.task_timeout_min}min",))
	return conn


def process_one(conn: psycopg.Connection, s3, cfg: config.Config) -> bool:
	"""
	Traite une tâche. Renvoie False s'il n'y avait rien à faire
	"""
	task = None
	try:
		with conn.transaction(), conn.cursor() as cur:
			task = tasks.claim(cur)
			if task is None:
				return False
			log("tache_prise", worker=cfg.worker_id, platform=task.platform,
				day=task.day, essai=task.attempts + 1)
			started = time.monotonic()

			lines = storage.iter_lines(s3, cfg.s3_bucket, task.object_key)
			rows, stats = transform.run(lines, task.platform, task.day)
			if cfg.simulated_work_s:
				time.sleep(cfg.simulated_work_s)  # démo uniquement

			written = sink.overwrite_partition(cur, task.platform, task.day, rows)
			tasks.mark_done(cur, task, cfg.worker_id, stats)
		# Sortie du bloc sans exception: la transaction est validée (COMMIT)
		log("tache_terminee", worker=cfg.worker_id, platform=task.platform, day=task.day,
			lignes_ecrites=written, duree_s=round(time.monotonic() - started, 3), **stats)
		return True

	except psycopg.OperationalError:
		raise  # la base est injoignable: c'est à la boucle principale de se reconnecter
	except Exception as exc:
		if task is None:
			raise
		# La transaction de traitement a été annulée donc on note l'échec dans une nouvelle transaction
		error = f"{type(exc).__name__}: {exc}"
		with conn.transaction(), conn.cursor() as cur:
			status = tasks.record_failure(cur, task, cfg.worker_id, error, cfg.max_attempts)
		log("tache_en_echec", worker=cfg.worker_id, platform=task.platform, day=task.day,
			essai=task.attempts + 1, nouveau_statut=status, erreur=error)
		return True


def run(cfg: config.Config, until_empty: bool = False) -> None:
	s3 = storage.client(cfg)
	conn = None
	log("worker_demarre", worker=cfg.worker_id)
	while not _stop_requested:
		try:
			if conn is None or conn.closed:
				conn = connect(cfg)
			if process_one(conn, s3, cfg):
				continue  # une tâche traitée: on enchaîne tout de suite sur la suivante
			if until_empty:
				break
			time.sleep(cfg.poll_interval_s)  # rien à faire : on attend un peu
		except psycopg.OperationalError as exc:
			log("base_injoignable", worker=cfg.worker_id, erreur=str(exc))
			if conn is not None:
				conn.close()
			conn = None
			time.sleep(cfg.poll_interval_s)
	if conn is not None:
		conn.close()
	log("worker_arrete", worker=cfg.worker_id)


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--until-empty", action="store_true",
						help="s'arrêter quand il n'y a plus de tâche disponible")
	args = parser.parse_args()
	signal.signal(signal.SIGTERM, _request_stop)
	signal.signal(signal.SIGINT, _request_stop)
	run(config.load(), until_empty=args.until_empty)


if __name__ == "__main__":
	main()