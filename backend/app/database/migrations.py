import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def run_safe_migrations(engine):
    # Avoid emoji: Windows service consoles may not be UTF-8.
    logger.debug("Running SAFE migrations...")

    with engine.connect() as conn:
        # Add exported_failure_sheet
        conn.execute(text("""
        ALTER TABLE email_campaigns
        ADD COLUMN IF NOT EXISTS exported_failure_sheet BOOLEAN DEFAULT FALSE;
        """))

        # Add exported_bounce_sheet
        conn.execute(text("""
        ALTER TABLE email_campaigns
        ADD COLUMN IF NOT EXISTS exported_bounce_sheet BOOLEAN DEFAULT FALSE;
        """))

        # Add processing_started_at
        conn.execute(text("""
        ALTER TABLE email_campaigns
        ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMP;
        """))

        # Add processing_lock_acquired_at
        conn.execute(text("""
        ALTER TABLE email_campaigns
        ADD COLUMN IF NOT EXISTS processing_lock_acquired_at TIMESTAMP;
        """))

        # Add failure_type
        conn.execute(text("""
        ALTER TABLE email_campaigns
        ADD COLUMN IF NOT EXISTS failure_type TEXT;
        """))

        conn.execute(text("""
        ALTER TABLE students
        ADD COLUMN IF NOT EXISTS email_health_status VARCHAR(32) DEFAULT 'healthy';
        """))

        conn.commit()

    logger.debug("SAFE migrations complete")