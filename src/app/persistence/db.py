"""Postgres connection pool. Only ever imported on the `aws` code path or when
VECTOR_BACKEND=pgvector locally — psycopg is never imported at module import time under
APP_ENV=local with VECTOR_BACKEND=numpy.
"""

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def get_pg_pool(dsn: str) -> Any:
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(dsn, min_size=1, max_size=5, open=True)
    return pool


def run_migration_file(dsn: str, sql_path: str) -> None:
    import psycopg

    with open(sql_path, encoding="utf-8") as f:
        sql = f.read()
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(sql)
