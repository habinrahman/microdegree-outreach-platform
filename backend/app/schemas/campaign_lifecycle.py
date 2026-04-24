"""API schemas for read-only campaign lifecycle visualization."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LifecycleStatusCount(BaseModel):
    status: str
    count: int = Field(..., ge=0)
    is_terminal: bool


class LifecycleUnknownStatusCount(BaseModel):
    status: str
    count: int = Field(..., ge=0)


class LifecycleEdge(BaseModel):
    source: str
    target: str


class LifecycleVisualizationResponse(BaseModel):
    computed_at_utc: str
    total_campaign_rows: int = Field(..., ge=0)
    status_counts: list[LifecycleStatusCount]
    unknown_status_counts: list[LifecycleUnknownStatusCount]
    edges: list[LifecycleEdge]
    self_loop_statuses: list[str]
    terminal_statuses: list[str]
    bulk_transitions: list[str]
    mermaid_state_diagram: str
