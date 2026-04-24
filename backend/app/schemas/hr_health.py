"""API schemas for HR health / opportunity scoring."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HRScoreReason(BaseModel):
    """Single explainable factor in a score."""

    code: str = Field(..., description="Stable machine code, e.g. bounce_rate_elevated")
    label: str = Field(..., description="Human-readable summary")
    impact: str = Field(..., description="positive | negative | neutral")
    weight: float | None = Field(None, description="Approximate contribution toward the score dimension")


class HRHealthScores(BaseModel):
    """Computed scores and tier for one HR contact."""

    tier: str = Field(..., description="A | B | C | D")
    health_score: float = Field(..., ge=0, le=100)
    opportunity_score: float = Field(..., ge=0, le=100)
    health_reasons: list[HRScoreReason]
    opportunity_reasons: list[HRScoreReason]
    components: dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque numeric inputs for debugging (rates, counts, flags)",
    )


class HRHealthDetailResponse(HRHealthScores):
    """Full detail for drawer / GET by id."""

    hr_id: str
    email: str
    company: str
    name: str
    is_valid: bool
    status: str
