"""HR contact management API."""
import io
import csv
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.models import HRContact, EmailCampaign
from app.schemas.hr_contact import HRContactCreate, HRContactUpdate, HRContactResponse
from app.services.hr_listing import query_hrs_without_initial_sent
from app.services.analytics_service import compute_hr_scores

# NOTE: no prefix here; `main.py` mounts this router at both `/hr` and `/hrs`
router = APIRouter(tags=["hr_contacts"], dependencies=[Depends(require_api_key)])

# CSV columns: name, company, email, linkedin, city, source
CSV_COLUMNS = ["name", "company", "email", "linkedin", "city", "source"]


@router.post("", response_model=HRContactResponse)
@router.post("/", response_model=HRContactResponse)
def create_hr(hr: HRContactCreate, db: Session = Depends(get_db)):
    """Add HR manually. Rejects duplicate email."""
    existing = db.query(HRContact).filter(HRContact.email == hr.email.strip().lower()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Duplicate HR email address")
    obj = HRContact(
        name=hr.name,
        company=hr.company,
        email=hr.email.strip().lower(),
        linkedin_url=hr.linkedin_url,
        designation=hr.designation,
        city=hr.city,
        source=hr.source,
        status=hr.status,
        is_valid=True,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("", response_model=list[HRContactResponse])
@router.get("/", response_model=list[HRContactResponse])
def list_hr(
    skip: int = 0,
    limit: int = 500,
    student_id: UUID | None = None,
    db: Session = Depends(get_db),
):
    """List HR contacts who have not yet had the first campaign email (seq 1) sent.

    Optional ``student_id``: exclude only when *that student* has already sent the initial
    to the HR (for controlled multi-select outreach).
    """
    hrs = (
        query_hrs_without_initial_sent(db, student_id=student_id)
        .order_by(HRContact.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    sent_ids: set = set()
    replied_ids: set = set()
    if student_id is not None and hrs:
        hr_ids = [h.id for h in hrs]
        sent_ids = {
            r[0]
            for r in db.query(EmailCampaign.hr_id)
            .filter(
                EmailCampaign.student_id == student_id,
                EmailCampaign.hr_id.in_(hr_ids),
                EmailCampaign.status == "sent",
            )
            .distinct()
            .all()
        }
        replied_ids = {
            r[0]
            for r in db.query(EmailCampaign.hr_id)
            .filter(
                EmailCampaign.student_id == student_id,
                EmailCampaign.hr_id.in_(hr_ids),
                EmailCampaign.reply_text.isnot(None),
            )
            .distinct()
            .all()
        }
    hr_score_map: dict = {}
    if hrs:
        hr_score_map = compute_hr_scores(db, hr_ids=[h.id for h in hrs])

    out: list[HRContactResponse] = []
    for h in hrs:
        item = HRContactResponse.model_validate(h)
        updates: dict = {"score": hr_score_map.get(h.id)}
        if student_id is not None:
            updates["sent"] = h.id in sent_ids
            updates["replied"] = h.id in replied_ids
        item = item.model_copy(update=updates)
        out.append(item)
    return out


@router.put("/{hr_id}", response_model=HRContactResponse)
def update_hr(hr_id: UUID, payload: HRContactUpdate, db: Session = Depends(get_db)):
    """Update HR contact."""
    obj = db.query(HRContact).filter(HRContact.id == hr_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="HR contact not found")
    data = payload.model_dump(exclude_unset=True)
    if "email" in data and data["email"]:
        data["email"] = data["email"].strip().lower()
        other = db.query(HRContact).filter(HRContact.email == data["email"], HRContact.id != hr_id).first()
        if other:
            raise HTTPException(status_code=400, detail="Duplicate HR email address")
    for k, v in data.items():
        setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj


@router.post("/upload")
@router.post("/upload/")
def upload_hr_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload HR contacts via CSV.
    Columns: name, company, email, linkedin, city, source
    Rejects duplicate emails (skips row and reports).
    """
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
    normalized_headers = [h.strip().lower() for h in reader.fieldnames]
    if "email" not in normalized_headers:
        raise HTTPException(status_code=400, detail="CSV must have 'email' column")
    created = 0
    duplicates = []
    errors = []
    for row in reader:
        raw = {k.strip(): v.strip() if v else "" for k, v in row.items()}
        email = raw.get("email") or raw.get("Email") or ""
        if not email:
            errors.append(f"Row missing email: {raw}")
            continue
        email = email.lower()
        if db.query(HRContact).filter(HRContact.email == email).first():
            duplicates.append(email)
            continue
        name = raw.get("name") or raw.get("Name") or ""
        company = raw.get("company") or raw.get("Company") or ""
        if not name or not company:
            errors.append(f"Row missing name/company: {raw}")
            continue
        hr = HRContact(
            name=name,
            company=company,
            email=email,
            linkedin_url=raw.get("linkedin") or raw.get("Linkedin") or None,
            designation=None,
            city=raw.get("city") or raw.get("City") or None,
            source=raw.get("source") or raw.get("Source") or None,
            status="active",
        )
        db.add(hr)
        created += 1
    db.commit()
    return {
        "created": created,
        "duplicate_emails_skipped": duplicates,
        "errors": errors,
    }
