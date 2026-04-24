"""
Autonomous Sequencer v1 — sequence-level lifecycle on the **canonical initial row** (seq 1).

Why initial row, not a separate pair table:
- Zero extra joins on the scheduler hot path (already loads pair context via seq 1).
- Same row already carries ``terminal_outcome`` for analytics; ``sequence_state`` is the operational FSM.
- Backfill/migrations touch one table; ORM stays the single source of truth.

``terminal_outcome`` (granular analytics) and ``sequence_state`` (dispatch FSM) are kept in sync
from ``campaign_terminal_outcomes.record_pair_terminal_outcome``.
"""

from __future__ import annotations

import logging
from sqlalchemy.orm import Session

from app.models import EmailCampaign
from app.services.campaign_terminal_outcomes import (
    ALL_OUTCOMES,
    BOUNCED,
    NO_RESPONSE_COMPLETED,
    PAUSED_UNKNOWN_OUTCOME,
    REPLIED_AFTER_INITIAL,
    REPLIED_AFTER_FU1,
    REPLIED_AFTER_FU2,
    REPLIED_AFTER_FU3,
)

logger = logging.getLogger(__name__)

ACTIVE_SEQUENCE = "ACTIVE_SEQUENCE"
TERMINATED_REPLIED = "TERMINATED_REPLIED"
COMPLETED_NO_RESPONSE = "COMPLETED_NO_RESPONSE"
PAUSED_UNKNOWN = "PAUSED_UNKNOWN"
BOUNCED_TERMINAL = "BOUNCED_TERMINAL"

ALL_SEQUENCE_STATES: frozenset[str] = frozenset(
    {
        ACTIVE_SEQUENCE,
        TERMINATED_REPLIED,
        COMPLETED_NO_RESPONSE,
        PAUSED_UNKNOWN,
        BOUNCED_TERMINAL,
    }
)

_TERMINAL_TO_SEQUENCE: dict[str, str] = {
    REPLIED_AFTER_INITIAL: TERMINATED_REPLIED,
    REPLIED_AFTER_FU1: TERMINATED_REPLIED,
    REPLIED_AFTER_FU2: TERMINATED_REPLIED,
    REPLIED_AFTER_FU3: TERMINATED_REPLIED,
    NO_RESPONSE_COMPLETED: COMPLETED_NO_RESPONSE,
    BOUNCED: BOUNCED_TERMINAL,
    PAUSED_UNKNOWN_OUTCOME: PAUSED_UNKNOWN,
}


def effective_sequence_state(initial: EmailCampaign | None) -> str:
    """Legacy rows: NULL ``sequence_state`` means ACTIVE until proven otherwise."""
    if initial is None:
        return ACTIVE_SEQUENCE
    s = (getattr(initial, "sequence_state", None) or "").strip()
    if not s:
        return ACTIVE_SEQUENCE
    return s if s in ALL_SEQUENCE_STATES else ACTIVE_SEQUENCE


def sequence_state_allows_followup_send(initial: EmailCampaign | None) -> bool:
    """FU rows may send only when the pair lifecycle is still active."""
    return effective_sequence_state(initial) == ACTIVE_SEQUENCE


def sync_initial_sequence_state_from_terminal(initial: EmailCampaign, terminal: str | None) -> None:
    """Map analytics ``terminal_outcome`` → coarse ``sequence_state`` (initial row only)."""
    t = (terminal or "").strip()
    if t not in ALL_OUTCOMES:
        return
    mapped = _TERMINAL_TO_SEQUENCE.get(t)
    if not mapped:
        return
    initial.sequence_state = mapped


def mark_sequence_terminated_replied(db: Session, *, student_id, hr_id) -> None:
    """Reply suppression: pair stops; FUs cancelled elsewhere — set lifecycle on initial."""
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
        return
    cur = effective_sequence_state(initial)
    if cur in (TERMINATED_REPLIED, COMPLETED_NO_RESPONSE, BOUNCED_TERMINAL):
        return
    initial.sequence_state = TERMINATED_REPLIED
    db.add(initial)
