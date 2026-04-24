"""Structural integrity checks (orphan detection)."""
from sqlalchemy import text

from app.database.config import SessionLocal, engine
from app.services.db_integrity_checks import run_corruption_integrity_checks


def test_integrity_ok_on_empty_db():
    db = SessionLocal()
    try:
        rep = run_corruption_integrity_checks(db)
        assert rep["integrity_ok"] is True
        assert all(c["ok"] for c in rep["checks"])
    finally:
        db.close()


def test_integrity_detects_orphan_assignment_sqlite():
    if ":memory:" not in str(engine.url):
        return
    fake_s = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    fake_h = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    aid = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            text(
                "INSERT INTO assignments (id, student_id, hr_id, status) "
                "VALUES (:aid, :sid, :hid, 'active')"
            ),
            {"aid": aid, "sid": fake_s, "hid": fake_h},
        )
        conn.execute(text("PRAGMA foreign_keys=ON"))
    db = SessionLocal()
    try:
        rep = run_corruption_integrity_checks(db)
        assert rep["integrity_ok"] is False
        names = {c["name"]: c["count"] for c in rep["checks"]}
        assert names["orphan_assignments_missing_student"] >= 1
        assert names["orphan_assignments_missing_hr"] >= 1
    finally:
        db.close()
