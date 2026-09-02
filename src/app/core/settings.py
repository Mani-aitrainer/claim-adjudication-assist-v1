"""Application settings. APP_ENV is the single switch — everything else derives from it."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: Literal["local", "aws"] = "local"
    log_level: str = "INFO"

    # feature switches — all false locally
    use_redis: bool = False
    use_textract: bool = False
    use_s3: bool = False
    use_secrets_manager: bool = False

    vector_backend: Literal["pgvector", "numpy"] = "pgvector"
    postgres_dsn: str = "postgresql://claims:claims@localhost:5432/claims"
    sqlite_path: str = "./.local/checkpoints.sqlite"
    redis_url: str | None = None
    aws_region: str = "ap-south-1"
    secret_name_openai: str = "claim-adjudication/openai-api-key"
    documents_dir: str = "./data/documents"
    fixture_dir: str = "./tests/fixtures/textract"

    openai_api_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__")


def get_settings() -> Settings:
    return Settings()
