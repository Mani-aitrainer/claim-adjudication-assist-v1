"""run_audit: one row per completed graph run. local -> SQLite (same file as the
checkpointer). aws -> the run_audit table on RDS Postgres (see migrations/003_runs.sql).
"""

import json
import sqlite3
from pathlib import Path
from typing import Any, Protocol

from app.core.settings import Settings


class RunAuditStore(Protocol):
    def write_run(
        self,
        run_id: str,
        document_id: str,
        status: str,
        decision_json: dict[str, Any],
        total_cost_usd: float,
        duration_ms: float,
        degraded: bool,
    ) -> None: ...

    def get_run(self, run_id: str) -> dict[str, Any] | None: ...


class SqliteRunAuditStore:
    def __init__(self, sqlite_path: str) -> None:
        self._path = sqlite_path
        Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_audit (
                    run_id TEXT PRIMARY KEY,
                    document_id TEXT,
                    status TEXT,
                    decision_json TEXT,
                    total_cost_usd REAL,
                    duration_ms REAL,
                    degraded INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def write_run(
        self,
        run_id: str,
        document_id: str,
        status: str,
        decision_json: dict[str, Any],
        total_cost_usd: float,
        duration_ms: float,
        degraded: bool,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO run_audit
                    (run_id, document_id, status, decision_json, total_cost_usd,
                     duration_ms, degraded)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    document_id,
                    status,
                    json.dumps(decision_json),
                    total_cost_usd,
                    duration_ms,
                    int(degraded),
                ),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM run_audit WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["decision_json"] = json.loads(record["decision_json"])
        record["degraded"] = bool(record["degraded"])
        return record


class PostgresRunAuditStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def write_run(
        self,
        run_id: str,
        document_id: str,
        status: str,
        decision_json: dict[str, Any],
        total_cost_usd: float,
        duration_ms: float,
        degraded: bool,
    ) -> None:
        import psycopg
        from psycopg.types.json import Jsonb

        with psycopg.connect(self._dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO run_audit
                    (run_id, document_id, status, decision_json, total_cost_usd,
                     duration_ms, degraded)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    decision_json = EXCLUDED.decision_json,
                    total_cost_usd = EXCLUDED.total_cost_usd,
                    duration_ms = EXCLUDED.duration_ms,
                    degraded = EXCLUDED.degraded
                """,
                (
                    run_id,
                    document_id,
                    status,
                    Jsonb(decision_json),
                    total_cost_usd,
                    duration_ms,
                    degraded,
                ),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        import psycopg

        with (
            psycopg.connect(self._dsn, row_factory=psycopg.rows.dict_row) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("SELECT * FROM run_audit WHERE run_id = %s", (run_id,))
            row = cur.fetchone()
        return dict(row) if row else None


def get_run_audit_store(settings: Settings) -> RunAuditStore:
    if settings.app_env == "aws":
        return PostgresRunAuditStore(settings.postgres_dsn)
    return SqliteRunAuditStore(settings.sqlite_path)
