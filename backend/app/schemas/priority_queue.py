"""Read-only priority outreach queue API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PriorityStudentBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    gmail_address: str
    status: str = "active"
    email_health_status: str = "healthy"
    is_demo: bool = False


class PriorityHRBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    company: str
    email: str
    is_valid: bool = True
    status: str | None = None


class PriorityQueueRow(BaseModel):
    student: PriorityStudentBrief
    hr: PriorityHRBrief
    priority_score: float = Field(..., ge=0, le=100)
    priority_rank: int = Field(..., ge=1)
    recommendation_reason: list[str] = Field(default_factory=list)
    recommended_action: str
    urgency_level: str
    queue_bucket: str
    hr_tier: str
    health_score: float
    opportunity_score: float
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    next_best_touch: str | None = None
    cooldown_status: str | None = None
    followup_status: str | None = None
    campaign_id: UUID | None = None
    signal_fingerprint: str
    ranking_mode: str = "standard"
    ranking_slot_type: str | None = None
    diversity_note: str | None = None
    decision_diagnostics: dict[str, Any] = Field(
        default_factory=dict,
        description="Operator-facing explainability: rank drivers, suppression, follow-up snapshot, cooldown, scoring.",
    )


class PriorityQueueSummary(BaseModel):
    send_now_count: int = 0
    followup_due_count: int = 0
    warm_lead_priority_count: int = 0
    wait_for_cooldown_count: int = 0
    suppressed_count: int = 0
    low_priority_count: int = 0
    avg_priority_score: float | None = None
    total_candidates: int = 0


class PriorityQueueResponse(BaseModel):
    computed_at_utc: datetime
    summary: PriorityQueueSummary
    rows: list[PriorityQueueRow]
    diversity_metrics: dict[str, Any] = Field(default_factory=dict)


class PriorityQueueSummaryOnlyResponse(BaseModel):
    computed_at_utc: datetime
    summary: PriorityQueueSummary


class SchedulerPriorityHookDoc(BaseModel):
    """Design-only: when enabled, scheduler may prefer higher-ranked pairs (Phase 2+)."""

    env_flag: str = "SCHEDULER_USE_PRIORITY_QUEUE"
    enabled_in_environment: bool = False
    description: str = (
        "If set to true, future scheduler iterations may reorder due campaigns using "
        "the read-only priority engine. Phase 1 ships with this disabled; no sending behavior changes."
    )
