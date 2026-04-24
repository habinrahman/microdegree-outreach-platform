"""Notifications API – list and mark read for placement team (Part 3)."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_admin, require_api_key
from app.database import get_db
from app.models import Notification
from app.models.email_campaign import EmailCampaign
from app.services.audit import log_event
from app.services.notification_dedupe import dedupe_notifications_for_display

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    dependencies=[Depends(require_api_key)],
)


class NotificationCreate(BaseModel):
    type: str
    title: str
    body: str


@router.get("/")
def list_notifications(
    db: Session = Depends(get_db),
    unread_only: bool = False,
    student_id: UUID | None = None,
):
    """List notifications; optional filter by unread."""
    q = db.query(Notification).order_by(Notification.created_at.desc())
    if unread_only:
        q = q.filter(Notification.status == "unread")
    if student_id is not None:
        # Notifications are deduped primarily for reply alerts; those are linked via reply_for_campaign_id.
        # Filter by student by joining the underlying campaign. Notifications without a campaign link
        # are not included in per-student views.
        q = (
            q.outerjoin(EmailCampaign, Notification.reply_for_campaign_id == EmailCampaign.id)
            .filter(EmailCampaign.student_id == student_id)
        )
    rows = q.limit(400).all()
    rows = dedupe_notifications_for_display(rows, max_items=100)
    return [
        {
            "id": str(n.id),
            "type": n.type,
            "title": n.title,
            "body": n.body,
            "status": n.status,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in rows
    ]


@router.post("/", dependencies=[Depends(require_admin)])
def create_notification(payload: NotificationCreate, db: Session = Depends(get_db)):
    """ADMIN: create a notification manually."""
    n = Notification(type=payload.type, title=payload.title, body=payload.body, status="unread")
    db.add(n)
    db.commit()
    db.refresh(n)
    log_event(
        db,
        actor="admin",
        action="notification_created",
        entity_type="Notification",
        entity_id=str(n.id),
        meta={"type": payload.type, "title": payload.title},
    )
    return {"id": str(n.id)}


@router.post("/{notification_id}/read")
def mark_notification_read(notification_id: UUID, db: Session = Depends(get_db)):
    """Mark a notification as read."""
    n = db.query(Notification).filter(Notification.id == notification_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.status = "read"
    db.commit()
    return {"id": str(n.id), "status": "read"}
