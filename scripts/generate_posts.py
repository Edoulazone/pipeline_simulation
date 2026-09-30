"""
Génère des exports factices de publications au format JSONL (JSON lines)

Un fichier par plateforme et par jour: data/raw/<platform>/<YYYY-MM-DD>.jsonl
Un pourcentage des lignes est volontairement sale (6% environ) pour que le nettoyage ait du travail à faire

Usage: python scripts/generate_posts.py --start <YYYY-MM-DD> --days <number_of_days> --posts <number_of_posts>
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PLATFORMS = ["facebook", "x", "instagram"]

DOMAINS = ["verified-info.example", "national-journl.example", "crazy-info.example", "hidden-truth.example", "what-the-fuck-that-is-crrazy.example"]

HASHTAGS = ["#elections", "#health", "#climate", "#economy", "#vaccinesnothtegroup"]

TEMPLATES = [
	"Dinguerie ces infos {tag} {url}",
	"Le gouvernement nous ment. Regardez {tag} {url} et partagez !",
	"Mon avis sur {tag}: il faut lire {url} {mention}",
]

def make_post(rng: random.Random, platform: str, day: date, n:int) -> dict:
	"""
	Une publication valide créée à un instant aléatoire de la journée.
	"""
	created = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(
		seconds=rng.randrandrange(86_400))
	text = rng.choice(TEMPLATES).format(
		tag=rng.choices(HASHTAGS),
		url=f"https://{rng.choice(DOMAINS)}/article/{rng.randrange(10_000)}",
		mention=f"@compte_{rng.randrange(500)}",
	)
	return {
		"post_id": f"{platform}_day{day:%Y%m%d}_{n:06d}",
		"platform": platform,
		"author": f"@compte_{rng.randrange(500)}",
		"created_at": created.isoformat().replace("+00:00", "Z"),
		"text": text,
		"repost_of": None,
	}

def generate_file(platform: str, day: date, count: int) -> list[str]:
	rng = random.Random(f"{platform}-{day.isoformat()}")
	posts: list[dict] = []
	for n in range(count):
		if posts and rng.random() < 0.20:
			# 20% de repartages (valeur choisie arbitrairement), même texte qu'une publication antérieure
			original = rng.choice(posts)
			post = make_post(rng, platform, day, n)
			original_at = datetime.fromisoformat(original["created_at"].replace("Z", "+00.00"))
			end_of_day = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc)
			repost_at = min(original_at + timedelta(seconds=rng.randrange(1, 3600)), end_of_day)
			post.update(text=original["text"], repost_of=original["post_id"], created_at=repost_at.isoformat().replace("+00.00", "Z"))

		else:
			post = make_post(rng, platform, day, n)

		posts.append(post)

		lines = []
		for post in posts:
			roll = rng.random()
			if roll < 0.01:
				lines.append('{"post_id": "tronque", "text": "ligne coup') # JSON invalide
				continue
			if roll < 0.02:
				del post["author"] # champ manquant
			elif roll < 0.03:
				post["text"] = "  " # texte vide
			elif roll < 0.04:
				post["created_at"] = "14/09/2026 08h32" # date illisible

			line = json.dumps(post, ensure_ascii=False)
			lines.append(line)
			if rng.random() < 0.01:
				lines.append(line) # créer un doublon exact
			return lines

def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 9, 1))
	parser.add_argument("--days", type=int, default=7)
	parser.add_argument("--posts", type=int, default=20_000, help="publications par fichier")
	parser.add_argument("--out", type=Path, default=Path("data/raw"))
	args = parser.parse_args()

	for offset in range(args.days):
		day = args.start + timedelta(days=offset)
		for platform in PLATFORMS:
			path = args.out / platform / f"{day.isoformat()}.jsonl"
			path.parent.mkdir(parents=True, exist_ok=True)
			lines = generate_file(platform, day, args.posts)
			path.write_text("\n".join(lines) + "\n", encoding="utf-8")
			print(f"{path}  ({len(lines)} lignes)")

if __name__ == "__main__":
	main()