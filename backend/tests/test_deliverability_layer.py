"""Deliverability heuristics and gate (layer default off)."""
from unittest.mock import patch

from app.services.deliverability_layer import (
    compute_spam_risk_score,
    deliverability_layer_enabled,
    evaluate_deliverability_for_send,
)


def test_spam_score_clean():
    s = compute_spam_risk_score("Hello", "Thanks for reading.")
    assert s["spam_risk_tier"] == "low"
    assert s["spam_risk_score"] < 35


def test_spam_score_trigger_phrase():
    s = compute_spam_risk_score("Winner", "You are a guaranteed winner! click here now!!!!")
    assert s["spam_risk_score"] >= 25
    assert s["spam_reasons"]
    assert s["spam_risk_tier"] in ("low", "medium", "high")


def test_gate_skipped_when_layer_disabled(monkeypatch):
    monkeypatch.delenv("DELIVERABILITY_LAYER", raising=False)
    assert deliverability_layer_enabled() is False

    class _Db:
        pass

    class _St:
        id = "00000000-0000-4000-8000-000000000001"
        gmail_address = "a@gmail.com"
        email_health_status = "healthy"
        created_at = None
        last_sent_at = None

    d = evaluate_deliverability_for_send(_Db(), _St(), "Hi", "Body")  # type: ignore[arg-type]
    assert d["allow"] is True
    assert d.get("skipped") is True


def test_gate_blocks_extreme_spam_when_enabled(monkeypatch):
    monkeypatch.setenv("DELIVERABILITY_LAYER", "1")
    monkeypatch.setenv("DELIVERABILITY_SPAM_BLOCK_SCORE", "10")

    class _Db:
        pass

    class _St:
        id = "00000000-0000-4000-8000-000000000002"
        gmail_address = "b@gmail.com"
        email_health_status = "healthy"
        created_at = None
        last_sent_at = None

    body = "winner winner " + "FREE!!! " * 20
    with (
        patch("app.services.deliverability_layer.count_recent_bounces", return_value=0),
        patch("app.services.deliverability_layer.count_sends_today_utc", return_value=0),
        patch(
            "app.services.deliverability_layer.compute_sending_reputation_score",
            return_value={
                "reputation_score": 99,
                "bounce_events_window": 0,
                "reply_positive_ratio": 0.0,
                "email_health_status": "healthy",
            },
        ),
    ):
        d = evaluate_deliverability_for_send(_Db(), _St(), "ACT NOW", body)  # type: ignore[arg-type]
    assert d["allow"] is False
    assert any("spam_risk" in r for r in (d.get("block_reasons") or []))
