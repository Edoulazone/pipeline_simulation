"""
Crée une tâche par fichier présent dans le stockage objet

Usage:
	python -m pipeline.submit            crée les tâches manquantes
	python -m pipeline.submit --rerun    remet en plus TOUTES les tâches à traiter
"""
from __future__ import annotations

import argparse

import psycopg

from . import config, storage, tasks


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--rerun", action="store_true",
						help="remettre toutes les tâches à traiter (rejeu complet)")
	args = parser.parse_args()

	cfg = config.load()
	s3 = storage.client(cfg)

	items = []
	for key in storage.list_raw_keys(s3, cfg.s3_bucket):
		try:
			platform, day = storage.parse_raw_key(key)
		except ValueError:
			print(f"ignoré (nom inattendu) : {key}")
			continue
		items.append((platform, day, key))

	# Une seule transaction: soit toutes les tâches sont créées, soit aucune
	with psycopg.connect(cfg.database_url) as conn, conn.transaction(), conn.cursor() as cur:
		created = tasks.submit(cur, items)
		reset = tasks.rerun_all(cur) if args.rerun else 0

	print(f"{len(items)} fichiers trouvés, {created} nouvelles tâches"
		+ (f", {reset} tâches remises à traiter" if args.rerun else ""))


if __name__ == "__main__":
	main()