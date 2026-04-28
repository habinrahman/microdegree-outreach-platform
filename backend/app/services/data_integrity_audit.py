"""Read-only cross-module consistency checks for pilot / operator confidence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, literal, or_
from sqlalchemy.orm import Session, aliased

from app.models.assignment import Assignment
from app.models.email_campaign import EmailCampaign
from app.models.hr_contact import HRContact
from app.models.student import Student
from app.utils.campaign_query_filters import email_campaigns_scoped_to_hr


def reply_thread_consistency_check(db: Session, *, base) -> dict[str, Any]:
    """
    Flags impossible or weak linkage on replied / outbound rows (read-only).
    `base` must be an EmailCampaign query scoped like analytics (e.g. HR demo filter).
    """
    e2 = aliased(EmailCampaign)

    reply_before_sent = (
        base.filter(
            EmailCampaign.replied.is_(True),
            EmailCampaign.sent_at.isnot(None),
            or_(
                and_(
                    EmailCampaign.reply_received_at.isnot(None),
                    EmailCampaign.reply_received_at < EmailCampaign.sent_at,
                ),
                and_(
                    EmailCampaign.reply_received_at.is_(None),
                    EmailCampaign.replied_at.isnot(None),
                    EmailCampaign.replied_at < EmailCampaign.sent_at,
                ),
            ),
        )
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )

    weak_thread = (
        base.filter(
            EmailCampaign.replied.is_(True),
            EmailCampaign.reply_text.isnot(None),
            EmailCampaign.thread_id.is_(None),
            EmailCampaign.gmail_thread_id.is_(None),
            EmailCampaign.message_id.is_(None),
        )
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )

    type_seq_mismatch = (
        base.filter(
            or_(
                and_(func.lower(EmailCampaign.email_type) == "initial", EmailCampaign.sequence_number != 1),
                and_(func.lower(EmailCampaign.email_type) == "followup_1", EmailCampaign.sequence_number != 2),
                and_(func.lower(EmailCampaign.email_type) == "followup_2", EmailCampaign.sequence_number != 3),
                and_(func.lower(EmailCampaign.email_type) == "followup_3", EmailCampaign.sequence_number != 4),
            )
        )
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )

    orphan_campaign_student = (
        db.query(func.count(EmailCampaign.id))
        .select_from(EmailCampaign)
        .outerjoin(Student, EmailCampaign.student_id == Student.id)
        .filter(Student.id.is_(None))
        .scalar()
        or 0
    )

    prior_fu2_exists = (
        db.query(literal(1))
        .select_from(e2)
        .filter(
            e2.student_id == EmailCampaign.student_id,
            e2.hr_id == EmailCampaign.hr_id,
            func.lower(e2.email_type) == "followup_2",
            e2.status == "sent",
        )
        .exists()
    )
    fu3_without_fu2 = (
        base.filter(
            func.lower(EmailCampaign.email_type) == "followup_3",
            EmailCampaign.status == "sent",
            ~prior_fu2_exists,
        )
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )

    e1 = aliased(EmailCampaign)
    prior_fu1_for_fu2 = (
        db.query(literal(1))
        .select_from(e1)
        .filter(
            e1.student_id == EmailCampaign.student_id,
            e1.hr_id == EmailCampaign.hr_id,
            func.lower(e1.email_type) == "followup_1",
            e1.status == "sent",
        )
        .exists()
    )
    fu2_without_fu1 = (
        base.filter(
            func.lower(EmailCampaign.email_type) == "followup_2",
            EmailCampaign.status == "sent",
            ~prior_fu1_for_fu2,
        )
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )

    reply_received_missing = (
        base.filter(
            EmailCampaign.replied.is_(True),
            EmailCampaign.reply_text.isnot(None),
            EmailCampaign.reply_received_at.is_(None),
        )
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )

    fu = aliased(EmailCampaign)
    replied_but_followup_queue = (
        base.filter(
            EmailCampaign.sequence_number == 1,
            func.lower(EmailCampaign.email_type) == "initial",
            EmailCampaign.replied.is_(True),
            db.query(literal(1))
            .select_from(fu)
            .filter(
                fu.student_id == EmailCampaign.student_id,
                fu.hr_id == EmailCampaign.hr_id,
                fu.sequence_number > 1,
                fu.status.in_(("pending", "scheduled")),
            )
            .exists(),
        )
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )

    sent_missing_ts = (
        base.filter(EmailCampaign.status == "sent", EmailCampaign.sent_at.is_(None))
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )

    status_replied_missing_body = (
        base.filter(
            func.lower(EmailCampaign.status) == "replied",
            or_(EmailCampaign.reply_text.is_(None), EmailCampaign.replied.is_(False)),
        )
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )

    return {
        "reply_before_sent": int(reply_before_sent),
        "weak_thread_identifiers": int(weak_thread),
        "email_type_sequence_mismatch": int(type_seq_mismatch),
        "orphan_campaign_missing_student": int(orphan_campaign_student),
        "followup_3_sent_without_followup_2": int(fu3_without_fu2),
        "followup_2_sent_without_followup_1": int(fu2_without_fu1),
        "replied_initial_but_followup_still_scheduled": int(replied_but_followup_queue),
        "status_sent_missing_sent_at": int(sent_missing_ts),
        "status_replied_missing_body_or_flag": int(status_replied_missing_body),
        "reply_received_at_null_on_replied": int(reply_received_missing),
    }


def _scheduler_health() -> dict[str, Any]:
    try:
        from app.services import campaign_scheduler as cs

        sch = getattr(cs, "_scheduler", None)
        running = sch is not None and getattr(sch, "running", False)
        return {"scheduler": "running" if running else "stopped", "ok": bool(running)}
    except Exception as e:
        return {"scheduler": "unknown", "ok": False, "error": str(e)[:200]}


def _worst_status(*statuses: str) -> str:
    order = {"green": 0, "yellow": 1, "red": 2}
    rank = max(order.get((s or "").lower(), 0) for s in statuses)
    return "red" if rank >= 2 else "yellow" if rank >= 1 else "green"


def build_data_integrity_snapshot(db: Session, *, include_demo: bool = False) -> dict[str, Any]:
    """
    Compare critical aggregates between Dashboard (/analytics/summary), funnel-shaped
    counts on email_campaigns, and thread/reply invariants.

    Conservative: flags likely inconsistencies; does not repair data.
    """
    from app.routers.analytics import _analytics_summary_impl

    summary = _analytics_summary_impl(include_demo, db)
    base = email_campaigns_scoped_to_hr(db, include_demo=include_demo)

    total_replied_campaigns = (
        base.filter(EmailCampaign.replied.is_(True)).with_entities(func.count(EmailCampaign.id)).scalar() or 0
    )
    replied_with_body = (
        base.filter(EmailCampaign.replied.is_(True), EmailCampaign.reply_text.isnot(None))
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )
    reply_text_not_replied = (
        base.filter(EmailCampaign.reply_text.isnot(None), EmailCampaign.replied.is_(False))
        .with_entities(func.count(EmailCampaign.id))
        .scalar()
        or 0
    )

    stage_rows = []
    for label, et in (
        ("initial", "initial"),
        ("followup_1", "followup_1"),
        ("followup_2", "followup_2"),
        ("followup_3", "followup_3"),
    ):
        n = (
            base.filter(
                func.lower(EmailCampaign.email_type) == et,
                EmailCampaign.replied.is_(True),
                EmailCampaign.reply_text.isnot(None),
            )
            .with_entities(func.count(EmailCampaign.id))
            .scalar()
            or 0
        )
        stage_rows.append({"stage": label, "replied_with_body": int(n)})

    stage_sum = sum(int(r["replied_with_body"]) for r in stage_rows)

    def _funnel_sent(et: str) -> int:
        return int(
            base.filter(func.lower(EmailCampaign.email_type) == et, EmailCampaign.status == "sent")
            .with_entities(func.count(EmailCampaign.id))
            .scalar()
            or 0
        )

    funnel_initial_sent = _funnel_sent("initial")
    funnel_fu1_sent = _funnel_sent("followup_1")
    funnel_fu2_sent = _funnel_sent("followup_2")
    funnel_fu3_sent = _funnel_sent("followup_3")

    thread = reply_thread_consistency_check(db, base=base)

    orphan_assignments_student = (
        db.query(func.count(Assignment.id))
        .outerjoin(Student, Assignment.student_id == Student.id)
        .filter(Assignment.student_id.isnot(None), Student.id.is_(None))
        .scalar()
        or 0
    )
    orphan_assignments_hr = (
        db.query(func.count(Assignment.id))
        .outerjoin(HRContact, Assignment.hr_id == HRContact.id)
        .filter(Assignment.hr_id.isnot(None), HRContact.id.is_(None))
        .scalar()
        or 0
    )

    sch = _scheduler_health()

    checks: list[dict[str, Any]] = []

    def add_check(name: str, ok: bool, detail: str, meta: dict[str, Any] | None = None, *, severity: str | None = None) -> None:
        row: dict[str, Any] = {"name": name, "ok": ok, "detail": detail, "meta": meta or {}}
        if severity:
            row["severity"] = severity
        checks.append(row)

    add_check(
        "replies_total_vs_replied_flag",
        int(summary.get("total_replies", 0)) == int(total_replied_campaigns),
        "analytics.total_replies should equal COUNT(email_campaigns.replied=TRUE) under the same HR/demo scope.",
        {"analytics_total_replies": int(summary.get("total_replies", 0)), "db_replied_rows": int(total_replied_campaigns)},
    )
    add_check(
        "replies_have_inbound_body",
        int(replied_with_body) == int(total_replied_campaigns),
        "Replied rows should have reply_text populated for operator review (legacy gaps flagged).",
        {"replied_rows": int(total_replied_campaigns), "replied_with_reply_text": int(replied_with_body)},
    )
    add_check(
        "inbound_text_without_replied_flag",
        int(reply_text_not_replied) == 0,
        "Inbound reply_text without replied=TRUE usually indicates bounces/soft signals; expect 0 on a clean pilot DB.",
        {"rows": int(reply_text_not_replied)},
    )
    add_check(
        "reply_stage_buckets_sum",
        int(stage_sum) <= int(total_replied_campaigns),
        "Sum of stage-level replied rows should not exceed total replied rows.",
        {"stage_sum": int(stage_sum), "total_replied_rows": int(total_replied_campaigns)},
    )

    add_check(
        "analytics_stage_vs_db_recount_initial",
        int(summary.get("replies_initial", 0)) == stage_rows[0]["replied_with_body"],
        "Dashboard replies_initial must match a direct recount on email_campaigns (same scope).",
        {"analytics": int(summary.get("replies_initial", 0)), "db": stage_rows[0]["replied_with_body"]},
    )
    add_check(
        "analytics_stage_vs_db_recount_fu1",
        int(summary.get("replies_followup1", 0)) == stage_rows[1]["replied_with_body"],
        "Dashboard replies_followup1 must match DB recount.",
        {"analytics": int(summary.get("replies_followup1", 0)), "db": stage_rows[1]["replied_with_body"]},
    )
    add_check(
        "analytics_stage_vs_db_recount_fu2",
        int(summary.get("replies_followup2", 0)) == stage_rows[2]["replied_with_body"],
        "Dashboard replies_followup2 must match DB recount.",
        {"analytics": int(summary.get("replies_followup2", 0)), "db": stage_rows[2]["replied_with_body"]},
    )
    add_check(
        "analytics_stage_vs_db_recount_fu3",
        int(summary.get("replies_followup3", 0)) == stage_rows[3]["replied_with_body"],
        "Dashboard replies_followup3 must match DB recount.",
        {"analytics": int(summary.get("replies_followup3", 0)), "db": stage_rows[3]["replied_with_body"]},
    )

    add_check(
        "reply_thread_reply_before_sent",
        thread["reply_before_sent"] == 0,
        "Inbound reply timestamp must not precede outbound sent_at on the matched campaign row.",
        {"count": thread["reply_before_sent"]},
    )
    add_check(
        "reply_thread_weak_identifiers",
        True,
        "Human replies should carry at least one of thread_id, gmail_thread_id, or message_id when possible.",
        {"count": thread["weak_thread_identifiers"]},
        severity="yellow" if thread["weak_thread_identifiers"] else None,
    )
    add_check(
        "reply_thread_type_sequence_alignment",
        thread["email_type_sequence_mismatch"] == 0,
        "email_type must align with sequence_number (initial=1, FU1=2, …).",
        {"count": thread["email_type_sequence_mismatch"]},
    )
    add_check(
        "reply_thread_orphan_campaign_student",
        thread["orphan_campaign_missing_student"] == 0,
        "email_campaigns.student_id should always resolve to a student row.",
        {"count": thread["orphan_campaign_missing_student"]},
    )
    add_check(
        "impossible_followup_3_without_followup_2",
        thread["followup_3_sent_without_followup_2"] == 0,
        "followup_3 sent requires followup_2 sent for the same student–HR pair.",
        {"count": thread["followup_3_sent_without_followup_2"]},
    )
    add_check(
        "impossible_followup_2_without_followup_1",
        thread["followup_2_sent_without_followup_1"] == 0,
        "followup_2 sent requires followup_1 sent for the same student–HR pair.",
        {"count": thread["followup_2_sent_without_followup_1"]},
    )
    add_check(
        "impossible_replied_initial_but_followup_scheduled",
        thread["replied_initial_but_followup_still_scheduled"] == 0,
        "If the initial row is replied, later sequence rows should not remain pending/scheduled.",
        {"count": thread["replied_initial_but_followup_still_scheduled"]},
    )
    add_check(
        "impossible_status_sent_without_sent_at",
        thread["status_sent_missing_sent_at"] == 0,
        "Rows with status=sent must have sent_at populated.",
        {"count": thread["status_sent_missing_sent_at"]},
    )
    add_check(
        "impossible_status_replied_incomplete",
        thread["status_replied_missing_body_or_flag"] == 0,
        "Rows with status=replied should have replied=TRUE and reply_text.",
        {"count": thread["status_replied_missing_body_or_flag"]},
    )
    add_check(
        "reply_received_at_populated",
        thread["reply_received_at_null_on_replied"] == 0,
        "Replied rows with inbound body should have reply_received_at (run migration / backfill).",
        {"count": thread["reply_received_at_null_on_replied"]},
        severity="yellow" if thread["reply_received_at_null_on_replied"] else None,
    )

    add_check(
        "orphan_assignments_missing_student",
        int(orphan_assignments_student) == 0,
        "assignments.student_id must reference an existing student.",
        {"count": int(orphan_assignments_student)},
    )
    add_check(
        "orphan_assignments_missing_hr",
        int(orphan_assignments_hr) == 0,
        "assignments.hr_id must reference an existing hr_contacts row.",
        {"count": int(orphan_assignments_hr)},
    )

    emails_sent_db = (
        base.filter(EmailCampaign.status == "sent").with_entities(func.count(EmailCampaign.id)).scalar() or 0
    )
    add_check(
        "funnel_emails_sent_vs_analytics",
        int(summary.get("emails_sent", 0)) == int(emails_sent_db),
        "analytics.emails_sent must match COUNT(email_campaigns.status='sent') under the same scope.",
        {"analytics": int(summary.get("emails_sent", 0)), "db": int(emails_sent_db)},
    )
    add_check(
        "scheduler_process_running",
        True,
        "Background campaign scheduler heartbeat (yellow when stopped in this process).",
        sch,
        severity="yellow" if not sch.get("ok") else None,
    )

    def _domain_status(failed: int, warned: int) -> str:
        if failed:
            return "red"
        if warned:
            return "yellow"
        return "green"

    def _check_bucket(names: list[str]) -> tuple[int, int]:
        failed = 0
        warned = 0
        name_set = set(names)
        for c in checks:
            if c["name"] not in name_set:
                continue
            if not c["ok"]:
                failed += 1
            if c.get("severity") == "yellow":
                warned += 1
        return failed, warned

    reply_names = [
        "replies_total_vs_replied_flag",
        "replies_have_inbound_body",
        "inbound_text_without_replied_flag",
        "reply_stage_buckets_sum",
        "reply_thread_reply_before_sent",
        "reply_thread_weak_identifiers",
        "reply_thread_type_sequence_alignment",
        "reply_thread_orphan_campaign_student",
        "reply_received_at_populated",
    ]
    funnel_names = [
        "analytics_stage_vs_db_recount_initial",
        "analytics_stage_vs_db_recount_fu1",
        "analytics_stage_vs_db_recount_fu2",
        "analytics_stage_vs_db_recount_fu3",
        "funnel_emails_sent_vs_analytics",
    ]
    lifecycle_names = [
        "impossible_followup_3_without_followup_2",
        "impossible_followup_2_without_followup_1",
        "impossible_replied_initial_but_followup_scheduled",
        "impossible_status_sent_without_sent_at",
        "impossible_status_replied_incomplete",
    ]
    orphan_names = ["orphan_assignments_missing_student", "orphan_assignments_missing_hr"]

    rf, rw = _check_bucket(reply_names)
    ff, fw = _check_bucket(funnel_names)
    lf, lw = _check_bucket(lifecycle_names)
    of, ow = _check_bucket(orphan_names)
    sf, sw = _check_bucket(["scheduler_process_running"])

    api_failed = 0
    api_warned = 0

    preflight = {
        "system_consistency": _worst_status(
            _domain_status(rf, rw),
            _domain_status(ff, fw),
            _domain_status(lf, lw),
            _domain_status(of, ow),
            _domain_status(sf, sw),
            _domain_status(api_failed, api_warned),
        ),
        "domains": [
            {"id": "reply_integrity", "label": "Reply integrity", "status": _domain_status(rf, rw)},
            {"id": "funnel_integrity", "label": "Funnel vs analytics", "status": _domain_status(ff, fw)},
            {"id": "lifecycle", "label": "Impossible lifecycle", "status": _domain_status(lf, lw)},
            {"id": "orphan_scan", "label": "Orphan assignments", "status": _domain_status(of, ow)},
            {"id": "scheduler", "label": "Scheduler state", "status": _domain_status(sf, sw)},
            {
                "id": "api_contract",
                "label": "API contract health",
                "status": "green",
                "detail": "Reserved: wire contract tests / OpenAPI drift when available.",
            },
        ],
        "reply_thread": thread,
        "funnel_sent_counts": {
            "initial": funnel_initial_sent,
            "followup_1": funnel_fu1_sent,
            "followup_2": funnel_fu2_sent,
            "followup_3": funnel_fu3_sent,
        },
        "scheduler": sch,
    }

    open_failures = sum(1 for c in checks if not c["ok"])
    open_warns = sum(1 for c in checks if c["ok"] and c.get("severity") == "yellow")
    score = max(0, 100 - open_failures * 15 - open_warns * 5)

    return {
        "include_demo": include_demo,
        "summary_subset": {
            "total_replies": int(summary.get("total_replies", 0)),
            "emails_sent": int(summary.get("emails_sent", 0)),
            "replies_initial": int(summary.get("replies_initial", 0)),
            "replies_followup1": int(summary.get("replies_followup1", 0)),
            "replies_followup2": int(summary.get("replies_followup2", 0)),
            "replies_followup3": int(summary.get("replies_followup3", 0)),
        },
        "raw_counts": {
            "replied_campaign_rows": int(total_replied_campaigns),
            "replied_with_reply_text": int(replied_with_body),
            "reply_text_without_replied": int(reply_text_not_replied),
            "stage_breakdown": stage_rows,
            "stage_replied_sum": int(stage_sum),
        },
        "checks": checks,
        "consistency_score": int(score),
        "preflight": preflight,
    }
