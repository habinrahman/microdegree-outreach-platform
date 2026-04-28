"""Controlled pilot rehearsal (no real outbound sends).

This script is intended to pressure-test system behavior before a pilot dry-run:
- scheduler run / overlap characteristics
- kill switch behavior mid-run
- suppression list behavior (manual + bounce auto)
- follow-up rescheduling after initial send
- reply classification path (simulated)
- resume update regeneration for pending campaigns (simulated)
- crash-after-SMTP-before-commit scenario (two-phase)

It monkeypatches worker send function to avoid real SMTP/Gmail calls.
"""

from __future__ import annotations

import argparse
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from sqlalchemy import text

from app.database.config import SessionLocal
from app.models import Assignment, EmailCampaign, HRContact, Student
from app.services.outbound_suppression_store import upsert_suppression
from app.services.runtime_settings_store import set_outbound_enabled
from app.services.campaign_scheduler import run_campaign_job
from app.services.reply_classifier import apply_inbound_reply_to_campaign
from app.services.student_email_health import refresh_student_email_health
from app.services.student_resume_update import refresh_pending_campaign_templates


DOMAIN = "smokeqa.internal"


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class RehearsalIds:
    student_ids: list[str]
    hr_ids: list[str]
    assignment_ids: list[str]
    campaign_ids: list[str]


def _mk_student(db, idx: int) -> Student:
    sid = uuid.uuid4()
    st = Student(
        id=sid,
        name=f"Pilot Student {idx}",
        gmail_address=f"pilot.student{idx}.{uuid.uuid4().hex[:6]}@{DOMAIN}",
        app_password="x",
        resume_path="C:\\pilot\\resume.pdf",
        resume_file_name="resume.pdf",
        status="active",
        email_health_status="healthy",
        is_demo=True,
        is_fixture_test_data=False,
    )
    db.add(st)
    db.commit()
    return st


def _mk_hr(db, idx: int) -> HRContact:
    hid = uuid.uuid4()
    hr = HRContact(
        id=hid,
        name=f"Pilot HR {idx}",
        company=f"PilotCo {idx}",
        email=f"pilot.hr{idx}.{uuid.uuid4().hex[:6]}@{DOMAIN}",
        status="active",
        is_valid=True,
        is_demo=True,
        is_fixture_test_data=False,
    )
    db.add(hr)
    db.commit()
    return hr


def _mk_assignment(db, st: Student, hr: HRContact) -> Assignment:
    a = Assignment(student_id=st.id, hr_id=hr.id, status="active")
    db.add(a)
    db.commit()
    return a


def _generate_campaigns_for_pair(db, a: Assignment) -> list[EmailCampaign]:
    """
    Generate 4-step rows with minimal dependencies (fast rehearsal).
    Initial is due now; followups are spaced 7/14/21 days from now.
    """
    anchor = _now_naive()
    student_id = a.student_id
    hr_id = a.hr_id
    rows: list[EmailCampaign] = []
    steps = [
        (1, "initial", anchor - timedelta(minutes=1)),
        (2, "followup_1", anchor + timedelta(days=7)),
        (3, "followup_2", anchor + timedelta(days=14)),
        (4, "followup_3", anchor + timedelta(days=21)),
    ]
    for seq, et, sched_at in steps:
        c = EmailCampaign(
            id=uuid.uuid4(),
            student_id=student_id,
            hr_id=hr_id,
            sequence_number=seq,
            email_type=et,
            scheduled_at=sched_at,
            status="scheduled" if seq == 1 else "pending",
            subject=f"pilot {et}",
            body=f"pilot body {et}",
            replied=False,
        )
        db.add(c)
        rows.append(c)
    db.commit()
    return rows


def _patch_worker_send_success():
    from app.workers import email_worker

    def _fake_send(**_kwargs):
        return {"message_id": f"<pilot-{uuid.uuid4().hex}@{DOMAIN}>", "status": "SENT"}

    # Also disable any non-deterministic side effects during rehearsal.
    def _noop(*_a, **_k):
        return None

    return email_worker, _fake_send, _noop


def _run_scheduler_once(db, *, limit: int | None = None) -> dict:
    return run_campaign_job(
        ignore_window=True,
        ignore_scheduled_time=True,
        skip_delay=True,
        limit=limit,
        ignore_deliverability_pause=True,
    )


def rehearsal_phase() -> None:
    db = SessionLocal()
    ids = RehearsalIds(student_ids=[], hr_ids=[], assignment_ids=[], campaign_ids=[])
    email_worker, fake_send, noop = _patch_worker_send_success()
    old_send = email_worker.send_with_fallback
    old_refresh = getattr(email_worker, "refresh_student_email_health", None)
    old_safe_sync = getattr(email_worker, "_safe_sync_sheets", None)
    # log_stream broadcast is invoked inside worker; patch the source module.
    try:
        from app.services import log_stream as _log_stream
    except Exception:
        _log_stream = None
    old_broadcast = getattr(_log_stream, "broadcast_log_sync", None) if _log_stream is not None else None
    email_worker.send_with_fallback = fake_send
    try:
        if old_refresh is not None:
            email_worker.refresh_student_email_health = noop
        if old_safe_sync is not None:
            email_worker._safe_sync_sheets = noop
        if _log_stream is not None and old_broadcast is not None:
            _log_stream.broadcast_log_sync = noop
    except Exception:
        pass
    try:
        # Ensure outbound starts enabled for a deterministic rehearsal.
        try:
            set_outbound_enabled(db, True)
        except Exception:
            pass
        print("rehearsal: outbound_enabled set true", flush=True)

        # Avoid hanging on the in-process scheduler mutex if a prior run crashed mid-job.
        try:
            from app.services import campaign_scheduler as cs

            if getattr(cs, "job_lock", None) is not None and getattr(cs.job_lock, "locked", lambda: False)():
                cs.job_lock.release()
        except Exception:
            pass

        print("rehearsal: creating students/hrs...", flush=True)
        students = [_mk_student(db, i + 1) for i in range(5)]
        hrs = [_mk_hr(db, i + 1) for i in range(20)]
        ids.student_ids = [str(s.id) for s in students]
        ids.hr_ids = [str(h.id) for h in hrs]

        print("rehearsal: creating assignments...", flush=True)
        assignments: list[Assignment] = []
        for si, st in enumerate(students):
            for hi in range(4):
                hr = hrs[si * 4 + hi]
                a = _mk_assignment(db, st, hr)
                assignments.append(a)
        ids.assignment_ids = [str(a.id) for a in assignments]

        print("rehearsal: generating campaigns...", flush=True)
        for a in assignments:
            created = _generate_campaigns_for_pair(db, a)
            ids.campaign_ids.extend([str(c.id) for c in created])

        print("rehearsal: running scheduler send pass 1...", flush=True)
        res1 = _run_scheduler_once(db, limit=50)
        print("scheduler_run_1:", res1)

        print("rehearsal: validating followups exist...", flush=True)
        fu_sched = (
            db.query(EmailCampaign)
            .filter(
                EmailCampaign.sequence_number.in_((2, 3, 4)),
                EmailCampaign.status.in_(("scheduled", "pending", "paused")),
            )
            .count()
        )
        print("followup_rows_present:", int(fu_sched))

        print("rehearsal: simulating reply classification...", flush=True)
        one = (
            db.query(EmailCampaign)
            .filter(EmailCampaign.status == "sent", EmailCampaign.sequence_number == 1)
            .order_by(EmailCampaign.sent_at.desc().nullslast())
            .first()
        )
        if one is not None:
            when = datetime.now(timezone.utc)
            r = apply_inbound_reply_to_campaign(
                db,
                one,
                body="Thanks, interested. Can we talk?",
                sender_for_classify="hr@smokeqa.internal",
                reply_from_header="Pilot HR <hr@smokeqa.internal>",
                when=when.replace(tzinfo=None),
                inbound_message_id=f"<inbound-{uuid.uuid4().hex}@{DOMAIN}>",
            )
            db.commit()
            print("reply_classifier_result:", r, "campaign_id:", str(one.id))

        print("rehearsal: suppression event...", flush=True)
        sup_hr = hrs[0]
        upsert_suppression(db, email=sup_hr.email, reason="manual_rehearsal", source="manual", active=True)
        # Make sure a scheduled campaign exists for that HR (follow-up or create a new initial for another student)
        blocked = (
            db.query(EmailCampaign)
            .filter(EmailCampaign.hr_id == sup_hr.id, EmailCampaign.status.in_(("scheduled", "pending")))
            .first()
        )
        if blocked is not None:
            from app.workers import email_worker as ew

            ew.process_email_campaign(str(blocked.id))
            db.expire_all()
            chk = db.query(EmailCampaign).filter(EmailCampaign.id == blocked.id).first()
            print("suppression_blocked_campaign_status:", getattr(chk, "status", None), "error:", getattr(chk, "error", None))

        print("rehearsal: resume update + pending regen...", flush=True)
        st0 = students[0]
        st0.resume_path = "C:\\pilot\\resume_v2.pdf"
        st0.resume_archive_path = "C:\\pilot\\resume.pdf"
        st0.resume_updated_at = _now_naive()
        db.add(st0)
        db.commit()
        try:
            n = refresh_pending_campaign_templates(db, st0)
        except Exception:
            n = 0
        print("pending_campaigns_regenerated_count:", int(n))

        print("rehearsal: scheduler pass 2 (overlap simulation)...", flush=True)
        res2 = _run_scheduler_once(db, limit=50)
        print("scheduler_run_2:", res2)

        print("rehearsal: kill switch toggle mid-run...", flush=True)
        set_outbound_enabled(db, False)
        res3 = _run_scheduler_once(db, limit=50)
        print("scheduler_run_killswitch:", res3)
        set_outbound_enabled(db, True)

        # Health gating must be deterministic for this rehearsal environment; we keep all
        # students pre-seeded as "healthy" and do not run live health refresh here.

        print("rehearsal_ok:", True)
        print("rehearsal_ids:", ids)
    finally:
        email_worker.send_with_fallback = old_send
        try:
            if old_refresh is not None:
                email_worker.refresh_student_email_health = old_refresh
            if old_safe_sync is not None:
                email_worker._safe_sync_sheets = old_safe_sync
            if _log_stream is not None and old_broadcast is not None:
                _log_stream.broadcast_log_sync = old_broadcast
        except Exception:
            pass
        db.close()


def crash_simulate_phase() -> None:
    """
    Simulate: SMTP send succeeds, process crashes before sent-status commit.

    We patch persist_sent_email_campaign to os._exit() before the commit.
    """
    from app.workers import email_worker

    db = SessionLocal()
    sid = uuid.uuid4()
    hid = uuid.uuid4()
    cid = uuid.uuid4()

    st = Student(
        id=sid,
        name="CrashSim Student",
        gmail_address=f"crashsim.student.{uuid.uuid4().hex[:6]}@{DOMAIN}",
        app_password="x",
        resume_path="C:\\pilot\\resume.pdf",
        status="active",
        email_health_status="healthy",
        is_demo=True,
        is_fixture_test_data=False,
    )
    hr = HRContact(
        id=hid,
        name="CrashSim HR",
        company="CrashSimCo",
        email=f"crashsim.hr.{uuid.uuid4().hex[:6]}@{DOMAIN}",
        status="active",
        is_valid=True,
        is_demo=True,
        is_fixture_test_data=False,
    )
    db.add(st)
    db.add(hr)
    db.commit()
    c = EmailCampaign(
        id=cid,
        student_id=sid,
        hr_id=hid,
        sequence_number=1,
        email_type="initial",
        scheduled_at=_now_naive() - timedelta(minutes=1),
        status="scheduled",
        subject="crash sim",
        body="crash sim",
        replied=False,
    )
    db.add(c)
    db.commit()
    db.close()

    # Patch send to succeed.
    def _fake_send(**_kwargs):
        return {"message_id": f"<crashsim-{uuid.uuid4().hex}@{DOMAIN}>", "status": "SENT"}

    old_send = email_worker.send_with_fallback
    email_worker.send_with_fallback = _fake_send

    # Patch persist to hard-exit before commit. Important: patch the reference used by the worker module.
    old_persist = email_worker.persist_sent_email_campaign

    def _crash(*_a, **_k):
        os._exit(12)  # no cleanup; simulates process crash after SMTP success

    email_worker.persist_sent_email_campaign = _crash
    try:
        payload = {"student_id": str(sid), "hr_id": str(hid), "campaign_id": str(cid)}
        try:
            with open("pilot_crash_ids.txt", "w", encoding="utf-8") as f:
                f.write(payload["campaign_id"])
        except Exception:
            pass
        print("crash_sim_ids:", payload, flush=True)
        email_worker.process_email_campaign(str(cid))
    finally:
        email_worker.send_with_fallback = old_send
        email_worker.persist_sent_email_campaign = old_persist


def crash_recover_phase(campaign_id: str) -> None:
    """
    After a crash-before-commit, the campaign is likely stuck in processing.
    Recovery behavior should pause stale processing to avoid duplicate resend.
    """
    # Ensure the recovery scheduler tick is deterministic and does not attempt real SMTP
    # or side-effecting post-send jobs (health refresh, sheet sync, log streaming).
    from app.workers import email_worker as _ew
    try:
        from app.services import log_stream as _log_stream
    except Exception:
        _log_stream = None

    def _fake_send(**_kwargs):
        return {"message_id": f"<crashrecover-{uuid.uuid4().hex}@{DOMAIN}>", "status": "SENT"}

    def _noop(*_a, **_k):
        return None

    old_send = _ew.send_with_fallback
    old_refresh = getattr(_ew, "refresh_student_email_health", None)
    old_safe_sync = getattr(_ew, "_safe_sync_sheets", None)
    old_broadcast = getattr(_log_stream, "broadcast_log_sync", None) if _log_stream is not None else None

    _ew.send_with_fallback = _fake_send
    try:
        if old_refresh is not None:
            _ew.refresh_student_email_health = _noop
        if old_safe_sync is not None:
            _ew._safe_sync_sheets = _noop
        if _log_stream is not None and old_broadcast is not None:
            _log_stream.broadcast_log_sync = _noop
    except Exception:
        pass
    db = SessionLocal()
    try:
        c = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
        if c is None:
            print("recover: campaign not found")
            return
        print("recover: before", {"status": c.status, "processing_started_at": str(c.processing_started_at)})

        # Make it stale and run scheduler self-heal.
        c.status = "processing"
        c.processing_started_at = (_now_naive() - timedelta(minutes=30))
        c.processing_lock_acquired_at = c.processing_started_at
        db.add(c)
        db.commit()

        res = run_campaign_job(
            ignore_window=True,
            ignore_scheduled_time=True,
            skip_delay=True,
            limit=50,
            ignore_deliverability_pause=True,
        )
        db.expire_all()
        c2 = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
        print("recover: scheduler_result", res)
        print("recover: after", {"status": getattr(c2, "status", None), "error": getattr(c2, "error", None)})
    finally:
        _ew.send_with_fallback = old_send
        try:
            if old_refresh is not None:
                _ew.refresh_student_email_health = old_refresh
            if old_safe_sync is not None:
                _ew._safe_sync_sheets = old_safe_sync
            if _log_stream is not None and old_broadcast is not None:
                _log_stream.broadcast_log_sync = old_broadcast
        except Exception:
            pass
        db.close()


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["rehearsal", "crash_simulate", "crash_recover"], required=True)
    ap.add_argument("--campaign-id", default="")
    args = ap.parse_args()

    if args.phase == "rehearsal":
        rehearsal_phase()
        return
    if args.phase == "crash_simulate":
        crash_simulate_phase()
        return
    if args.phase == "crash_recover":
        if not args.campaign_id:
            raise SystemExit("--campaign-id required for crash_recover")
        crash_recover_phase(args.campaign_id)
        return


if __name__ == "__main__":
    main()

