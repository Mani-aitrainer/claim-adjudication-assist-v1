"""Durable facts store. local -> a table in the same SQLite file as the checkpointer.
aws -> the long_term_memory table on RDS Postgres (see persistence/migrations/002_memory.sql).

Written only after a final, non-degraded decision (write_policy: on_final_decision_only in
config/tradeoff.yaml). Facts: prior decisions for the member, provider flags, OCR
corrections that worked on the same form template.
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from app.core.settings import Settings


class LongTermMemoryStore(Protocol):
    def write_fact(
        self,
        scope_key: str,
        scope_value: str,
        fact_type: str,
        fact_json: dict[str, Any],
        source_run_id: str,
        ttl_days: int,
    ) -> None: ...

    def query_facts(
        self, scope_key: str, scope_value: str, fact_type: str | None = None, top_k: int = 3
    ) -> list[dict[str, Any]]: ...


class SqliteMemoryStore:
    def __init__(self, sqlite_path: str) -> None:
        self._path = sqlite_path
        Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS long_term_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope_key TEXT NOT NULL,
                    scope_value TEXT NOT NULL,
                    fact_type TEXT NOT NULL,
                    fact_json TEXT NOT NULL,
                    source_run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def write_fact(
        self,
        scope_key: str,
        scope_value: str,
        fact_type: str,
        fact_json: dict[str, Any],
        source_run_id: str,
        ttl_days: int,
    ) -> None:
        now = datetime.now(UTC)
        expires_at = now + timedelta(days=ttl_days)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO long_term_memory
                    (scope_key, scope_value, fact_type, fact_json, source_run_id,
                     created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope_key,
                    scope_value,
                    fact_type,
                    json.dumps(fact_json),
                    source_run_id,
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )

    def query_facts(
        self, scope_key: str, scope_value: str, fact_type: str | None = None, top_k: int = 3
    ) -> list[dict[str, Any]]:
        now = datetime.now(UTC).isoformat()
        query = (
            "SELECT fact_json, source_run_id, created_at FROM long_term_memory "
            "WHERE scope_key = ? AND scope_value = ? AND expires_at > ?"
        )
        params: list[Any] = [scope_key, scope_value, now]
        if fact_type is not None:
            query += " AND fact_type = ?"
            params.append(fact_type)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(top_k)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {"fact": json.loads(row[0]), "source_run_id": row[1], "created_at": row[2]}
            for row in rows
        ]


class PostgresMemoryStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def write_fact(
        self,
        scope_key: str,
        scope_value: str,
        fact_type: str,
        fact_json: dict[str, Any],
        source_run_id: str,
        ttl_days: int,
    ) -> None:
        import psycopg
        from psycopg.types.json import Jsonb

        with psycopg.connect(self._dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO long_term_memory
                    (scope_key, scope_value, fact_type, fact_json, source_run_id, expires_at)
                VALUES (%s, %s, %s, %s, %s, now() + (%s || ' days')::interval)
                """,
                (scope_key, scope_value, fact_type, Jsonb(fact_json), source_run_id, ttl_days),
            )

    def query_facts(
        self, scope_key: str, scope_value: str, fact_type: str | None = None, top_k: int = 3
    ) -> list[dict[str, Any]]:
        import psycopg

        query = (
            "SELECT fact_json, source_run_id, created_at FROM long_term_memory "
            "WHERE scope_key = %s AND scope_value = %s AND expires_at > now()"
        )
        params: list[Any] = [scope_key, scope_value]
        if fact_type is not None:
            query += " AND fact_type = %s"
            params.append(fact_type)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(top_k)

        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [
            {"fact": row[0], "source_run_id": row[1], "created_at": str(row[2])} for row in rows
        ]


def get_memory_store(settings: Settings) -> LongTermMemoryStore:
    if settings.app_env == "aws":
        return PostgresMemoryStore(settings.postgres_dsn)
    return SqliteMemoryStore(settings.sqlite_path)
