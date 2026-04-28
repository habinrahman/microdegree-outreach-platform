"""Alembic environment — uses DATABASE_URL / ALEMBIC_DATABASE_URL and app metadata."""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# Ensure backend/ is on path when invoked as `alembic` from repo root
_sys_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _sys_path not in sys.path:
    sys.path.insert(0, _sys_path)

load_dotenv()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.database.base import Base  # noqa: E402
import app.models  # noqa: E402, F401 — register all tables on Base.metadata

target_metadata = Base.metadata


def _migration_url() -> str:
    url = (os.getenv("ALEMBIC_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise ValueError("Set DATABASE_URL or ALEMBIC_DATABASE_URL for Alembic migrations.")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _migration_url()
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Managed Postgres providers sometimes enforce aggressive default timeouts that
        # can cancel Alembic reflection queries and DDL. For migrations, we prefer
        # correctness/completion over latency.
        try:
            connection.exec_driver_sql("SET statement_timeout TO 0")
            connection.exec_driver_sql("SET lock_timeout TO 0")
        except Exception:
            # Best-effort: if the server disallows changing these, proceed.
            pass
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
