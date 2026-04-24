"""Legacy HR endpoints expected by the existing dashboard.

Dashboard expects:
- GET /hrs/ -> list[{ id, company, hr_name, email, domain }]
- POST /hrs/upload -> CSV with columns: company,hr_name,email,domain
"""

import csv
import logging
import io
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.models import HRContact, HRIgnored, Student, Assignment, Response, Interview
from app.models.email_campaign import EmailCampaign
from app.services.audit import log_event
from app.services.hr_listing import query_hrs_without_initial_sent

router = APIRouter(prefix="/hrs", tags=["hr_contacts_legacy"], dependencies=[Depends(require_api_key)])
logger = logging.getLogger(__name__)


@router.get("/")
def list_hrs_legacy(
    student_id: UUID | None = None,
    include_demo: bool = False,
    db: Session = Depends(get_db),
):
    """
    List HRs who have not yet had sequence 1 (initial) marked sent.

    If ``student_id`` is set, only that student's sends count (per-student outreach).
    If omitted, any student's sent initial hides the HR (legacy global pool behavior).
    """
    if student_id is not None:
        q = query_hrs_without_initial_sent(db, student_id)
    else:
        q = query_hrs_without_initial_sent(db)

    # Safe HR filtering: hide invalid/bounced HRs (do not break student_id logic).
    q = q.filter(HRContact.status != "invalid")
    if not include_demo:
        q = q.filter(HRContact.is_demo.is_(False))
    rows = q.order_by(HRContact.created_at.desc()).all()
    return [
        {
            "id": str(r.id),
            "company": r.company,
            "hr_name": r.name,
            "email": r.email,
            "domain": getattr(r, "domain", None),
        }
        for r in rows
    ]

@router.post("/")
@router.post("")
def create_hr_legacy(payload: dict, db: Session = Depends(get_db)):
    """Manual add HR (legacy shape: company, hr_name, email, domain)."""
    company = (payload.get("company") or "").strip()
    hr_name = (payload.get("hr_name") or payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    domain = (payload.get("domain") or None)
    if isinstance(domain, str):
        domain = domain.strip() or None

    if not company or not hr_name or not email:
        raise HTTPException(status_code=400, detail="Missing company/hr_name/email")

    if db.query(HRContact).filter(HRContact.email == email).first():
        raise HTTPException(status_code=400, detail="Duplicate HR email address")

    hr = HRContact(name=hr_name, company=company, email=email, domain=domain, status="active")
    db.add(hr)
    db.commit()
    db.refresh(hr)

    log_event(
        db,
        actor="admin",
        action="hr_created",
        entity_type="HRContact",
        entity_id=str(hr.id),
        meta={"email": email, "company": company},
    )

    return {"ok": True, "id": str(hr.id)}


@router.post("/upload")
@router.post("/upload/")
def upload_hrs_csv_legacy(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    content = file.file.read()
    try:
        text = content.decode("utf-8")
    except Exception:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    # expected: company, hr_name, email, 
    headers = [h.strip().lower() for h in reader.fieldnames]
    if "email" not in headers:
        raise HTTPException(status_code=400, detail="CSV must have 'email' column")

    created = 0
    duplicates = []
    errors = []
    seen_emails = set()
    existing_emails = set(
        e[0] for e in db.query(HRContact.email).all()
    )

    for row in reader:
        try:
            raw = {k.strip().lower(): (v.strip() if v else "") for k, v in row.items()}

            email = (raw.get("email") or "").strip().lower()

            # Email mandatory
            if not email:
                errors.append(f"Row missing email: {row}")
                continue

            # Skip duplicates inside same CSV
            if email in seen_emails:
                duplicates.append(email)
                continue
            seen_emails.add(email)

            # Skip duplicates already in DB
            if email in existing_emails:
                duplicates.append(email)
                continue

            # Safe defaults
            company = raw.get("company") or "Unknown"
            hr_name = raw.get("hr_name") or raw.get("name") or "HR"
            domain = (raw.get("domain") or "").strip() or None

            hr = HRContact(
                name=hr_name,
                company=company,
                email=email,
                domain=domain,
                status="active",
            )
            db.add(hr)
            created += 1
            existing_emails.add(email)
        except Exception as e:
            logger.error("Internal server error", exc_info=e)
            errors.append("internal_error")

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Internal server error", exc_info=e)
        errors.append("commit_failed")
    return {
        "created": created,
        "duplicates": len(duplicates),
        "errors": errors,
        "message": f"{created} HRs added, {len(duplicates)} duplicates skipped",
    }


@router.post("/{hr_id}/ignore")
def ignore_hr_legacy(hr_id: UUID, student_id: UUID, db: Session = Depends(get_db)):
    """Mark HR as ignored by a student (used for blacklisting rule)."""
    hr = db.query(HRContact).filter(HRContact.id == hr_id).first()
    if not hr:
        raise HTTPException(status_code=404, detail="HR not found")
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    exists = (
        db.query(HRIgnored)
        .filter(HRIgnored.student_id == student_id, HRIgnored.hr_id == hr_id)
        .first()
        is not None
    )
    if exists:
        return {"ok": True, "ignored": True, "already": True}

    row = HRIgnored(student_id=student_id, hr_id=hr_id)
    db.add(row)
    db.commit()

    # update quick counter field for legacy visibility
    count = db.query(HRIgnored.student_id).filter(HRIgnored.hr_id == hr_id).distinct().count()
    hr.ignored_by_students_count = str(count)
    if count >= 3:
        hr.status = "blacklisted"
    db.commit()

    log_event(
        db,
        actor="admin",
        action="hr_ignored",
        entity_type="HRContact",
        entity_id=str(hr_id),
        meta={"student_id": str(student_id), "ignored_count": count},
    )

    return {"ok": True, "ignored": True, "ignored_count": count, "hr_status": hr.status}


@router.delete("/{hr_id}")
def delete_hr_legacy(hr_id: UUID, db: Session = Depends(get_db)):
    """
    Delete HR and all related rows to avoid FK issues in SQLite:
    - assignments, campaigns, responses, interviews, ignores
    """
    hr = db.query(HRContact).filter(HRContact.id == hr_id).first()
    if not hr:
        raise HTTPException(status_code=404, detail="HR not found")

    ignores_deleted = db.query(HRIgnored).filter(HRIgnored.hr_id == hr_id).delete(synchronize_session=False)
    interviews_deleted = db.query(Interview).filter(Interview.hr_id == hr_id).delete(synchronize_session=False)
    responses_deleted = db.query(Response).filter(Response.hr_id == hr_id).delete(synchronize_session=False)
    campaigns_deleted = db.query(EmailCampaign).filter(EmailCampaign.hr_id == hr_id).delete(synchronize_session=False)
    assignments_deleted = db.query(Assignment).filter(Assignment.hr_id == hr_id).delete(synchronize_session=False)

    db.delete(hr)
    db.commit()

    log_event(
        db,
        actor="admin",
        action="hr_deleted",
        entity_type="HRContact",
        entity_id=str(hr_id),
        meta={
            "assignments_deleted": int(assignments_deleted or 0),
            "campaigns_deleted": int(campaigns_deleted or 0),
            "responses_deleted": int(responses_deleted or 0),
            "interviews_deleted": int(interviews_deleted or 0),
            "ignores_deleted": int(ignores_deleted or 0),
        },
    )

    return {
        "ok": True,
        "deleted_hr_id": str(hr_id),
        "assignments_deleted": int(assignments_deleted or 0),
        "campaigns_deleted": int(campaigns_deleted or 0),
        "responses_deleted": int(responses_deleted or 0),
        "interviews_deleted": int(interviews_deleted or 0),
        "ignores_deleted": int(ignores_deleted or 0),
    }

