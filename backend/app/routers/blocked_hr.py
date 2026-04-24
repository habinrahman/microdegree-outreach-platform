"""Globally blocked HR emails (e.g. bounce-driven blacklist)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.models import BlockedHR

router = APIRouter(prefix="/blocked-hrs", tags=["blocked_hrs"], dependencies=[Depends(require_api_key)])


@router.get("")
@router.get("/")
def get_blocked_hrs(db: Session = Depends(get_db)):
    rows = db.query(BlockedHR).order_by(BlockedHR.created_at.desc()).all()
    return [
        {
            "id": str(r.id),
            "email": r.email,
            "company": r.company,
            "reason": r.reason,
            "exported_to_sheet": r.exported_to_sheet,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
