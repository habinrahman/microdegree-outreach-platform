"""Read-only priority outreach queue API (Phase 1)."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.schemas.priority_queue import (
    PriorityQueueResponse,
    PriorityQueueRow,
    PriorityQueueSummary,
    PriorityQueueSummaryOnlyResponse,
    SchedulerPriorityHookDoc,
)
from app.services.priority_queue_engine import compute_priority_queue, scheduler_priority_hook_enabled

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/queue", tags=["priority-queue"], dependencies=[Depends(require_api_key)])


def _parse_computed_at(iso_s: str) -> datetime:
    if iso_s.endswith("Z"):
        iso_s = iso_s[:-1] + "+00:00"
    return datetime.fromisoformat(iso_s)


@router.get("/priority", response_model=PriorityQueueResponse)
def get_priority_queue(
    db: Session = Depends(get_db),
    bucket: str | None = Query(None, description="Filter by queue_bucket"),
    student_id: UUID | None = Query(None),
    tier: str | None = Query(None, description="HR health tier A|B|C|D"),
    only_due: bool = Query(False, description="Only SEND_NOW or FOLLOW_UP_DUE"),
    limit: int = Query(200, ge=1, le=500),
    include_demo: bool = Query(False),
    diversified: bool = Query(
        False,
        description="Apply Phase 2 diversity (HR cap, student floor, exploration, optional MMR)",
    ),
) -> Any:
    t0 = time.perf_counter()
    data = compute_priority_queue(
        db,
        bucket=bucket,
        student_id=student_id,
        tier=tier,
        only_due=only_due,
        limit=limit,
        include_rows=True,
        include_demo=include_demo,
        diversified=diversified,
    )
    elapsed = time.perf_counter() - t0
    if elapsed > 2.0:
        logger.warning(
            "GET /queue/priority compute_priority_queue slow: %.2fs limit=%s diversified=%s",
            elapsed,
            limit,
            diversified,
        )
    else:
        logger.debug("GET /queue/priority compute_priority_queue %.3fs", elapsed)
    return PriorityQueueResponse(
        computed_at_utc=_parse_computed_at(data["computed_at_utc"]),
        summary=PriorityQueueSummary(**data["summary"]),
        rows=[PriorityQueueRow(**r) for r in data["rows"]],
        diversity_metrics=data.get("diversity_metrics") or {},
    )


@router.get("/priority/summary", response_model=PriorityQueueSummaryOnlyResponse)
def get_priority_queue_summary(
    db: Session = Depends(get_db),
    bucket: str | None = Query(None),
    student_id: UUID | None = Query(None),
    tier: str | None = Query(None),
    only_due: bool = Query(False),
    limit: int = Query(500, ge=1, le=5000, description="Scan depth for summary aggregates"),
    include_demo: bool = Query(False),
) -> Any:
    t0 = time.perf_counter()
    data = compute_priority_queue(
        db,
        bucket=bucket,
        student_id=student_id,
        tier=tier,
        only_due=only_due,
        limit=limit,
        include_rows=False,
        include_demo=include_demo,
    )
    elapsed = time.perf_counter() - t0
    if elapsed > 2.0:
        logger.warning(
            "GET /queue/priority/summary compute_priority_queue slow: %.2fs limit=%s",
            elapsed,
            limit,
        )
    return PriorityQueueSummaryOnlyResponse(
        computed_at_utc=_parse_computed_at(data["computed_at_utc"]),
        summary=PriorityQueueSummary(**data["summary"]),
    )


@router.get("/priority/scheduler-hook", response_model=SchedulerPriorityHookDoc)
def get_scheduler_priority_hook_design() -> SchedulerPriorityHookDoc:
    """Documents SCHEDULER_USE_PRIORITY_QUEUE (default off). Phase 1 does not wire the scheduler."""
    return SchedulerPriorityHookDoc(enabled_in_environment=scheduler_priority_hook_enabled())
