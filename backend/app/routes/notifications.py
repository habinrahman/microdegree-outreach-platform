from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database.config import get_db
from app.models.notification import Notification
from app.services.notification_dedupe import dedupe_notifications_for_display

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.get("/notifications")
@router.get("/notifications/")
def get_notifications(db: Session = Depends(get_db)):
    rows = (
        db.query(Notification)
        .order_by(Notification.created_at.desc())
        .limit(400)
        .all()
    )
    notifications = dedupe_notifications_for_display(rows, max_items=50)

    return [
        {
            "id": str(n.id),
            "title": n.title,
            "body": n.body,
            "status": n.status,
            "type": n.type,
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "reply_for_campaign_id": (
                str(n.reply_for_campaign_id)
                if getattr(n, "reply_for_campaign_id", None) is not None
                else None
            ),
        }
        for n in notifications
    ]
