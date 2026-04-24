"""
EmailCampaign row lifecycle (outbound queue semantics).

Single source of truth for **which status changes are legal** on ``email_campaigns.status``.
Used by runtime guards (ORM assigns) and invariant tests.

Notes
-----
- **Bulk** ``Query.update({...})`` bypasses SQLAlchemy attribute events; the scheduler's
  ``pending → scheduled`` normalization is documented as macro ``BULK_PENDING_TO_SCHEDULED``
  and must stay consistent with ``LEGAL_EMAIL_CAMPAIGN_TRANSITIONS`` intent.
- **Cross-row** sequencing (e.g. do not send FU if initial replied) is enforced elsewhere
  (``followup_eligibility``, ``cancel_followups_for_hr_response``); this module is **per-row**.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# Model + code paths use lowercase statuses.
KNOWN_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "pending",
        "scheduled",
        "processing",
        "sent",
        "replied",
        "failed",
        "cancelled",
        "expired",
        "paused",
    }
)

# Outbound queue is finished for these statuses (ORM graph has no exit to a different state).
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset({"cancelled", "expired", "replied"})

# ---------------------------------------------------------------------------
# Directed edges: from_status -> {allowed to_status} (single-row ORM paths)
# ---------------------------------------------------------------------------
LEGAL_EMAIL_CAMPAIGN_TRANSITIONS: dict[str, frozenset[str]] = {
    # Created as pending (campaign_generator, debug seed); may be cancelled before send.
    # Row-level ``pending -> scheduled`` kept legal to mirror scheduler bulk normalize intent.
    "pending": frozenset({"scheduled", "processing", "cancelled", "paused"}),
    # Scheduler bulk-normalizes pending -> scheduled (bulk SQL); row-level pending->scheduled not listed.
    "scheduled": frozenset(
        {
            "processing",
            "expired",
            "cancelled",
            "paused",  # operator bulk pause (PATCH /campaigns)
        }
    ),
    # Worker + scheduler claim; scheduler can return to scheduled if campaign group paused;
    # stale processing -> paused (idempotency); operator reconcile -> sent/paused.
    "processing": frozenset(
        {
            "sent",
            "failed",
            "cancelled",
            "scheduled",
            "paused",
        }
    ),
    # Outbound success; inbound reply / bounce classifier may refine.
    "sent": frozenset({"replied", "failed", "sent"}),  # self-loop: idempotent "already sent" repair
    # Human / interested reply classification — terminal for app ORM (no regress to outbound queue).
    "replied": frozenset({"replied"}),
    # Retry path re-queues outreach (outreach_service); operator bulk may cancel? not in code — keep tight.
    "failed": frozenset({"pending", "failed"}),  # self-loop: idempotent writes
    # Operator bulk patch from pending|scheduled|processing only.
    "cancelled": frozenset({"cancelled"}),
    "expired": frozenset({"expired"}),
    # Stale / operator pause; outreach may later force pending for re-queue.
    # outreach_service may force ``paused -> pending`` when re-queuing.
    "paused": frozenset({"pending", "paused"}),
}

# Documented bulk SQL transitions (not expressed as single-row edges above).
BULK_PENDING_TO_SCHEDULED: Final[str] = (
    "campaign_scheduler.run_campaign_job: bulk UPDATE pending -> scheduled for scheduler fetch path"
)
BULK_PROCESSING_TO_PAUSED_STALE: Final[str] = (
    "campaign_scheduler.run_campaign_job: stale processing -> paused (unknown outcome; idempotency)"
)


def normalize_email_campaign_status(status: str | None) -> str:
    s = (status or "pending").strip().lower()
    return s if s else "pending"


def is_legal_email_campaign_transition(before: str | None, after: str | None) -> bool:
    """Return True if ``after`` may replace ``before`` on the same EmailCampaign row (ORM semantics)."""
    b = normalize_email_campaign_status(before)
    a = normalize_email_campaign_status(after)
    if b == a:
        return True
    if b not in LEGAL_EMAIL_CAMPAIGN_TRANSITIONS:
        return False
    return a in LEGAL_EMAIL_CAMPAIGN_TRANSITIONS[b]


def assert_legal_email_campaign_transition(
    before: str | None,
    after: str | None,
    *,
    context: str = "",
) -> None:
    if is_legal_email_campaign_transition(before, after):
        return
    b = normalize_email_campaign_status(before)
    a = normalize_email_campaign_status(after)
    msg = f"Illegal EmailCampaign status transition {b!r} -> {a!r}"
    if context:
        msg += f" ({context})"
    raise ValueError(msg)


# Explicit regression targets: must stay illegal vs ``is_legal``.
FORBIDDEN_TRANSITION_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("replied", "pending"),
    ("replied", "scheduled"),
    ("replied", "processing"),
    ("replied", "sent"),
    ("replied", "failed"),
    ("cancelled", "pending"),
    ("cancelled", "scheduled"),
    ("cancelled", "processing"),
    ("cancelled", "sent"),
    ("expired", "pending"),
    ("expired", "scheduled"),
    ("expired", "processing"),
    ("failed", "sent"),  # must re-enter via pending -> … -> sent
    ("failed", "replied"),
    ("failed", "scheduled"),
    ("failed", "processing"),
    ("sent", "pending"),
    ("sent", "scheduled"),
    ("sent", "processing"),
    ("sent", "cancelled"),
)


def transition_map_markdown() -> str:
    """Human-readable transition map for operators / docs."""
    lines = [
        "## EmailCampaign.status transition map (per row)",
        "",
        "Edges are **OR single-row updates** used by the app (excluding documented bulk SQL).",
        "",
        "| From | To |",
        "|------|-----|",
    ]
    for src in sorted(LEGAL_EMAIL_CAMPAIGN_TRANSITIONS.keys()):
        for dst in sorted(LEGAL_EMAIL_CAMPAIGN_TRANSITIONS[src]):
            if src == dst:
                lines.append(f"| `{src}` | `{dst}` (no-op / idempotent) |")
            else:
                lines.append(f"| `{src}` | `{dst}` |")
    lines.extend(
        [
            "",
            "### Bulk (not row ORM)",
            "",
            f"- `{BULK_PENDING_TO_SCHEDULED}`",
            f"- `{BULK_PROCESSING_TO_PAUSED_STALE}`",
            "",
            "### Examples explicitly forbidden",
            "",
        ]
    )
    for a, b in FORBIDDEN_TRANSITION_EXAMPLES:
        lines.append(f"- `{a}` → `{b}`")
    return "\n".join(lines)


def build_mermaid_state_diagram() -> str:
    """Mermaid ``stateDiagram-v2`` source for operators (read-only visualization)."""
    parts = ["stateDiagram-v2", "  direction LR"]
    for src in sorted(LEGAL_EMAIL_CAMPAIGN_TRANSITIONS.keys()):
        for dst in sorted(LEGAL_EMAIL_CAMPAIGN_TRANSITIONS[src]):
            if src == dst:
                continue
            parts.append(f"  {src} --> {dst}")
    parts.append("  class cancelled,expired,replied terminal")
    parts.append("  classDef terminal fill:#7f1d1d,color:#fecaca")
    return "\n".join(parts)


def build_lifecycle_visualization_payload(db: "Session") -> dict[str, Any]:
    """
    Read-only snapshot: graph edges from ``LEGAL_EMAIL_CAMPAIGN_TRANSITIONS`` plus
    ``email_campaigns`` row counts grouped by ``status``.
    """
    from datetime import datetime, timezone

    from sqlalchemy import func

    from app.models import EmailCampaign

    rows = db.query(EmailCampaign.status, func.count(EmailCampaign.id)).group_by(EmailCampaign.status).all()
    raw_counts: dict[str, int] = {}
    for st, n in rows:
        key = (st or "").strip().lower() if st is not None else ""
        if not key:
            key = "(empty)"
        raw_counts[key] = raw_counts.get(key, 0) + int(n)

    # Canonical rows for known model statuses + any DB drift
    status_counts: dict[str, int] = {s: 0 for s in sorted(KNOWN_STATUSES)}
    other: dict[str, int] = {}
    for k, v in raw_counts.items():
        if k in KNOWN_STATUSES:
            status_counts[k] = v
        else:
            other[k] = v

    edges: list[dict[str, str]] = []
    for src, dsts in sorted(LEGAL_EMAIL_CAMPAIGN_TRANSITIONS.items()):
        for dst in sorted(dsts):
            if src == dst:
                continue
            edges.append({"source": src, "target": dst})

    self_loop_on = sorted(
        s for s in LEGAL_EMAIL_CAMPAIGN_TRANSITIONS if s in LEGAL_EMAIL_CAMPAIGN_TRANSITIONS[s]
    )

    total = sum(raw_counts.values())

    return {
        "computed_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_campaign_rows": total,
        "status_counts": [
            {
                "status": s,
                "count": status_counts[s],
                "is_terminal": s in TERMINAL_STATUSES,
            }
            for s in sorted(KNOWN_STATUSES)
        ],
        "unknown_status_counts": [{"status": k, "count": v} for k, v in sorted(other.items())],
        "edges": edges,
        "self_loop_statuses": self_loop_on,
        "terminal_statuses": sorted(TERMINAL_STATUSES),
        "bulk_transitions": [BULK_PENDING_TO_SCHEDULED, BULK_PROCESSING_TO_PAUSED_STALE],
        "mermaid_state_diagram": build_mermaid_state_diagram(),
    }
