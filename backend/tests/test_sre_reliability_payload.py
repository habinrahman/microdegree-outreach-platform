"""SRE reliability payload shape (uses in-memory DB from conftest)."""
from app.database.config import SessionLocal
from app.services.sre_reliability import build_reliability_payload


def test_reliability_payload_structure():
    db = SessionLocal()
    try:
        p = build_reliability_payload(db)
        assert "metrics" in p
        assert "queues" in p
        assert "alerts" in p
        assert "slo_panel" in p
        assert "scheduler" in p
        assert isinstance(p["alerts"], list)
        assert "schema_launch_gate" in p
        sg = p["schema_launch_gate"]
        assert sg.get("status") in ("ok", "degraded", "critical")
        assert isinstance(sg.get("tables"), list)
        assert "sequence_engine" in p
    finally:
        db.close()
