"""Regression: runtime_settings missing / empty / override (schema drift + fail-open)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from fastapi.testclient import TestClient


def _drop_runtime_settings_table():
    from app.database.config import engine

    with engine.begin() as conn:
        conn.execute(text('DROP TABLE IF EXISTS "runtime_settings"'))


def _restore_runtime_settings_table():
    from app.database.config import engine
    from app.services.runtime_settings_bootstrap import ensure_runtime_settings_schema_for_engine

    ensure_runtime_settings_schema_for_engine(engine)


@pytest.fixture
def client() -> TestClient:
    from main import app

    return TestClient(app)


def test_get_followups_dispatch_fail_open_when_table_missing():
    from app.database.config import SessionLocal
    from app.services.runtime_settings_store import get_followups_dispatch_enabled

    _drop_runtime_settings_table()
    try:
        db = SessionLocal()
        try:
            assert get_followups_dispatch_enabled(db) is True
        finally:
            db.close()
    finally:
        _restore_runtime_settings_table()


def test_get_followups_dispatch_empty_table_defaults_true():
    from app.database.config import SessionLocal, engine
    from app.models.runtime_setting import RuntimeSetting
    from app.services.runtime_settings_store import get_followups_dispatch_enabled

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM runtime_settings"))
    db = SessionLocal()
    try:
        assert db.query(RuntimeSetting).count() == 0
        assert get_followups_dispatch_enabled(db) is True
    finally:
        db.close()
        _restore_runtime_settings_table()


def test_get_followups_dispatch_respects_false_row():
    from app.database.config import SessionLocal
    from app.services.runtime_settings_store import (
        get_followups_dispatch_enabled,
        set_followups_dispatch_enabled,
    )

    db = SessionLocal()
    try:
        set_followups_dispatch_enabled(db, False)
        assert get_followups_dispatch_enabled(db) is False
        set_followups_dispatch_enabled(db, True)
        assert get_followups_dispatch_enabled(db) is True
    finally:
        db.close()


def test_dispatch_settings_get_never_500_when_table_missing(client: TestClient):
    _drop_runtime_settings_table()
    try:
        r = client.get("/followups/settings/dispatch")
        assert r.status_code == 200
        body = r.json()
        assert body.get("followups_dispatch_enabled") is True
    finally:
        _restore_runtime_settings_table()


def test_dispatch_settings_put_recreates_table_then_persists(client: TestClient):
    _drop_runtime_settings_table()
    try:
        r = client.put("/followups/settings/dispatch", json={"enabled": False})
        assert r.status_code == 200
        assert r.json().get("ok") is True
        g = client.get("/followups/settings/dispatch")
        assert g.status_code == 200
        assert g.json().get("followups_dispatch_enabled") is False
    finally:
        _restore_runtime_settings_table()


def test_followups_settings_checksum_shape(client: TestClient):
    r = client.get("/followups/settings/checksum")
    assert r.status_code == 200
    b = r.json()
    assert "followups_env_enabled" in b
    assert "dispatch_toggle" in b
    assert "effective_dispatch" in b
    assert "source" in b


def test_followups_dispatch_toggle_writes_audit_log(client: TestClient):
    from app.database.config import SessionLocal
    from app.models.audit_log import AuditLog

    r = client.put("/followups/settings/dispatch", json={"enabled": False, "reason": "incident-999-test"})
    assert r.status_code == 200
    db = SessionLocal()
    try:
        row = (
            db.query(AuditLog)
            .filter(AuditLog.action == "followups_dispatch_toggle")
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        assert row is not None
        assert "incident-999-test" in (row.meta or "")
    finally:
        db.close()
    client.put("/followups/settings/dispatch", json={"enabled": True, "reason": "reset after test"})


def test_set_followups_dispatch_uses_bootstrap_when_table_was_dropped():
    from app.database.config import SessionLocal
    from app.services.runtime_settings_store import get_followups_dispatch_enabled, set_followups_dispatch_enabled

    _drop_runtime_settings_table()
    try:
        db = SessionLocal()
        try:
            set_followups_dispatch_enabled(db, False)
            assert get_followups_dispatch_enabled(db) is False
        finally:
            db.close()
    finally:
        _restore_runtime_settings_table()
