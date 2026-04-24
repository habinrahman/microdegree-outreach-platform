"""Dashboard-compatible HR routes: GET /hr-contacts, POST /hr-contacts/upload."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.models.hr_contact import HRContact
from app.routers.hr import upload_hr_csv
from app.schemas.hr_health import HRHealthDetailResponse, HRHealthScores, HRScoreReason
from app.services.hr_health_scoring import TIER_RANK, compute_health_for_hr_ids, compute_health_for_one

router = APIRouter(prefix="/hr-contacts", tags=["hr_contacts"], dependencies=[Depends(require_api_key)])


@router.get("/{hr_id}/health")
def get_hr_contact_health(hr_id: UUID, db: Session = Depends(get_db)):
    """Explainable health + opportunity scores and tier for one HR (detail drawer)."""
    hr = db.query(HRContact).filter(HRContact.id == hr_id).first()
    if not hr:
        raise HTTPException(status_code=404, detail="HR contact not found")
    raw = compute_health_for_one(db, hr_id)
    scores = HRHealthScores(
        tier=raw["tier"],
        health_score=raw["health_score"],
        opportunity_score=raw["opportunity_score"],
        health_reasons=[HRScoreReason(**r) for r in raw["health_reasons"]],
        opportunity_reasons=[HRScoreReason(**r) for r in raw["opportunity_reasons"]],
        components=raw["components"],
    )
    return HRHealthDetailResponse(
        hr_id=str(hr.id),
        email=hr.email,
        company=hr.company,
        name=hr.name,
        is_valid=bool(hr.is_valid),
        status=hr.status or "",
        **scores.model_dump(),
    )


@router.get("")
@router.get("/")
def list_hr_contacts(
    skip: int = 0,
    limit: int = 5000,
    include_demo: bool = False,
    include_health: bool = False,
    tier: str | None = Query(None, description="Filter by tier A/B/C/D (implies include_health)"),
    db: Session = Depends(get_db),
):
    q = db.query(HRContact).order_by(HRContact.created_at.desc())
    if not include_demo:
        q = q.filter(HRContact.is_demo.is_(False))
    rows = q.offset(skip).limit(min(max(limit, 1), 10000)).all()

    want_health = include_health or (tier and tier.strip().upper() in TIER_RANK)
    bundles = compute_health_for_hr_ids(db, [h.id for h in rows]) if want_health and rows else {}

    out: list[dict] = []
    for h in rows:
        item = {
            "id": str(h.id),
            "name": h.name,
            "company": h.company,
            "email": h.email,
            "domain": h.domain,
            "status": h.status,
            "is_valid": bool(h.is_valid),
        }
        if want_health:
            b = bundles.get(h.id) or {}
            item["tier"] = b.get("tier", "D")
            item["health_score"] = b.get("health_score", 0.0)
            item["opportunity_score"] = b.get("opportunity_score", 0.0)
            item["health_reasons"] = b.get("health_reasons", [])
            item["opportunity_reasons"] = b.get("opportunity_reasons", [])
            item["score_components"] = b.get("components", {})
        if tier and tier.strip().upper() in TIER_RANK:
            if (item.get("tier") or "").upper() != tier.strip().upper():
                continue
        out.append(item)
    return out


@router.post("/upload")
@router.post("/upload/")
def hr_contacts_upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    return upload_hr_csv(file=file, db=db)
