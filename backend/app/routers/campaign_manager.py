"""Campaign-level controls: create, list, pause, resume."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.utils.datetime_utils import ensure_utc
from app.models import Campaign, Student
from app.models.email_campaign import EmailCampaign

router = APIRouter(prefix="/campaign-manager", tags=["campaign-manager"], dependencies=[Depends(require_api_key)])


class CreateCampaignBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    student_id: UUID
    email_campaign_ids: list[UUID] = []


def _campaign_to_dict(c: Campaign) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "student_id": str(c.student_id),
        "status": c.status,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.get("")
def list_campaign_groups(student_id: UUID | None = None, include_demo: bool = False, db: Session = Depends(get_db)):
    q = db.query(Campaign).join(Student, Campaign.student_id == Student.id)
    if not include_demo:
        q = q.filter(Student.is_demo.is_(False))
    q = q.order_by(Campaign.created_at.desc())
    if student_id is not None:
        q = q.filter(Campaign.student_id == student_id)
    return [_campaign_to_dict(c) for c in q.all()]


@router.post("")
def create_campaign_group(payload: CreateCampaignBody, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.id == payload.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    c = Campaign(
        name=payload.name.strip(),
        student_id=payload.student_id,
        status="running",
        created_at=ensure_utc(datetime.now(timezone.utc)),
    )
    if not c.name:
        raise HTTPException(status_code=400, detail="Campaign name is required")
    db.add(c)
    db.flush()

    if payload.email_campaign_ids:
        rows = (
            db.query(EmailCampaign)
            .filter(
                EmailCampaign.id.in_(payload.email_campaign_ids),
                EmailCampaign.student_id == payload.student_id,
            )
            .all()
        )
        for row in rows:
            row.campaign_id = c.id

    db.commit()
    db.refresh(c)
    return _campaign_to_dict(c)


@router.post("/{campaign_id}/pause")
def pause_campaign_group(campaign_id: UUID, db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    c.status = "paused"
    db.commit()
    db.refresh(c)
    return _campaign_to_dict(c)


@router.post("/{campaign_id}/resume")
def resume_campaign_group(campaign_id: UUID, db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    c.status = "running"
    db.commit()
    db.refresh(c)
    return _campaign_to_dict(c)
