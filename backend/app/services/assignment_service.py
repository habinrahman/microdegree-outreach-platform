"""Assignment business logic: same HR may be assigned to many students; duplicate (student, hr) blocked."""
from uuid import UUID
from sqlalchemy.orm import Session

from app.models import Student, HRContact, Assignment
from app.services.hr_health_scoring import TIER_RANK, compute_health_for_hr_ids, tier_at_or_above


def get_active_hr_ids_for_student(db: Session, student_id: UUID) -> set[UUID]:
    """HR ids this student already has an active assignment for (not global exclusivity)."""
    rows = (
        db.query(Assignment.hr_id)
        .filter(Assignment.student_id == student_id, Assignment.status == "active")
        .all()
    )
    return {r[0] for r in rows}


def validate_and_assign(
    db: Session,
    student_id: UUID,
    hr_ids: list[UUID],
    min_hr_tier: str | None = None,
) -> tuple[list[Assignment], list[UUID], list[UUID], list[UUID], list[UUID]]:
    """
    Validate and create assignments (only HRContact.is_valid == True may be assigned).
    Optional ``min_hr_tier`` (A/B/C/D): HRs below that tier are rejected as ``rejected_low_tier``.

    Returns:
        (created, rejected_already_assigned, rejected_not_found_in_db, rejected_invalid_hr, rejected_low_tier).
    """
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return [], [], list(hr_ids), [], []

    if student.status != "active":
        return [], list(hr_ids), [], [], []

    hr_ids_unique = list(dict.fromkeys(hr_ids))  # preserve order, dedupe
    already_for_student = get_active_hr_ids_for_student(db, student_id)
    found_hr_ids = set(
        r[0]
        for r in db.query(HRContact.id).filter(HRContact.id.in_(hr_ids_unique)).all()
    )
    valid_hr_ids = set(
        r[0]
        for r in db.query(HRContact.id)
        .filter(HRContact.id.in_(hr_ids_unique), HRContact.is_valid.is_(True))
        .all()
    )

    rejected_already = [h for h in hr_ids_unique if h in already_for_student]
    rejected_not_found = [h for h in hr_ids_unique if h not in found_hr_ids]
    rejected_invalid = [h for h in hr_ids_unique if h in found_hr_ids and h not in valid_hr_ids]
    to_assign = [h for h in hr_ids_unique if h not in already_for_student and h in valid_hr_ids]

    rejected_low_tier: list[UUID] = []
    mt = (min_hr_tier or "").strip().upper()
    if mt and mt in TIER_RANK and to_assign:
        bundles = compute_health_for_hr_ids(db, to_assign)
        filtered: list[UUID] = []
        for hid in to_assign:
            tier = (bundles.get(hid) or {}).get("tier") or "D"
            if tier_at_or_above(str(tier), mt):
                filtered.append(hid)
            else:
                rejected_low_tier.append(hid)
        to_assign = filtered

    created = []
    for hr_id in to_assign:
        assignment = Assignment(
            student_id=student_id,
            hr_id=hr_id,
            status="active",
        )
        db.add(assignment)
        created.append(assignment)
    if created:
        db.commit()
        for a in created:
            db.refresh(a)
        # Campaigns are NOT auto-created on assignment — only when user explicitly sends
        # (see outreach_service.send_one, outreach manual_send, etc.).
        # Previously: generate_campaigns_for_assignments(db, created)

    return created, rejected_already, rejected_not_found, rejected_invalid, rejected_low_tier
