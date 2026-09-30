"""
Accès au stockage objet: le « staging » partagé entre tous les workers

En local j'utilise MinIO et en prod n'importe quel service compatible S3 (AWS, OVHcloud, Scaleway, Garage...)

Organisation des objets identique à celle du disque local: raw/<plateforme>/<AAAA-MM-JJ>.jsonl
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import PurePosixPath

import boto3
from botocore.exceptions import ClientError

from .config import Config

RAW_PREFIX = "raw/"


def client(cfg: Config):
	return boto3.client(
		"s3",
		endpoint_url=cfg.s3_endpoint,
		aws_access_key_id=cfg.s3_access_key,
		aws_secret_access_key=cfg.s3_secret_key,
		region_name="us-east-1",  # nécessaire pour boto3, ballec pour MinIO
	)


def ensure_bucket(s3, bucket: str) -> None:
	"""
	Crée le bucket s'il n'existe pas et ne fait rien s'il existe déjà
	"""
	try:
		s3.head_bucket(Bucket=bucket)
	except ClientError:
		s3.create_bucket(Bucket=bucket)


def raw_key(platform: str, day: date) -> str:
	return f"{RAW_PREFIX}{platform}/{day.isoformat()}.jsonl"


def parse_raw_key(key: str) -> tuple[str, date]:
	"""
	'raw/x/2026-09-01.jsonl' -> ('x', date(2026, 9, 1)) ou erreur si nom invalide
	"""
	path = PurePosixPath(key)
	if not key.startswith(RAW_PREFIX) or path.suffix != ".jsonl" or len(path.parts) != 3:
		raise ValueError(f"clé inattendue : {key!r}")
	return path.parts[1], date.fromisoformat(path.stem)


def list_raw_keys(s3, bucket: str) -> list[str]:
	"""
	Toutes les clés sous raw
	S3 renvoie max 1 000 clés par réponse et paginator chope tout
	"""
	keys: list[str] = []
	for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=RAW_PREFIX):
		keys.extend(obj["Key"] for obj in page.get("Contents", []))
	return sorted(keys)


def iter_lines(s3, bucket: str, key: str) -> Iterator[str]:
	"""
	Lit un objet ligne par ligne => mémoire utilisée indépendante de la taille du fichier
	"""
	body = s3.get_object(Bucket=bucket, Key=key)["Body"]
	try:
		for raw in body.iter_lines():
			yield raw.decode("utf-8", errors="replace")
	finally:
		body.close()