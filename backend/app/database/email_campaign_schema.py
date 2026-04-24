"""Ensure email_campaigns triage columns exist (PostgreSQL)."""
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def ensure_email_campaign_triage_columns(engine: Engine) -> None:
    """Add reply_workflow_status / reply_admin_notes if missing."""
    try:
        dialect = engine.dialect.name
    except Exception:
        dialect = ""

    if dialect != "postgresql":
        logger.info("Skipping email_campaigns column check (dialect=%s)", dialect or "unknown")
        return

    with engine.begin() as conn:
        r = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'email_campaigns'
                """
            )
        )
        cols = {row[0] for row in r}

        if "reply_workflow_status" not in cols:
            conn.execute(
                text(
                    """
                    ALTER TABLE email_campaigns
                    ADD COLUMN reply_workflow_status VARCHAR(50) DEFAULT 'OPEN'
                    """
                )
            )
            logger.info("Added column email_campaigns.reply_workflow_status")

        if "reply_admin_notes" not in cols:
            conn.execute(
                text(
                    """
                    ALTER TABLE email_campaigns
                    ADD COLUMN reply_admin_notes TEXT
                    """
                )
            )
            logger.info("Added column email_campaigns.reply_admin_notes")
