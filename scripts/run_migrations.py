"""Applies SQL migrations in persistence/migrations/, in filename order, against Postgres.
Also sets up the checkpointer's own tables for the given profile.

    python scripts/run_migrations.py --env local
    python scripts/run_migrations.py --env aws
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.core.settings import Settings  # noqa: E402
from app.persistence.db import run_migration_file  # noqa: E402

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "src" / "app" / "persistence" / "migrations"


async def _setup_checkpointer_tables(settings: Settings) -> None:
    if settings.app_env == "aws":
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(settings.postgres_dsn) as saver:
            await saver.setup()  # one-time, run from the db-migrate job — not on every pod start
        return

    from app.persistence.checkpointer import get_checkpointer

    async with get_checkpointer(settings):
        pass  # entering the context manager already runs .setup() for the local sqlite path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=["local", "aws"], default="local")
    args = parser.parse_args()

    settings = Settings(app_env=args.env)

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for sql_file in sql_files:
        print(f"applying {sql_file.name} ...")
        run_migration_file(settings.postgres_dsn, str(sql_file))
    print(f"applied {len(sql_files)} migration file(s)")

    asyncio.run(_setup_checkpointer_tables(settings))
    print("checkpointer tables ready")


if __name__ == "__main__":
    main()
