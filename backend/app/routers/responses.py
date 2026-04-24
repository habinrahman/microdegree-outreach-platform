"""Record HR responses; cancels remaining follow-up campaigns for that assignment."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.models import Response as ResponseModel, HRContact
from app.schemas.response_schema import ResponseCreate
from app.services.campaign_cancel import cancel_followups_for_hr_response
from app.utils.datetime_utils import ensure_utc

router = APIRouter(prefix="/responses", tags=["responses"], dependencies=[Depends(require_api_key)])


@router.post("")
def create_response(body: ResponseCreate, db: Session = Depends(get_db)):
    """Record that an HR responded. Cancels remaining follow-up emails for this student–HR pair.
    If response_type is 'not_hiring', HR is paused for 90 days."""
    r = ResponseModel(
        student_id=body.student_id,
        hr_id=body.hr_id,
        response_date=body.response_date,
        response_type=body.response_type,
        notes=body.notes,
    )
    db.add(r)
    hr = db.query(HRContact).filter(HRContact.id == body.hr_id).first()
    if hr:
        hr.status = "responded"
        if (body.response_type or "").lower() == "not_hiring":
            hr.status = "paused"
            hr.paused_until = ensure_utc(datetime.now(timezone.utc) + timedelta(days=90))
    db.commit()
    cancelled = cancel_followups_for_hr_response(db, body.student_id, body.hr_id, reason="response_api")
    return {"message": "Response recorded", "followups_cancelled": cancelled}
