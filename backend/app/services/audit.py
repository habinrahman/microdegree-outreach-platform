"""Audit logging helpers."""
import json
from sqlalchemy.orm import Session

from app.models import AuditLog


def log_event(
    db: Session,
    *,
    actor: str | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    meta: dict | None = None,
):
    row = AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        meta=json.dumps(meta or {}, ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    return row

