"""Database configuration using DATABASE_URL (PostgreSQL/Supabase)."""
import os
from dotenv import load_dotenv

load_dotenv()

import logging
import uuid
from sqlalchemy import create_engine, String, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import OperationalError, PendingRollbackError

from app.database.bootstrap_ddl import bootstrap_ddl_statement_timeout_ms
from app.database.session_resilience import recover_db_session
from sqlalchemy.types import TypeDecorator, CHAR

logger = logging.getLogger(__name__)

# UUID type used for model compatibility
class UuidType(TypeDecorator):
    impl = CHAR(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return uuid.UUID(value)
        return value


DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL is None:
    raise ValueError("DATABASE_URL environment variable is required.")

# Supabase pooler (6543) / PgBouncer can drop idle server-side; recycle + pre_ping + keepalives reduce stale errors.
_pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "120"))
_pool_timeout = int(os.getenv("DB_POOL_TIMEOUT", "30"))
_engine_kwargs = {
    "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
    "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
    "pool_pre_ping": True,
    "pool_recycle": _pool_recycle,
    "pool_timeout": _pool_timeout,
}
# Avoid hanging forever when the DB host is unreachable (common local/dev pain).
_dialect = DATABASE_URL.split(":", 1)[0].lower()
if "postgresql" in _dialect or _dialect == "postgres":
    _timeout = int(os.getenv("DB_CONNECT_TIMEOUT", "30"))
    _connect_args: dict = {"connect_timeout": _timeout}
    if os.getenv("DB_TCP_KEEPALIVE", "1").strip().lower() not in ("0", "false", "no"):
        _connect_args["keepalives"] = 1
        _connect_args["keepalives_idle"] = int(os.getenv("DB_KEEPALIVES_IDLE", "30"))
        _connect_args["keepalives_interval"] = int(os.getenv("DB_KEEPALIVES_INTERVAL", "10"))
        _connect_args["keepalives_count"] = int(os.getenv("DB_KEEPALIVES_COUNT", "3"))
    _engine_kwargs["connect_args"] = _connect_args
elif "sqlite" in _dialect and ":memory:" in DATABASE_URL:
    # In-memory SQLite: share one connection across threads (pytest + FastAPI TestClient).
    # StaticPool does not accept pool_size / max_overflow / pool_timeout / pool_recycle.
    from sqlalchemy.pool import StaticPool

    _engine_kwargs = {
        "pool_pre_ping": True,
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

try:
    from app.database.fixture_email_guard import install_fixture_email_guard

    install_fixture_email_guard()
except Exception as e:
    logger.warning("fixture_email_guard not installed: %s", e)


def get_db():
    """Dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    except OperationalError as e:
        recover_db_session(db, e, log=logger)
        raise
    except PendingRollbackError:
        recover_db_session(db, None, log=logger)
        raise
    finally:
        db.close()


def init_db():
    """Lightweight startup: no runtime DDL/migrations (run Alembic / SQL manually)."""

    logger.info("Skipping runtime migrations — handled manually")

    from app.models import (
        Student,
        HRContact,
        Assignment,
        Response,
        Interview,
        EmailCampaign,
        Campaign,
        Notification,
        AuditLog,
        HRIgnored,
        RuntimeSetting,
    )

    try:
        # SAFETY: Never run SQLAlchemy create_all() against an existing Postgres/Supabase schema.
        # Local SQLite only: create tables if missing (no ALTER/migration path here).
        if engine.dialect.name != "postgresql":
            Base.metadata.create_all(bind=engine)
            logger.info("SQLite: create_all applied where needed.")
        else:
            # Postgres: apply the *small* additive columns we rely on (no destructive DDL).
            _ensure_postgres_columns()
            _ensure_runtime_settings_postgres()

    except OperationalError as e:
        logger.warning("Database not available at startup: %s", e)
        return

    # Fixture-tag columns: strict bootstrap (raises if DDL cannot be applied). Independent of Alembic / SQL editor.
    from app.database.fixture_column_bootstrap import ensure_fixture_columns_bootstrap, verify_fixture_columns

    v0 = verify_fixture_columns(engine)
    logger.info("fixture_columns_present=%s", v0.get("fixture_columns_present"))
    ensure_fixture_columns_bootstrap(engine, verify_only=False, strict=True)
    v1 = verify_fixture_columns(engine)
    logger.info("fixture_columns_present_after_bootstrap=%s", v1.get("fixture_columns_present"))

    try:
        db = SessionLocal()
        try:
            from app.services.schema_launch_gate import log_schema_launch_gate_at_startup

            log_schema_launch_gate_at_startup(db)
        finally:
            db.close()
    except Exception as e:
        logger.warning("schema_launch_gate startup log skipped: %s", e)


def _backfill_sent_campaigns_sent_at() -> None:
    """
    One-time repair each startup: rows with status=sent must never leave sent_at NULL.
    Prefer DB `updated_at` when that column exists (manual Supabase schema); else use `created_at`.
    """
    try:
        with engine.begin() as conn:
            if engine.dialect.name == "postgresql":
                has_created = conn.execute(
                    text(
                        """
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'email_campaigns'
                          AND column_name = 'created_at'
                        LIMIT 1
                        """
                    )
                ).fetchone()
                has_updated = conn.execute(
                    text(
                        """
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'email_campaigns'
                          AND column_name = 'updated_at'
                        LIMIT 1
                        """
                    )
                ).fetchone()
                if has_updated:
                    conn.execute(
                        text(
                            """
                            UPDATE email_campaigns
                            SET sent_at = updated_at
                            WHERE sent_at IS NULL
                              AND status = 'sent'
                              AND updated_at IS NOT NULL
                            """
                        )
                    )
                if has_created:
                    conn.execute(
                        text(
                            """
                            UPDATE email_campaigns
                            SET sent_at = created_at
                            WHERE sent_at IS NULL
                              AND status = 'sent'
                            """
                        )
                    )
            else:
                conn.execute(
                    text(
                        """
                        UPDATE email_campaigns
                        SET sent_at = created_at
                        WHERE sent_at IS NULL
                          AND status = 'sent'
                        """
                    )
                )
        logger.info("email_campaigns.sent_at backfill applied for sent rows with NULL sent_at.")
    except Exception as e:
        logger.warning("email_campaigns.sent_at backfill skipped: %s", e)


def _backfill_students_name_from_legacy() -> None:
    """
    Supabase / legacy schemas sometimes created `students` without `name`.
    After adding `name`, copy from full_name / student_name / display_name, then gmail local-part.
    """
    try:
        if engine.dialect.name != "postgresql":
            return
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'students'
                    """
                )
            ).fetchall()
            colset = {str(r[0]).lower() for r in rows}
            if "name" not in colset:
                return
            for legacy in ("full_name", "student_name", "display_name"):
                if legacy not in colset:
                    continue
                conn.execute(
                    text(
                        f"""
                        UPDATE students SET name = SUBSTRING(TRIM({legacy}::text), 1, 255)
                        WHERE (name IS NULL OR TRIM(name) = '')
                          AND {legacy} IS NOT NULL AND TRIM({legacy}::text) <> ''
                        """
                    )
                )
            if "gmail_address" in colset:
                conn.execute(
                    text(
                        """
                        UPDATE students SET name = SUBSTRING(
                            TRIM(SPLIT_PART(gmail_address::text, '@', 1)), 1, 255
                        )
                        WHERE (name IS NULL OR TRIM(name) = '')
                          AND gmail_address IS NOT NULL
                          AND POSITION('@' IN gmail_address::text) > 1
                        """
                    )
                )
        logger.info("students.name backfill from legacy columns (if any) completed.")
    except Exception as e:
        logger.warning("students.name legacy backfill skipped: %s", e)


def _ensure_runtime_settings_postgres() -> None:
    """
    Ensure ``runtime_settings`` exists + default seed (mirrors Alembic 0010/0012).

    Defensive against environments that skipped ``alembic upgrade`` but run new code.
    """
    if engine.dialect.name != "postgresql":
        return
    try:
        from app.services.runtime_settings_bootstrap import ensure_runtime_settings_schema_for_engine

        ensure_runtime_settings_schema_for_engine(engine)
        logger.info("runtime_settings: Postgres bootstrap applied (if needed).")
    except Exception as e:
        logger.warning("runtime_settings: Postgres bootstrap skipped: %s", e)


def _ensure_postgres_columns():
    """
    Lightweight schema upgrade for Postgres deployments.
    SQLAlchemy create_all won't add new columns to existing tables, so we add the columns we rely on.

    Each DDL runs in its own transaction so a timeout or error on one statement does not leave the
    connection in ``InFailedSqlTransaction`` for the rest (Supabase ``statement_timeout`` is common).
    """
    alters_spec: list[tuple[str, str, str]] = [
        ("email_campaigns", "message_id", "ALTER TABLE email_campaigns ADD COLUMN message_id TEXT"),
        ("email_campaigns", "thread_id", "ALTER TABLE email_campaigns ADD COLUMN thread_id TEXT"),
        ("email_campaigns", "campaign_id", "ALTER TABLE email_campaigns ADD COLUMN campaign_id TEXT"),
        ("email_campaigns", "replied", "ALTER TABLE email_campaigns ADD COLUMN replied BOOLEAN DEFAULT FALSE"),
        ("email_campaigns", "replied_at", "ALTER TABLE email_campaigns ADD COLUMN replied_at TIMESTAMP NULL"),
        (
            "email_campaigns",
            "reply_detected_at",
            "ALTER TABLE email_campaigns ADD COLUMN reply_detected_at TIMESTAMP NULL",
        ),
        ("email_campaigns", "reply_type", "ALTER TABLE email_campaigns ADD COLUMN reply_type TEXT"),
        ("email_campaigns", "reply_snippet", "ALTER TABLE email_campaigns ADD COLUMN reply_snippet TEXT"),
        ("email_campaigns", "reply_text", "ALTER TABLE email_campaigns ADD COLUMN reply_text TEXT"),
        ("email_campaigns", "reply_from", "ALTER TABLE email_campaigns ADD COLUMN reply_from TEXT"),
        (
            "email_campaigns",
            "last_reply_message_id",
            "ALTER TABLE email_campaigns ADD COLUMN last_reply_message_id TEXT",
        ),
        (
            "students",
            "name",
            "ALTER TABLE students ADD COLUMN name VARCHAR(255) NOT NULL DEFAULT ''",
        ),
        ("students", "is_demo", "ALTER TABLE students ADD COLUMN is_demo BOOLEAN DEFAULT FALSE"),
        (
            "hr_contacts",
            "is_valid",
            "ALTER TABLE hr_contacts ADD COLUMN is_valid BOOLEAN NOT NULL DEFAULT TRUE",
        ),
        ("hr_contacts", "is_demo", "ALTER TABLE hr_contacts ADD COLUMN is_demo BOOLEAN DEFAULT FALSE"),
        ("responses", "gmail_message_id", "ALTER TABLE responses ADD COLUMN gmail_message_id TEXT"),
        (
            "students",
            "emails_sent_today",
            "ALTER TABLE students ADD COLUMN emails_sent_today INTEGER NOT NULL DEFAULT 0",
        ),
        ("students", "last_sent_at", "ALTER TABLE students ADD COLUMN last_sent_at TIMESTAMP NULL"),
        (
            "students",
            "email_health_status",
            "ALTER TABLE students ADD COLUMN email_health_status VARCHAR(32) NOT NULL DEFAULT 'healthy'",
        ),
        ("email_campaigns", "reply_status", "ALTER TABLE email_campaigns ADD COLUMN reply_status TEXT"),
        ("email_campaigns", "delivery_status", "ALTER TABLE email_campaigns ADD COLUMN delivery_status TEXT"),
        (
            "email_campaigns",
            "exported_to_sheet",
            "ALTER TABLE email_campaigns ADD COLUMN exported_to_sheet BOOLEAN NOT NULL DEFAULT FALSE",
        ),
        (
            "email_campaigns",
            "exported_failure_sheet",
            "ALTER TABLE email_campaigns ADD COLUMN exported_failure_sheet BOOLEAN NOT NULL DEFAULT FALSE",
        ),
        (
            "email_campaigns",
            "exported_bounce_sheet",
            "ALTER TABLE email_campaigns ADD COLUMN exported_bounce_sheet BOOLEAN NOT NULL DEFAULT FALSE",
        ),
        (
            "email_campaigns",
            "processing_started_at",
            "ALTER TABLE email_campaigns ADD COLUMN processing_started_at TIMESTAMP NULL",
        ),
        (
            "email_campaigns",
            "processing_lock_acquired_at",
            "ALTER TABLE email_campaigns ADD COLUMN processing_lock_acquired_at TIMESTAMP NULL",
        ),
        (
            "email_campaigns",
            "failure_type",
            "ALTER TABLE email_campaigns ADD COLUMN failure_type TEXT",
        ),
        (
            "email_campaigns",
            "suppression_reason",
            "ALTER TABLE email_campaigns ADD COLUMN suppression_reason TEXT",
        ),
        (
            "email_campaigns",
            "terminal_outcome",
            "ALTER TABLE email_campaigns ADD COLUMN terminal_outcome VARCHAR(64)",
        ),
        (
            "email_campaigns",
            "sequence_state",
            "ALTER TABLE email_campaigns ADD COLUMN sequence_state VARCHAR(48)",
        ),
        (
            "email_campaigns",
            "overdue_late",
            "ALTER TABLE email_campaigns ADD COLUMN overdue_late BOOLEAN NOT NULL DEFAULT FALSE",
        ),
        (
            "email_campaigns",
            "overdue_first_seen_at",
            "ALTER TABLE email_campaigns ADD COLUMN overdue_first_seen_at TIMESTAMP NULL",
        ),
        (
            "email_campaigns",
            "exported_sequencer_sheet",
            "ALTER TABLE email_campaigns ADD COLUMN exported_sequencer_sheet BOOLEAN NOT NULL DEFAULT FALSE",
        ),
        (
            "blocked_hrs",
            "exported_to_sheet",
            "ALTER TABLE blocked_hrs ADD COLUMN exported_to_sheet BOOLEAN NOT NULL DEFAULT FALSE",
        ),
    ]
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT table_name, column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name IN (
                        'email_campaigns', 'students', 'hr_contacts', 'responses', 'blocked_hrs'
                      )
                    """
                )
            ).fetchall()
    except Exception as e:
        logger.warning("Postgres column introspection skipped: %s", e)
        return

    existing = {(str(r[0]).lower(), str(r[1]).lower()) for r in rows}
    stmts = [ddl for (tbl, col, ddl) in alters_spec if (tbl.lower(), col.lower()) not in existing]

    _ddl_to_ms = bootstrap_ddl_statement_timeout_ms()
    for stmt in stmts:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"SET LOCAL statement_timeout = {_ddl_to_ms}"))
                conn.execute(text(stmt))
        except Exception as e:
            logger.warning("Postgres column DDL skipped for one statement: %s", e)

    def _pg_named_unique_constraint_exists(conn, table: str, conname: str) -> bool:
        row = conn.execute(
            text(
                """
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = current_schema()
                  AND t.relname = :tbl
                  AND c.conname = :cname
                LIMIT 1
                """
            ),
            {"tbl": table, "cname": conname},
        ).fetchone()
        return row is not None

    # Allow multiple campaigns per student–HR; uniqueness is per sequence_number.
    # Isolated transactions: a failed DROP must not abort CREATE INDEX on the same connection.
    _ddl_to_ms = bootstrap_ddl_statement_timeout_ms()
    try:
        with engine.begin() as conn:
            conn.execute(text(f"SET LOCAL statement_timeout = {_ddl_to_ms}"))
            if _pg_named_unique_constraint_exists(conn, "email_campaigns", "uq_email_campaigns_student_hr"):
                conn.execute(
                    text("ALTER TABLE email_campaigns DROP CONSTRAINT IF EXISTS uq_email_campaigns_student_hr")
                )
    except Exception as e:
        logger.warning("Postgres index/uniqueness step skipped: %s", e)

    for idx_stmt in (
        "DROP INDEX IF EXISTS uq_email_campaigns_student_hr",
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_email_campaigns_student_hr_seq "
            "ON email_campaigns (student_id, hr_id, sequence_number)"
        ),
    ):
        try:
            with engine.begin() as conn:
                conn.execute(text(f"SET LOCAL statement_timeout = {_ddl_to_ms}"))
                conn.execute(text(idx_stmt))
        except Exception as e:
            logger.warning("Postgres index/uniqueness step skipped: %s", e)