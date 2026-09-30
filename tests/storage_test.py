from datetime import date

import pytest
from moto import mock_aws

from pipeline import storage
from pipeline.config import load

CFG = load({
	"DATABASE_URL": "postgresql://unused",
	"S3_ENDPOINT": "https://s3.amazonaws.com",  # moto simule S3 à cette adresse
	"S3_ACCESS_KEY": "test",
	"S3_SECRET_KEY": "test",
})


@pytest.fixture
def s3():
	"""Un faux S3 en mémoire : aucun serveur, aucun réseau."""
	with mock_aws():
		client = storage.client(CFG)
		storage.ensure_bucket(client, CFG.s3_bucket)
		yield client


def test_key_round_trip():
	key = storage.raw_key("x", date(2026, 9, 1))
	assert key == "raw/x/2026-09-01.jsonl"
	assert storage.parse_raw_key(key) == ("x", date(2026, 9, 1))


@pytest.mark.parametrize("bad", ["raw/x.jsonl", "raw/x/2026-09-01.csv",
								"autre/x/2026-09-01.jsonl", "raw/x/pas-une-date.jsonl"])
def test_invalid_keys_are_rejected(bad):
	with pytest.raises(ValueError):
		storage.parse_raw_key(bad)


def test_ensure_bucket_is_idempotent(s3):
	storage.ensure_bucket(s3, CFG.s3_bucket)  # deuxième appel: pas d'erreur


def test_list_and_read(s3):
	s3.put_object(Bucket=CFG.s3_bucket, Key="raw/x/2026-09-02.jsonl", Body="b\n".encode())
	s3.put_object(Bucket=CFG.s3_bucket, Key="raw/x/2026-09-01.jsonl",
				Body='{"a": 1}\nligne accentuée é\n'.encode("utf-8"))
	s3.put_object(Bucket=CFG.s3_bucket, Key="autre/fichier.txt", Body=b"ignore")

	assert storage.list_raw_keys(s3, CFG.s3_bucket) == [
		"raw/x/2026-09-01.jsonl", "raw/x/2026-09-02.jsonl"]
	assert list(storage.iter_lines(s3, CFG.s3_bucket, "raw/x/2026-09-01.jsonl")) == [
		'{"a": 1}', "ligne accentuée é"]