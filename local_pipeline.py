"""
Le pipeline local

Il lit tous les fichiers de data/raw, les traite un par un, et écrit les résultats dans un CSV
Chaque commentaire « PROBLÈME » est une raison pour laquelle on ne peut pas simplement le lancer sur plusieurs machines

Usage: python local_pipeline.py
"""
import csv
import time
from dataclasses import asdict, fields
from datetime import date
from pathlib import Path

from pipeline import transform

# PROBLÈME 1: configuration codée en dur
DATA_DIR = Path("data/raw")
OUTPUT_FILE = Path("output/daily_counts.csv")


def main() -> None:
	started = time.perf_counter()
	all_rows: list[transform.DailyCount] = []

	# PROBLÈME 2: traitement séquentiel => 21 fichiers = 21 fois le temps d'un fichier
	# PROBLÈME 3: tout l'historique est retraité à chaque exécution
	for path in sorted(DATA_DIR.glob("*/*.jsonl")):
		# plateforme et jour viennent du chemin: data/raw/<plateforme>/<jour>.jsonl
		platform = path.parent.name
		day = date.fromisoformat(path.stem)

		# PROBLÈME 4: lecture sur le disque local
		lines = path.read_text(encoding="utf-8").splitlines()
		rows, stats = transform.run(lines, platform, day)

		# PROBLÈME 5: statistiques inissent dans un print() => personne ne les verra si le script tourne la nuit via cron
		print(f"{platform}/{day} : {stats['lignes_gardees']}/{stats['lignes_lues']} "
			f"lignes gardées, {len(rows)} lignes de résultat")

		# PROBLÈME 6: tout reste en mémoire jusqu'à la fin => crash au 20e fichier fait perdre tout le travail
		all_rows.extend(rows)

	# PROBLÈME 7: écriture non atomique => crash pendant l'écriture laisse un CSV non fini avec ancien résultat déjà écrasé
	OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
	with OUTPUT_FILE.open("w", newline="", encoding="utf-8") as f:
		writer = csv.DictWriter(f, fieldnames=[fl.name for fl in fields(transform.DailyCount)])
		writer.writeheader()
		writer.writerows(asdict(row) for row in all_rows)

	# PROBLÈME 8: si ça plante faut tout relancer
	print(f"terminé : {len(all_rows)} lignes écrites dans {OUTPUT_FILE} "
		f"en {time.perf_counter() - started:.1f} s")


if __name__ == "__main__":
	main()