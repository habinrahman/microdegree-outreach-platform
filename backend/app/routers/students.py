"""Student management API.

This router supports:
- JSON payloads (new backend schema)
- Legacy multipart/form-data payloads used by the existing dashboard
"""
import logging
import os
import uuid
from uuid import UUID
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.database import get_db
from app.models import Student, Assignment, Response, Interview, HRIgnored
from app.models.email_campaign import EmailCampaign
from app.services.audit import log_event
from app.schemas.student import StudentCreate, StudentUpdate, StudentResponse, StudentHealthRow
from app.schemas.student_template import (
    StudentTemplateBundle,
    StudentTemplateBundleUpdate,
    StudentTemplateOut,
)
from app.services.student_email_health import compute_student_send_health_metrics
from app.services.resume_profile_extract import extract_profile_from_resume_file
from app.services.student_resume_update import (
    absolute_resume_path,
    backend_root_dir,
    count_queueable_campaigns_for_student,
    refresh_pending_campaign_templates,
    resumes_upload_dir,
)
from app.auth import require_api_key
from app.models.student_template import StudentTemplate

router = APIRouter(
    prefix="/students",
    tags=["students"],
    dependencies=[Depends(require_api_key)],
)

_STUDENT_UPDATE_ALLOWED = frozenset(
    {
        "name",
        "is_demo",
        "gmail_address",
        "experience_years",
        "skills",
        "resume_drive_file_id",
        "resume_file_name",
        "resume_path",
        "app_password",
        "domain",
        "linkedin_url",
        "gmail_connected",
        "status",
    }
)


def _connection_type(st: Student) -> str | None:
    # Never return secrets; only return a UI-safe derived label.
    token = (getattr(st, "gmail_refresh_token", None) or "").strip()
    if token:
        return "OAuth"
    app_pw = (getattr(st, "app_password", None) or "").strip()
    if app_pw:
        return "SMTP"
    return None


def to_student_public(st: Student) -> dict:
    ctype = _connection_type(st)
    return {
        "id": st.id,
        "name": st.name,
        "gmail_address": st.gmail_address,
        "status": getattr(st, "status", None) or "active",
        "domain": getattr(st, "domain", None),
        "gmail_connected": bool(ctype),
        "connection_type": ctype,
        "is_demo": bool(getattr(st, "is_demo", False)),
        "experience_years": int(getattr(st, "experience_years", 0) or 0),
        "skills": getattr(st, "skills", None),
        "resume_drive_file_id": getattr(st, "resume_drive_file_id", None),
        "resume_file_name": getattr(st, "resume_file_name", None),
        "resume_path": getattr(st, "resume_path", None),
        "resume_updated_at": getattr(st, "resume_updated_at", None),
        "active_resume_url": (
            f"/students/{st.id}/resume/current" if (getattr(st, "resume_path", None) or "").strip() else None
        ),
        "linkedin_url": getattr(st, "linkedin_url", None),
        "created_at": getattr(st, "created_at", None),
        "emails_sent_today": int(getattr(st, "emails_sent_today", 0) or 0),
        "last_sent_at": getattr(st, "last_sent_at", None),
        "email_health_status": getattr(st, "email_health_status", None) or "healthy",
    }
logger = logging.getLogger(__name__)

_TEMPLATE_TYPES = ("INITIAL", "FOLLOWUP_1", "FOLLOWUP_2", "FOLLOWUP_3")


def _empty_template_bundle() -> dict:
    return {k: None for k in _TEMPLATE_TYPES}


def _tmpl_to_out(row: StudentTemplate) -> dict:
    return {
        "template_type": str(row.template_type),
        "subject": row.subject,
        "body": row.body,
        "created_at": getattr(row, "created_at", None),
        "updated_at": getattr(row, "updated_at", None),
    }


@router.post("", response_model=StudentResponse)
@router.post("/", response_model=StudentResponse)
async def create_student(request: Request, db: Session = Depends(get_db)):
    """Add new student (JSON or legacy form-data)."""
    content_type = (request.headers.get("content-type") or "").lower()

    # Legacy dashboard sends multipart/form-data with fields: name,email,app_password,domain,resume(file)
    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        name = (form.get("name") or "").strip()
        email = (form.get("email") or "").strip()
        app_password = (form.get("app_password") or "").strip() or None
        domain = (form.get("domain") or "").strip() or None
        resume = form.get("resume")  # UploadFile or None

        if not name or not email:
            raise HTTPException(status_code=400, detail="Missing name or email")

        resume_path = None
        resume_file_name = None
        if resume is not None and hasattr(resume, "filename"):
            upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", "resumes")
            os.makedirs(upload_dir, exist_ok=True)
            resume_file_name = resume.filename
            safe_name = f"{uuid.uuid4()}_{resume.filename}"
            disk_path = os.path.join(upload_dir, safe_name)
            contents = await resume.read()
            with open(disk_path, "wb") as f:
                f.write(contents)
            # store relative path from backend/ for compatibility with existing sender
            resume_path = os.path.relpath(disk_path, start=os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

        obj = Student(
            name=name,
            gmail_address=email,
            app_password=app_password,
            domain=domain,
            resume_path=resume_path,
            resume_file_name=resume_file_name,
            status="active",
        )
    else:
        # JSON mode
        payload = await request.json()
        student = StudentCreate.model_validate(payload)
        obj = Student(**student.model_dump())

    db.add(obj)
    db.commit()
    db.refresh(obj)
    return to_student_public(obj)


@router.get("", response_model=list[StudentResponse])
@router.get("/", response_model=list[StudentResponse])
def list_students(include_demo: bool = False, db: Session = Depends(get_db)):
    """List all students."""
    try:
        logger.info("Fetching students...")
        q = db.query(Student)
        if not include_demo:
            q = q.filter(Student.is_demo.is_(False))
        if hasattr(Student, "is_fixture_test_data"):
            q = q.filter(Student.is_fixture_test_data.is_(False))
        rows = q.order_by(Student.created_at.desc()).all()
        logger.info("Students fetched: %s", len(rows))
        return [to_student_public(st) for st in rows]
    except Exception:
        logger.exception("Error in list_students")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/health", response_model=list[StudentHealthRow])
def list_students_health(include_demo: bool = False, db: Session = Depends(get_db)):
    """Per-student rolling 24h send health (blocked count, failure rate) and stored status."""
    q = db.query(Student)
    if not include_demo:
        q = q.filter(Student.is_demo.is_(False))
    if hasattr(Student, "is_fixture_test_data"):
        q = q.filter(Student.is_fixture_test_data.is_(False))
    rows: list[StudentHealthRow] = []
    for st in q.order_by(Student.created_at.desc()).all():
        m = compute_student_send_health_metrics(db, st.id)
        rows.append(
            StudentHealthRow(
                student_id=str(st.id),
                email=st.gmail_address,
                health_status=getattr(st, "email_health_status", None) or "healthy",
                failure_rate=m["failure_rate"],
                blocked_count=m["blocked_last_24h"],
            )
        )
    return rows


@router.get("/{student_id}/resume/meta")
def get_student_resume_meta(student_id: UUID, db: Session = Depends(get_db)):
    """Lightweight state for Update Resume dialog (pending campaigns, current file)."""
    st = db.query(Student).filter(Student.id == student_id).first()
    if not st:
        raise HTTPException(status_code=404, detail="Student not found")
    pending = count_queueable_campaigns_for_student(db, student_id)
    ru = getattr(st, "resume_updated_at", None)
    return {
        "has_pending_campaigns": pending > 0,
        "pending_campaign_count": int(pending),
        "resume_file_name": getattr(st, "resume_file_name", None),
        "resume_updated_at": ru.isoformat() if hasattr(ru, "isoformat") and ru else None,
        "active_resume_url": f"/students/{student_id}/resume/current"
        if (getattr(st, "resume_path", None) or "").strip()
        else None,
    }


@router.get("/{student_id}/resume/current")
def download_student_resume_current(student_id: UUID, db: Session = Depends(get_db)):
    """Download the active resume file (for View / verification)."""
    st = db.query(Student).filter(Student.id == student_id).first()
    if not st:
        raise HTTPException(status_code=404, detail="Student not found")
    rp = (getattr(st, "resume_path", None) or "").strip()
    if not rp:
        raise HTTPException(status_code=404, detail="No resume on file")
    try:
        full = absolute_resume_path(rp)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid resume path")
    if not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="Resume file missing on disk")
    name = (getattr(st, "resume_file_name", None) or "resume.pdf").strip() or "resume.pdf"
    return FileResponse(full, media_type="application/pdf", filename=name)


@router.post("/{student_id}/resume")
async def upload_student_resume(
    student_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    regenerate_pending: str = Form("false"),
    db: Session = Depends(get_db),
):
    """
    Replace active resume (soft: previous path kept in resume_archive_path; old file stays on disk).
    Re-parses PDF for experience/skills when possible. Optional: refresh pending|scheduled campaign bodies.
    """
    st = db.query(Student).filter(Student.id == student_id).first()
    if not st:
        raise HTTPException(status_code=404, detail="Student not found")

    regen = str(regenerate_pending or "").strip().lower() in ("1", "true", "yes", "on")

    raw_name = (file.filename or "resume.pdf").strip() or "resume.pdf"
    if not raw_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF resumes are supported for this upload path")

    max_bytes = 12 * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while True:
        block = await file.read(1024 * 1024)
        if not block:
            break
        total += len(block)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail="Resume too large (max 12MB)")
        chunks.append(block)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    old_rel = (getattr(st, "resume_path", None) or "").strip()
    safe_name = f"{uuid.uuid4()}_{raw_name}"
    disk_path = os.path.join(resumes_upload_dir(), safe_name)
    with open(disk_path, "wb") as f:
        f.write(data)
    new_rel = os.path.relpath(disk_path, start=backend_root_dir())

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)

    if old_rel:
        st.resume_archive_path = old_rel
    st.resume_path = new_rel
    st.resume_file_name = raw_name
    st.resume_updated_at = now_naive

    try:
        profile = extract_profile_from_resume_file(disk_path)
        if "experience_years" in profile:
            st.experience_years = int(profile["experience_years"])
        if profile.get("skills"):
            st.skills = str(profile["skills"])
    except Exception:
        logger.exception("resume profile extract failed student_id=%s", student_id)

    db.add(st)
    db.commit()
    db.refresh(st)

    regen_n = 0
    if regen:
        try:
            regen_n = refresh_pending_campaign_templates(db, st)
        except Exception:
            logger.exception("refresh_pending_campaign_templates failed student_id=%s", student_id)
        try:
            log_event(
                db,
                actor="system",
                action="pending_campaigns_regenerated",
                entity_type="Student",
                entity_id=str(student_id),
                meta={"count": int(regen_n)},
            )
        except Exception:
            pass

    try:
        log_event(
            db,
            actor="operator",
            action="resume_uploaded",
            entity_type="Student",
            entity_id=str(student_id),
            meta={
                "regenerate_pending": bool(regen),
                "pending_templates_refreshed": int(regen_n),
                "ip": (getattr(getattr(request, "client", None), "host", None) if request else None),
            },
        )
    except Exception:
        pass

    return {
        "ok": True,
        "message": "Resume updated successfully. Future emails will attach this file.",
        "resume_file_name": st.resume_file_name,
        "resume_updated_at": st.resume_updated_at.isoformat() if st.resume_updated_at else None,
        "active_resume_url": f"/students/{student_id}/resume/current",
        "pending_campaigns_refreshed": int(regen_n),
        "resume_refreshed_for_outreach": True,
    }


@router.get("/{student_id}/templates", response_model=StudentTemplateBundle)
def get_student_templates(student_id: UUID, db: Session = Depends(get_db)):
    st = db.query(Student.id).filter(Student.id == student_id).first()
    if not st:
        raise HTTPException(status_code=404, detail="Student not found")

    rows = (
        db.query(StudentTemplate)
        .filter(StudentTemplate.student_id == student_id)
        .all()
    )
    out = _empty_template_bundle()
    for r in rows:
        tt = str(r.template_type)
        if tt in out:
            out[tt] = _tmpl_to_out(r)
    return out


@router.put("/{student_id}/templates", response_model=StudentTemplateBundle)
def put_student_templates(
    student_id: UUID,
    payload: StudentTemplateBundleUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    st = db.query(Student).filter(Student.id == student_id).first()
    if not st:
        raise HTTPException(status_code=404, detail="Student not found")

    # Only apply keys the client actually sent (partial saves allowed).
    sent = set(payload.model_fields_set or set())
    # Validate keys (defense-in-depth: pydantic already constrains, but be strict)
    for k in sent:
        if k not in _TEMPLATE_TYPES:
            raise HTTPException(status_code=400, detail="Invalid template_type")

    # Transactional upsert
    changed: list[str] = []
    try:
        for tt in sent:
            value = getattr(payload, tt)
            existing = (
                db.query(StudentTemplate)
                .filter(
                    StudentTemplate.student_id == student_id,
                    StudentTemplate.template_type == tt,
                )
                .first()
            )
            if value is None:
                if existing is not None:
                    db.delete(existing)
                    changed.append(tt)
                continue

            # Pydantic already validated and stripped subject/body, but keep explicit bounds here too.
            subj = str(value.subject).strip()
            body = str(value.body).strip()
            if len(subj) > 300:
                raise HTTPException(status_code=400, detail="subject too long (max 300)")
            if len(body) > 10000:
                raise HTTPException(status_code=400, detail="body too long (max 10000)")

            # Optimistic concurrency: reject stale modal writes.
            if_match = (getattr(value, "if_match", None) or "").strip()
            if if_match and existing is not None:
                cur = getattr(existing, "updated_at", None) or getattr(existing, "created_at", None)
                cur_iso = cur.isoformat() if hasattr(cur, "isoformat") else None
                # accept exact match only (simple + predictable)
                if not cur_iso or if_match != cur_iso:
                    raise HTTPException(
                        status_code=409,
                        detail="Template changed since it was loaded. Reload and try again.",
                    )

            if existing is None:
                db.add(
                    StudentTemplate(
                        student_id=student_id,
                        template_type=tt,
                        subject=subj,
                        body=body,
                    )
                )
                changed.append(tt)
            else:
                existing.subject = subj
                existing.body = body
                existing.updated_at = datetime.utcnow()
                changed.append(tt)

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    # Return full bundle (idempotent)
    rows = (
        db.query(StudentTemplate)
        .filter(StudentTemplate.student_id == student_id)
        .all()
    )
    out = _empty_template_bundle()
    for r in rows:
        tt = str(r.template_type)
        if tt in out:
            out[tt] = _tmpl_to_out(r)

    # Lightweight audit log (metadata only, no template contents).
    if changed:
        actor = "operator"
        meta = {
            "student_id": str(student_id),
            "template_types": sorted(set(changed)),
            "ip": (getattr(getattr(request, "client", None), "host", None) if request else None),
        }
        try:
            log_event(
                db,
                actor=actor,
                action="student_templates_saved",
                entity_type="Student",
                entity_id=str(student_id),
                meta=meta,
            )
        except Exception:
            pass
    return out


@router.put("/{student_id}", response_model=StudentResponse)
def update_student(student_id: UUID, payload: StudentUpdate, db: Session = Depends(get_db)):
    """Update student."""
    obj = db.query(Student).filter(Student.id == student_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Student not found")
    data = payload.model_dump(exclude_unset=True)
    for k in _STUDENT_UPDATE_ALLOWED:
        if k in data:
            setattr(obj, k, data[k])
    db.commit()
    db.refresh(obj)
    return to_student_public(obj)


@router.delete("/{student_id}", response_model=StudentResponse)
def deactivate_student(student_id: UUID, db: Session = Depends(get_db)):
    """Deactivate student (set status to inactive)."""
    obj = db.query(Student).filter(Student.id == student_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Student not found")
    obj.status = "inactive"
    db.commit()
    db.refresh(obj)
    return to_student_public(obj)


@router.delete("/{student_id}/purge")
def purge_student(
    student_id: UUID,
    confirm: str = Query("", description="Must be exactly DELETE_STUDENT_PERMANENTLY"),
    db: Session = Depends(get_db),
):
    """
    Permanently delete a student and related rows to avoid FK issues in SQLite:
    - assignments, campaigns, responses, interviews, ignore rows
    """
    if (confirm or "").strip() != "DELETE_STUDENT_PERMANENTLY":
        raise HTTPException(
            status_code=400,
            detail="Add query parameter confirm=DELETE_STUDENT_PERMANENTLY to acknowledge permanent deletion",
        )
    obj = db.query(Student).filter(Student.id == student_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Student not found")

    ignores_deleted = db.query(HRIgnored).filter(HRIgnored.student_id == student_id).delete(synchronize_session=False)
    interviews_deleted = db.query(Interview).filter(Interview.student_id == student_id).delete(synchronize_session=False)
    responses_deleted = db.query(Response).filter(Response.student_id == student_id).delete(synchronize_session=False)
    campaigns_deleted = db.query(EmailCampaign).filter(EmailCampaign.student_id == student_id).delete(synchronize_session=False)
    assignments_deleted = db.query(Assignment).filter(Assignment.student_id == student_id).delete(synchronize_session=False)

    db.delete(obj)
    db.commit()

    log_event(
        db,
        actor="admin",
        action="student_deleted",
        entity_type="Student",
        entity_id=str(student_id),
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
        "deleted_student_id": str(student_id),
        "assignments_deleted": int(assignments_deleted or 0),
        "campaigns_deleted": int(campaigns_deleted or 0),
        "responses_deleted": int(responses_deleted or 0),
        "interviews_deleted": int(interviews_deleted or 0),
        "ignores_deleted": int(ignores_deleted or 0),
    }
