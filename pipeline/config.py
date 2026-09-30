"""
Configuration de la version distribuée
"""
from __future__ import annotations

import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass, field


class ConfigError(Exception):
	"""La configuration est incomplète ou invalide: le programme ne doit pas démarrer."""


@dataclass(frozen=True)
class Config:
	# connexions: secrets ont repr=False pour éviter que les mots de passe apparaissent
	database_url: str = field(repr=False)   # contient le mot de passe de la base
	s3_endpoint: str
	s3_access_key: str
	s3_secret_key: str = field(repr=False)
	s3_bucket: str
	# comportement des workers
	worker_id: str
	max_attempts: int
	poll_interval_s: float
	task_timeout_min: int
	simulated_work_s: float                 # démo uniquement: ralentit chaque tâche


REQUIRED = ("DATABASE_URL", "S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY")


def load(env: Mapping[str, str] | None = None) -> Config:
	"""
	Construit la configuration à partir de l'env

	Toutes les erreurs sont signalées en une fois
	"""
	env = os.environ if env is None else env
	errors: list[str] = []

	missing = [name for name in REQUIRED if not env.get(name)]
	if missing:
		errors.append(f"variables obligatoires manquantes : {', '.join(missing)}")

	def number(name: str, default: str, kind: type, minimum: float):
		raw = env.get(name, default)
		try:
			value = kind(raw)
		except ValueError:
			errors.append(f"{name} doit être un nombre, reçu {raw!r}")
			return kind(default)
		if value < minimum:
			errors.append(f"{name} doit être >= {minimum}, reçu {value}")
		return value

	max_attempts = number("MAX_ATTEMPTS", "3", int, 1)
	poll_interval_s = number("POLL_INTERVAL_S", "2", float, 0.1)
	task_timeout_min = number("TASK_TIMEOUT_MIN", "15", int, 1)
	simulated_work_s = number("SIMULATED_WORK_S", "0", float, 0)

	if errors:
		raise ConfigError("configuration invalide :\n  - " + "\n  - ".join(errors))

	return Config(
		database_url=env["DATABASE_URL"],
		s3_endpoint=env["S3_ENDPOINT"],
		s3_access_key=env["S3_ACCESS_KEY"],
		s3_secret_key=env["S3_SECRET_KEY"],
		s3_bucket=env.get("S3_BUCKET", "posts"),
		worker_id=env.get("WORKER_ID") or socket.gethostname(), # nom de la machine par défaut
		max_attempts=max_attempts,
		poll_interval_s=poll_interval_s,
		task_timeout_min=task_timeout_min,
		simulated_work_s=simulated_work_s,
	)