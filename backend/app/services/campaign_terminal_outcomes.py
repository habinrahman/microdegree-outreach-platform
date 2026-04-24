"""
Canonical terminal outcomes for a student–HR outreach sequence (analytics).

Stored primarily on the **initial** row (``sequence_number == 1``) as the pair-level summary.
Optionally mirrored onto a triggering row (e.g. the campaign that received the reply) for exports.
"""

from __future__ import annotations

import logging
from typing import Final

from sqlalchemy.orm import Session

from app.models import EmailCampaign

logger = logging.getLogger(__name__)

REPLIED_AFTER_INITIAL: Final = "REPLIED_AFTER_INITIAL"
REPLIED_AFTER_FU1: Final = "REPLIED_AFTER_FU1"
REPLIED_AFTER_FU2: Final = "REPLIED_AFTER_FU2"
REPLIED_AFTER_FU3: Final = "REPLIED_AFTER_FU3"
NO_RESPONSE_COMPLETED: Final = "NO_RESPONSE_COMPLETED"
BOUNCED: Final = "BOUNCED"
PAUSED_UNKNOWN_OUTCOME: Final = "PAUSED_UNKNOWN_OUTCOME"

ALL_OUTCOMES: frozenset[str] = frozenset(
    {
        REPLIED_AFTER_INITIAL,
        REPLIED_AFTER_FU1,
        REPLIED_AFTER_FU2,
        REPLIED_AFTER_FU3,
        NO_RESPONSE_COMPLETED,
        BOUNCED,
        PAUSED_UNKNOWN_OUTCOME,
    }
)


def terminal_outcome_for_replied_campaign(c: EmailCampaign) -> str:
    """Map the outbound step that received the human reply to REPLIED_AFTER_*."""
    seq = int(c.sequence_number or 0)
    et = (c.email_type or "").strip().lower()
    if seq <= 1 or et == "initial":
        return REPLIED_AFTER_INITIAL
    if seq == 2 or et == "followup_1":
        return REPLIED_AFTER_FU1
    if seq == 3 or et == "followup_2":
        return REPLIED_AFTER_FU2
    return REPLIED_AFTER_FU3


def _is_replied_outcome(v: str | None) -> bool:
    return (v or "").strip().startswith("REPLIED_AFTER_")


def _rank(outcome: str | None) -> int:
    """Higher = stronger; avoid overwriting stronger terminals with weaker signals."""
    if not outcome:
        return 0
    o = outcome.strip()
    if _is_replied_outcome(o):
        return 4
    if o == NO_RESPONSE_COMPLETED:
        return 3
    if o == BOUNCED:
        return 2
    if o == PAUSED_UNKNOWN_OUTCOME:
        return 1
    return 0


def record_pair_terminal_outcome(
    db: Session,
    *,
    student_id,
    hr_id,
    outcome: str,
    tag_campaign: EmailCampaign | None = None,
) -> None:
    """
    Set ``terminal_outcome`` on the pair's initial row (seq 1) when the new outcome is not weaker
    than the existing value. Optionally mirror the same value onto ``tag_campaign``.
    """
    o = (outcome or "").strip()
    if o not in ALL_OUTCOMES:
        logger.warning("record_pair_terminal_outcome: unknown outcome %r ignored", outcome)
        return

    initial = (
        db.query(EmailCampaign)
        .filter(
            EmailCampaign.student_id == student_id,
            EmailCampaign.hr_id == hr_id,
            EmailCampaign.sequence_number == 1,
        )
        .first()
    )
    if initial is None:
        logger.debug("record_pair_terminal_outcome: no initial row for pair %s %s", student_id, hr_id)
        return

    cur = (initial.terminal_outcome or "").strip() or None
    if cur and _rank(o) < _rank(cur):
        return

    initial.terminal_outcome = o
    db.add(initial)
    from app.services.sequence_state_service import sync_initial_sequence_state_from_terminal

    sync_initial_sequence_state_from_terminal(initial, o)

    if tag_campaign is not None and tag_campaign.id != initial.id:
        tag_campaign.terminal_outcome = o
        db.add(tag_campaign)
