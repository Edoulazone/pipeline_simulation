import pytest

from pipeline.config import ConfigError, load

MINIMAL = {
    "DATABASE_URL": "postgresql://pipeline:secret-db@localhost:5432/pipeline",
    "S3_ENDPOINT": "http://localhost:9000",
    "S3_ACCESS_KEY": "pipeline",
    "S3_SECRET_KEY": "secret-s3",
}


def test_minimal_config_uses_defaults():
    cfg = load(MINIMAL)
    assert cfg.s3_bucket == "posts"
    assert cfg.max_attempts == 3
    assert cfg.simulated_work_s == 0
    assert cfg.worker_id  # nom de la machine par défaut


def test_values_are_converted_to_numbers():
    cfg = load({**MINIMAL, "MAX_ATTEMPTS": "5", "POLL_INTERVAL_S": "0.5"})
    assert cfg.max_attempts == 5
    assert cfg.poll_interval_s == 0.5


def test_all_errors_are_reported_at_once():
    with pytest.raises(ConfigError) as exc:
        load({"S3_ENDPOINT": "http://localhost:9000", "MAX_ATTEMPTS": "trois"})
    message = str(exc.value)
    assert "DATABASE_URL" in message and "S3_SECRET_KEY" in message
    assert "MAX_ATTEMPTS doit être un nombre" in message


def test_out_of_range_value_is_rejected():
    with pytest.raises(ConfigError, match="MAX_ATTEMPTS doit être >= 1"):
        load({**MINIMAL, "MAX_ATTEMPTS": "0"})


def test_secrets_are_hidden_when_printed():
    text = repr(load(MINIMAL))
    assert "secret-db" not in text and "secret-s3" not in text
    assert "http://localhost:9000" in text  # le reste reste visible pour déboguer