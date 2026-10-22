from app.core import secrets
from app.core.settings import Settings

DSN = "postgresql://claims@db.example.com:5432/claims"


def _fake_secret(monkeypatch, password: str) -> None:
    secrets._get_secret_json.cache_clear()
    monkeypatch.setattr(
        secrets, "_get_secret_json", lambda secret_id, region: {"password": password}
    )


def test_password_is_added_and_url_encoded(monkeypatch) -> None:
    _fake_secret(monkeypatch, "p@ss/w:rd")
    settings = Settings(
        use_secrets_manager=True, rds_secret_arn="arn:secret", postgres_dsn=DSN
    )
    assert settings.postgres_dsn == (
        "postgresql://claims:p%40ss%2Fw%3Ard@db.example.com:5432/claims"
    )


def test_dsn_with_password_is_left_alone(monkeypatch) -> None:
    _fake_secret(monkeypatch, "ignored")
    dsn = "postgresql://claims:already@db.example.com:5432/claims"
    settings = Settings(use_secrets_manager=True, rds_secret_arn="arn:secret", postgres_dsn=dsn)
    assert settings.postgres_dsn == dsn


def test_no_lookup_without_secret_arn_or_switch(monkeypatch) -> None:
    def boom(secret_id, region):
        raise AssertionError("should not call Secrets Manager")

    monkeypatch.setattr(secrets, "_get_secret_json", boom)
    assert Settings(postgres_dsn=DSN).postgres_dsn == DSN
    assert Settings(use_secrets_manager=True, postgres_dsn=DSN).postgres_dsn == DSN


def test_openai_key_is_fetched_when_missing(monkeypatch) -> None:
    secrets._get_secret_json.cache_clear()
    monkeypatch.setattr(
        secrets, "_get_secret_json", lambda secret_id, region: {"OPENAI_API_KEY": "sk-test"}
    )
    settings = Settings(use_secrets_manager=True, openai_api_key=None)
    assert settings.openai_api_key == "sk-test"


def test_openai_key_env_var_is_not_overridden(monkeypatch) -> None:
    def boom(secret_id, region):
        raise AssertionError("should not call Secrets Manager")

    monkeypatch.setattr(secrets, "_get_secret_json", boom)
    settings = Settings(use_secrets_manager=True, openai_api_key="sk-already-set")
    assert settings.openai_api_key == "sk-already-set"
