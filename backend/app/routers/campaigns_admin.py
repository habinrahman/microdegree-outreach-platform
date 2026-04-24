"""Admin/testing endpoints for campaigns and HR lifecycle."""
from uuid import UUID
from fastapi import APIRouter, Depends

from app.auth import require_admin
from app.services.campaign_scheduler import run_campaign_job
from app.services.hr_lifecycle import run_hr_lifecycle_job
from app.services.gmail_monitor import run_gmail_monitor_job

router = APIRouter(prefix="/campaigns", tags=["campaigns_admin"], dependencies=[Depends(require_admin)])


@router.post("/hr_lifecycle/run_once")
def run_hr_lifecycle_once():
    """ADMIN: Run HR lifecycle job once (no_response, blacklist, unpause)."""
    return run_hr_lifecycle_job()


@router.post("/gmail_monitor/run_once")
def run_gmail_monitor_once(max_students: int = 25):
    """ADMIN: Run Gmail inbox monitor once (reply detection)."""
    return run_gmail_monitor_job(max_students=max_students)


@router.post("/run_once")
def run_once(
    limit: int = 5,
    student_id: UUID | None = None,
    hr_id: UUID | None = None,
):
    """
    TEST/ADMIN: Send campaigns immediately.
    - ignores business hours window
    - ignores scheduled_at time
    - no random delay between emails
    """
    return run_campaign_job(
        ignore_window=True,
        ignore_scheduled_time=True,
        skip_delay=True,
        limit=limit,
        student_id=str(student_id) if student_id else None,
        hr_id=str(hr_id) if hr_id else None,
        ignore_deliverability_pause=True,
    )

