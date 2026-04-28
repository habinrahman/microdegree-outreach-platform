"""Focused smoke tests for outbound safety controls.

Runs against DATABASE_URL / ALEMBIC_DATABASE_URL and uses synthetic fixture-tagged rows.
Does NOT perform real SMTP sends (monkeypatches worker send function).
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from threading import Thread

from dotenv import load_dotenv

from app.database.config import SessionLocal
from app.models import EmailCampaign, HRContact, Student
from app.models.outbound_suppression import OutboundSuppression
from app.services.outbound_suppression_store import upsert_suppression
from app.services.runtime_settings_store import set_outbound_enabled, get_outbound_enabled
from app.services.campaign_scheduler import run_campaign_job


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _mk_student(db, *, sid: uuid.UUID) -> Student:
    st = Student(
        id=sid,
        name="smoke student",
        gmail_address=f"student.smoketest+{uuid.uuid4().hex[:8]}@smokeqa.internal",
        app_password="x",  # scheduler filter requires non-null
        resume_path="C:\\fixture\\resume.pdf",  # non-empty
        status="active",
        email_health_status="healthy",
        is_demo=True,
        is_fixture_test_data=False,
    )
    db.add(st)
    db.commit()
    return st


def _mk_hr(db, *, hid: uuid.UUID, email: str) -> HRContact:
    hr = HRContact(
        id=hid,
        name="smoke hr",
        company="smoke co",
        email=email,
        status="active",
        is_valid=True,
        is_demo=True,
        is_fixture_test_data=False,
    )
    db.add(hr)
    db.commit()
    return hr


def _mk_campaign(db, *, cid: uuid.UUID, sid: uuid.UUID, hid: uuid.UUID, status: str = "scheduled") -> EmailCampaign:
    c = EmailCampaign(
        id=cid,
        student_id=sid,
        hr_id=hid,
        sequence_number=1,
        email_type="initial",
        scheduled_at=_utc_now_naive() - timedelta(minutes=1),
        status=status,
        subject="fixture subject",
        body="fixture body",
        replied=False,
    )
    db.add(c)
    db.commit()
    return c


def _cleanup(db, *, cid: uuid.UUID, sid: uuid.UUID, hid: uuid.UUID, hr_email: str) -> None:
    # Order matters because of FKs. Be defensive: worker/scheduler may have touched additional
    # rows for the same pair in future evolutions.
    try:
        db.rollback()
    except Exception:
        pass

    db.query(EmailCampaign).filter(
        (EmailCampaign.id == cid)
        | (EmailCampaign.student_id == sid)
        | (EmailCampaign.hr_id == hid)
    ).delete(synchronize_session=False)
    try:
        db.query(OutboundSuppression).filter(OutboundSuppression.email_lower == hr_email.strip().lower()).delete(
            synchronize_session=False
        )
    except Exception:
        # Suppression table may not exist yet (bootstrap creates on demand); ignore cleanup in that case.
        try:
            db.rollback()
        except Exception:
            pass
    # Retry deletes with rollback if FK constraints complain.
    for _ in range(2):
        try:
            db.query(HRContact).filter(HRContact.id == hid).delete(synchronize_session=False)
            db.query(Student).filter(Student.id == sid).delete(synchronize_session=False)
            db.commit()
            break
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass


def test_kill_switch() -> dict:
    db = SessionLocal()
    sid = uuid.uuid4()
    hid = uuid.uuid4()
    cid = uuid.uuid4()
    hr_email = f"hr.smoketest+kill.{uuid.uuid4().hex[:8]}@smokeqa.internal"
    try:
        _mk_student(db, sid=sid)
        _mk_hr(db, hid=hid, email=hr_email)
        _mk_campaign(db, cid=cid, sid=sid, hid=hid, status="scheduled")

        set_outbound_enabled(db, False)
        assert get_outbound_enabled(db) is False

        # Scheduler should refuse to pick up.
        res = run_campaign_job(
            ignore_window=True,
            ignore_scheduled_time=True,
            skip_delay=True,
            limit=5,
            student_id=str(sid),
            ignore_deliverability_pause=True,
        )
        c = db.query(EmailCampaign).filter(EmailCampaign.id == cid).first()
        return {
            "scheduler_note": res.get("note"),
            "scheduler_sent": int(res.get("sent") or 0),
            "campaign_status_after_scheduler": getattr(c, "status", None),
        }
    finally:
        try:
            set_outbound_enabled(db, True)
        except Exception:
            pass
        _cleanup(db, cid=cid, sid=sid, hid=hid, hr_email=hr_email)
        db.close()


def test_kill_switch_worker_block() -> dict:
    from app.workers import email_worker

    db = SessionLocal()
    sid = uuid.uuid4()
    hid = uuid.uuid4()
    cid = uuid.uuid4()
    hr_email = f"hr.smoketest+workerblock.{uuid.uuid4().hex[:8]}@smokeqa.internal"
    try:
        _mk_student(db, sid=sid)
        _mk_hr(db, hid=hid, email=hr_email)
        _mk_campaign(db, cid=cid, sid=sid, hid=hid, status="scheduled")

        # Ensure worker would otherwise "send": patch send_with_fallback to explode if reached.
        def _boom(**_kwargs):
            raise RuntimeError("send should not be reached")

        old_send = email_worker.send_with_fallback
        email_worker.send_with_fallback = _boom
        try:
            set_outbound_enabled(db, False)
            email_worker.process_email_campaign(str(cid))
        finally:
            email_worker.send_with_fallback = old_send

        c = db.query(EmailCampaign).filter(EmailCampaign.id == cid).first()
        return {
            "campaign_status": getattr(c, "status", None),
            "campaign_error": getattr(c, "error", None),
            "processing_lock_cleared": bool(getattr(c, "processing_lock_acquired_at", None) is None),
        }
    finally:
        try:
            set_outbound_enabled(db, True)
        except Exception:
            pass
        _cleanup(db, cid=cid, sid=sid, hid=hid, hr_email=hr_email)
        db.close()


def test_runtime_settings_fail_closed() -> dict:
    # Simulate runtime_settings read failure by monkeypatching internal accessor.
    from app.services import runtime_settings_store as rs

    db = SessionLocal()
    try:
        old = rs._get_raw

        def _raise(*_a, **_k):
            raise RuntimeError("synthetic read failure")

        rs._get_raw = _raise
        try:
            v = rs.get_outbound_enabled(db)
        finally:
            rs._get_raw = old
        return {"outbound_enabled_on_read_failure": v}
    finally:
        db.close()


def test_manual_suppression_blocks_worker() -> dict:
    from app.workers import email_worker

    db = SessionLocal()
    sid = uuid.uuid4()
    hid = uuid.uuid4()
    cid = uuid.uuid4()
    hr_email = f"hr.smoketest+supp.{uuid.uuid4().hex[:8]}@smokeqa.internal"
    try:
        _mk_student(db, sid=sid)
        _mk_hr(db, hid=hid, email=hr_email)
        _mk_campaign(db, cid=cid, sid=sid, hid=hid, status="scheduled")

        upsert_suppression(db, email=hr_email, reason="manual_test", source="manual", active=True)

        # Patch send so we'd notice if it reached actual send.
        def _boom(**_kwargs):
            raise RuntimeError("send should not be reached")

        old_send = email_worker.send_with_fallback
        email_worker.send_with_fallback = _boom
        try:
            email_worker.process_email_campaign(str(cid))
        finally:
            email_worker.send_with_fallback = old_send

        c = db.query(EmailCampaign).filter(EmailCampaign.id == cid).first()
        return {
            "campaign_status": getattr(c, "status", None),
            "campaign_error": getattr(c, "error", None),
            "campaign_suppression_reason": getattr(c, "suppression_reason", None),
        }
    finally:
        _cleanup(db, cid=cid, sid=sid, hid=hid, hr_email=hr_email)
        db.close()


def test_bounce_auto_suppression() -> dict:
    from app.workers import email_worker
    from smtplib import SMTPException

    db = SessionLocal()
    sid = uuid.uuid4()
    hid = uuid.uuid4()
    cid = uuid.uuid4()
    hr_email = f"hr.smoketest+bounce.{uuid.uuid4().hex[:8]}@smokeqa.internal"
    try:
        _mk_student(db, sid=sid)
        _mk_hr(db, hid=hid, email=hr_email)
        _mk_campaign(db, cid=cid, sid=sid, hid=hid, status="scheduled")

        def _raise_bounce(**_kwargs):
            raise SMTPException("550 5.1.1 user unknown (synthetic bounce)")

        old_send = email_worker.send_with_fallback
        email_worker.send_with_fallback = _raise_bounce
        try:
            email_worker.process_email_campaign(str(cid))
        finally:
            email_worker.send_with_fallback = old_send

        sup = db.query(OutboundSuppression).filter(OutboundSuppression.email_lower == hr_email.lower()).first()
        c = db.query(EmailCampaign).filter(EmailCampaign.id == cid).first()
        return {
            "campaign_status": getattr(c, "status", None),
            "campaign_reply_status": getattr(c, "reply_status", None),
            "campaign_delivery_status": getattr(c, "delivery_status", None),
            "suppression_created": bool(sup is not None),
            "suppression_source": getattr(sup, "source", None) if sup else None,
            "suppression_reason": getattr(sup, "reason", None) if sup else None,
        }
    finally:
        _cleanup(db, cid=cid, sid=sid, hid=hid, hr_email=hr_email)
        db.close()


def test_advisory_lock_idempotency() -> dict:
    from app.workers import email_worker
    from smtplib import SMTPException

    db = SessionLocal()
    sid = uuid.uuid4()
    hid = uuid.uuid4()
    cid = uuid.uuid4()
    hr_email = f"hr.smoketest+lock.{uuid.uuid4().hex[:8]}@smokeqa.internal"
    try:
        _mk_student(db, sid=sid)
        _mk_hr(db, hid=hid, email=hr_email)
        _mk_campaign(db, cid=cid, sid=sid, hid=hid, status="scheduled")

        # Hold the lock in the first worker by sleeping in send.
        def _slow_fail(**_kwargs):
            time.sleep(2.0)
            raise SMTPException("550 synthetic slow bounce")

        old_send = email_worker.send_with_fallback
        email_worker.send_with_fallback = _slow_fail

        timings: dict[str, float] = {}

        def run1():
            timings["t1_start"] = time.time()
            email_worker.process_email_campaign(str(cid))
            timings["t1_end"] = time.time()

        def run2():
            # start slightly after run1 to contend on advisory lock
            time.sleep(0.2)
            timings["t2_start"] = time.time()
            email_worker.process_email_campaign(str(cid))
            timings["t2_end"] = time.time()

        try:
            th1 = Thread(target=run1, daemon=True)
            th2 = Thread(target=run2, daemon=True)
            th1.start()
            th2.start()
            th1.join(10)
            th2.join(10)
        finally:
            email_worker.send_with_fallback = old_send

        # After run1 completes, a third run should be able to acquire lock again (no deadlock).
        def _fast_fail(**_kwargs):
            raise SMTPException("550 synthetic bounce again")

        old_send2 = email_worker.send_with_fallback
        email_worker.send_with_fallback = _fast_fail
        try:
            t3_start = time.time()
            email_worker.process_email_campaign(str(cid))
            t3_end = time.time()
        finally:
            email_worker.send_with_fallback = old_send2

        c = db.query(EmailCampaign).filter(EmailCampaign.id == cid).first()
        return {
            "t1_duration_s": round(timings.get("t1_end", 0) - timings.get("t1_start", 0), 3),
            "t2_duration_s": round(timings.get("t2_end", 0) - timings.get("t2_start", 0), 3),
            "t3_duration_s": round(t3_end - t3_start, 3),
            "t2_exited_quickly": bool((timings.get("t2_end", 0) - timings.get("t2_start", 0)) < 1.0),
            "campaign_status_final": getattr(c, "status", None),
        }
    finally:
        _cleanup(db, cid=cid, sid=sid, hid=hid, hr_email=hr_email)
        db.close()


def main() -> None:
    load_dotenv()
    # Run against direct DB when supplied (recommended for ops).
    if not ((os.getenv("ALEMBIC_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()):
        raise SystemExit("Set DATABASE_URL or ALEMBIC_DATABASE_URL")

    out: dict[str, dict] = {}
    out["kill_switch_scheduler"] = test_kill_switch()
    out["kill_switch_worker"] = test_kill_switch_worker_block()
    out["kill_switch_fail_closed"] = test_runtime_settings_fail_closed()
    out["suppression_manual"] = test_manual_suppression_blocks_worker()
    out["suppression_bounce_auto"] = test_bounce_auto_suppression()
    out["advisory_lock"] = test_advisory_lock_idempotency()

    for k, v in out.items():
        print(f"\n== {k} ==")
        for kk, vv in v.items():
            print(f"{kk}: {vv}")


if __name__ == "__main__":
    main()

