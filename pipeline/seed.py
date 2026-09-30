"""
Dépose les fichiers de data/raw dans le stockage objet sous raw/

But: simuler l'étape d'ingestion qui remplit le stockage

Idempotent: joli mot pour dire qu'on recrée pas les mêmes fichiers avec le même contenu si même commande

Usage: python -m pipeline.seed
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from . import config, storage


def main(data_dir: Path = Path("data/raw")) -> None:
	cfg = config.load()
	s3 = storage.client(cfg)
	storage.ensure_bucket(s3, cfg.s3_bucket)

	files = sorted(data_dir.glob("*/*.jsonl"))
	if not files:
		raise SystemExit(f"aucun fichier dans {data_dir} : lancer d'abord scripts/generate_posts.py")

	for path in files:
		key = storage.raw_key(platform=path.parent.name, day=date.fromisoformat(path.stem))
		s3.upload_file(str(path), cfg.s3_bucket, key)
		print(f"envoyé : {key}")
	print(f"{len(files)} fichiers dans le bucket {cfg.s3_bucket!r}")


if __name__ == "__main__":
	main()