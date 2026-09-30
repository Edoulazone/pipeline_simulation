"""
Logique métier du pipeline: lire, nettoyer (extraire, agréger ensuite)

Ce module ne contient que des fonctions pures: des lignes de texte en entrée, des objets Python en sortie. Il ne sait pas d'où viennent ces lignes (local disk) ni où vont les résultats (databse)
C'est ça qui permettra de l'utiliser tel quel dans la version locale ET dans la version distribuée
"""

from __future__ import annotations
import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

REQUIRED_FIELDS = ("post_id", "platform", "author", "created_at", "text")

@dataclass(frozen=True)
class Post:
	"""
	Une publi clean avec tous les champs et les bons types
	"""

	post_id: str
	platform: str
	author: str
	created_at: datetime
	text: str
	repost_of: str | None


def _parse_datetime(value: str) -> datetime | None:
	"""
	Date ISO 8601 en UTC (ballec un peu mais bon comme ça on sait ce que c'est) ou None si illisible
	"""
	try:
		parsed = datetime.fromisoformat(value.replace("Z", "+00.00"))
	except (ValueError, AttributeError):
		return None
	if parsed.tzinfo is None:
		return None  # on refuse une date sans fuseau (à nouveau arbitraire mais voilà on montre qu'on a réfléchi tmtc)
	return parsed.astimezone(timezone.utc)

def clean(lines: Iterable[str], platform: str, day: date) -> tuple[list[Post], dict]:
	"""
	Garde les publications valides d'un fichier (1 plateforme et 1 jour donc) et rejète les autres

	return: publications propres, ststs de rejet
	"""
	stats = {"lignes_lues": 0, "json_invalide": 0, "champ_manquant": 0,
			"texte_vide": 0, "date_illisible": 0, "hors_de_la_journee": 0,
			"mauvaise_plateforme": 0, "doublon": 0}
	seen_ids: set[str] = set()
	posts: list[Post] = []

	for line in lines:
		if not line.strip():
			continue  # ligne vide en fin de fichier : ce n'est pas une donnée
		stats["lignes_lues"] += 1

		try:
			raw = json.loads(line)
		except json.JSONDecodeError:
			stats["json_invalide"] += 1
			continue
		if not isinstance(raw, dict) or any(raw.get(f) is None for f in REQUIRED_FIELDS):
			stats["champ_manquant"] += 1
			continue
		if not str(raw["text"]).strip():
			stats["texte_vide"] += 1
			continue
		created_at = _parse_datetime(raw["created_at"])
		if created_at is None:
			stats["date_illisible"] += 1
			continue

		if created_at.date() != day:
			stats["hors_de_la_journee"] += 1
			continue
		if raw["platform"] != platform:
			stats["mauvaise_plateforme"] += 1
			continue
		if raw["post_id"] in seen_ids:
			stats["doublon"] += 1
			continue

		seen_ids.add(raw["post_id"])
		posts.append(Post(
			post_id=raw["post_id"],
			platform=raw["platform"],
			author=raw["author"],
			created_at=created_at,
			text=raw["text"].strip(),
			repost_of=raw.get("repost_of"),
		))

	stats["lignes_gardees"] = len(posts)
	return posts, stats


# Extraction

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
HASHTAG_RE = re.compile(r"#(\w+)")
 
 
@dataclass(frozen=True)
class Extracted:
	hashtags: frozenset[str]
	domains: frozenset[str]
 
 
def extract(text: str) -> Extracted:
	"""
	Hashtags et domaines cités dans un texte

	1: extraire les liens
	2: retirer les liens du texte (pour que #section soit pas un "#")
	"""
	urls = URL_RE.findall(text)
	remaining = URL_RE.sub(" ", text)
	hashtags = frozenset(tag.lower() for tag in HASHTAG_RE.findall(remaining))

	domains = set()
	for url in urls:
		host = (urlsplit(url.rstrip(".,;:!?)")).hostname or "").lower()
		if host.startswith("www."):
			host = host[4:]
		if host:
			domains.add(host)
	return Extracted(hashtags=hashtags, domains=frozenset(domains))


# Agrégation (résumer beaucoup de lignes en quelques chiffres en regroupant par critères)

@dataclass(frozen=True)
class DailyCount:
	"""
	Une ligne de résultats qui dit combien de publications citent "value"
	"""
	day: date
	platform: str
	kind: str          # "hashtag" ou "domain"
	value: str         # par exemple "elections" ou "site-chelou.example"
	posts: int         # toutes les publications, repartages compris (visibilité)
	originals: int     # publications originales seulement (production de contenu)
 
 
def aggregate(posts: Iterable[Post], platform: str, day: date) -> list[DailyCount]:
	"""
	Compte le nombre de fois qu'un "hashtag" ou "domain: est cité
	"""
	totals: Counter[tuple[str, str]] = Counter()
	originals: Counter[tuple[str, str]] = Counter()
	for post in posts:
		found = extract(post.text)
		keys = [("hashtag", h) for h in found.hashtags] + [("domain", d) for d in found.domains]
		for key in keys:
			totals[key] += 1
			if post.repost_of is None:
				originals[key] += 1

	# Tri constant: même entrée et même sortie dans le même ordre
	return [
		DailyCount(day, platform, kind, value, totals[(kind, value)], originals[(kind, value)])
		for kind, value in sorted(totals)
	]
 
 
def run(lines: Iterable[str], platform: str, day: date) -> tuple[list[DailyCount], dict]:
	"""
	Traitement complet d'un fichier (nettoyer puis agréger)
	"""
	posts, stats = clean(lines, platform, day)
	return aggregate(posts, platform, day), stats
