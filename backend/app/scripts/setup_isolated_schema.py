"""Create a sterile isolated Postgres schema for deterministic rehearsals.

This repo's Alembic migrations assume core tables already exist in Postgres (managed schema),
and mainly apply additive changes. For a brand-new schema we must:
- create the schema
- create all tables from SQLAlchemy metadata
- then run Alembic upgrades for additive migrations

Usage (PowerShell):
  $env:ISOLATED_SCHEMA='pilot_rehearsal_xxx'
  $env:ALEMBIC_DATABASE_URL='<dburl>?options=-c%20search_path%3Dpilot_rehearsal_xxx'
  python -m app.scripts.setup_isolated_schema
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from app.database.base import Base
import app.models  # noqa: F401


def main() -> None:
    load_dotenv()
    schema = (os.getenv("ISOLATED_SCHEMA") or "").strip()
    if not schema:
        raise SystemExit("Set ISOLATED_SCHEMA")

    url = (os.getenv("ALEMBIC_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise SystemExit("Set ALEMBIC_DATABASE_URL (recommended) or DATABASE_URL")

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text(f"create schema if not exists {schema}"))
        # Ensure our DDL targets the schema for unqualified table names.
        conn.execute(text(f"set search_path to {schema}"))
        Base.metadata.create_all(bind=conn)

        # Ensure alembic_version exists in this schema (alembic will use it).
        conn.execute(
            text(
                """
                create table if not exists alembic_version (
                  version_num varchar(255) not null
                )
                """
            )
        )

    print("ok schema=", schema)


if __name__ == "__main__":
    main()

