"""
Écriture des résultats dans PostgreSQL

Strat grand remplacement (mdr): on supprime toutes les lignes d'une partition (une plateforme, un jour), puis on insère le nouveau résultat
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import psycopg

from .transform import DailyCount

COLUMNS = ("day", "platform", "kind", "value", "posts", "originals")


def overwrite_partition(cur: psycopg.Cursor, platform: str, day: date,
						rows: Sequence[DailyCount]) -> int:
	"""
	Remplace tout le résultat d'une partition et renvoie le nombre de lignes écrites

	À appeler DANS une transaction ouverte par l'appelant : c'est elle qui rend le
	remplacement atomique
	Sans elle, un crash entre la suppression et l'insertion
	laisserait la partition vide (note pour moi, je bade avec ces 65000 fonctions)

	Appelant choisit où commence et finit la transaction et après worker y met le changement de statut de sa tâche
	"""
	for row in rows:
		if (row.platform, row.day) != (platform, day):
			# garde-fou (je broie la langue de Molière): une ligne d'une autre partition ne serait jamais supprimée par un futur remplacement de sa partition et reste en double
			raise ValueError(f"ligne hors partition {platform}/{day} : {row}")

	cur.execute("DELETE FROM daily_counts WHERE day = %s AND platform = %s", (day, platform))
	# COPY: méthode d'insertion en masse la plus rapide de PostgreSQL (big brain je sais)
	with cur.copy(f"COPY daily_counts ({', '.join(COLUMNS)}) FROM STDIN") as copy:
		for row in rows:
			copy.write_row((row.day, row.platform, row.kind, row.value,
							row.posts, row.originals))
	return len(rows)