"""Application settings. APP_ENV is the single switch — everything else derives from it."""

from typing import Literal

from pydantic import model_validator
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
    # aws profile: the RDS-managed master secret. When set (and use_secrets_manager is on),
    # its password is added to a postgres_dsn that has none.
    rds_secret_arn: str | None = None
    sqlite_path: str = "./.local/checkpoints.sqlite"
    redis_url: str | None = None
    aws_region: str = "ap-south-1"
    secret_name_openai: str = "claim-adjudication/openai-api-key"
    documents_dir: str = "./data/documents"
    fixture_dir: str = "./tests/fixtures/textract"

    openai_api_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__")

    @model_validator(mode="after")
    def _add_rds_password(self) -> "Settings":
        if self.use_secrets_manager and self.rds_secret_arn:
            from app.core.secrets import dsn_with_rds_password

            self.postgres_dsn = dsn_with_rds_password(
                self.postgres_dsn, self.rds_secret_arn, self.aws_region
            )
        return self

    @model_validator(mode="after")
    def _load_openai_api_key(self) -> "Settings":
        if self.use_secrets_manager and not self.openai_api_key:
            from app.core.secrets import get_openai_api_key

            self.openai_api_key = get_openai_api_key(self.secret_name_openai, self.aws_region)
        return self


def get_settings() -> Settings:
    return Settings()
