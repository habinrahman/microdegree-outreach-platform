"""HR lifecycle automation — disabled while running initial-emails-only mode."""

import logging

logger = logging.getLogger(__name__)


def run_hr_lifecycle_job() -> dict:
    logger.debug("Follow-up system disabled (initial_emails_only)")
    return {"disabled": True, "reason": "initial_emails_only"}
