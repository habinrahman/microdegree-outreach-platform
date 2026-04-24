"""Audit log API (admin)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(require_admin)])


@router.get("/")
def list_audit(db: Session = Depends(get_db), limit: int = 200):
    rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 1000)).all()
    return [
        {
            "id": str(r.id),
            "actor": r.actor,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "meta": r.meta,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/clear")
def clear_audit(db: Session = Depends(get_db)):
    deleted = db.query(AuditLog).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "deleted": int(deleted or 0)}
