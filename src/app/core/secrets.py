"""Secrets Manager lookups. Only used on the aws profile."""

import json
from functools import lru_cache
from urllib.parse import quote, urlsplit, urlunsplit


@lru_cache(maxsize=8)
def _get_secret_json(secret_id: str, region: str) -> dict:
    import boto3

    client = boto3.client("secretsmanager", region_name=region)
    return json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])


def get_openai_api_key(secret_id: str, region: str) -> str:
    """Fetch the OpenAI key from the secret Step 5 of the run guide writes:
    `{"OPENAI_API_KEY": "sk-..."}`.
    """
    return _get_secret_json(secret_id, region)["OPENAI_API_KEY"]


def dsn_with_rds_password(dsn: str, secret_id: str, region: str) -> str:
    """Return `dsn` with the RDS-managed master password filled in.

    RDS creates the secret as {"username": ..., "password": ...}. A DSN that already
    carries a password is returned unchanged.
    """
    parts = urlsplit(dsn)
    if parts.password:
        return dsn
    password = _get_secret_json(secret_id, region)["password"]
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    netloc = f"{parts.username}:{quote(password, safe='')}@{host}"
    return urlunsplit(parts._replace(netloc=netloc))
