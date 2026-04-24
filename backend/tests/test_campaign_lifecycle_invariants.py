"""Invariant tests for ``EmailCampaign.status`` lifecycle (see ``campaign_lifecycle`` service)."""

from __future__ import annotations

import pytest

from app.services.campaign_lifecycle import (
    BULK_PENDING_TO_SCHEDULED,
    BULK_PROCESSING_TO_PAUSED_STALE,
    FORBIDDEN_TRANSITION_EXAMPLES,
    KNOWN_STATUSES,
    LEGAL_EMAIL_CAMPAIGN_TRANSITIONS,
    TERMINAL_STATUSES,
    assert_legal_email_campaign_transition,
    build_lifecycle_visualization_payload,
    build_mermaid_state_diagram,
    is_legal_email_campaign_transition,
    transition_map_markdown,
)


def test_known_statuses_cover_all_fsm_keys_and_targets():
    keys = set(LEGAL_EMAIL_CAMPAIGN_TRANSITIONS.keys())
    targets: set[str] = set()
    for dests in LEGAL_EMAIL_CAMPAIGN_TRANSITIONS.values():
        targets.update(dests)
    all_seen = keys | targets
    missing = all_seen - KNOWN_STATUSES
    assert not missing, f"Unknown status token in graph: {missing}"
    unused = KNOWN_STATUSES - all_seen
    assert not unused, f"KNOWN_STATUSES has unused entries: {unused}"


@pytest.mark.parametrize("src,dst", sorted(FORBIDDEN_TRANSITION_EXAMPLES))
def test_explicitly_forbidden_transitions_rejected(src: str, dst: str):
    assert is_legal_email_campaign_transition(src, dst) is False
    with pytest.raises(ValueError, match="Illegal EmailCampaign"):
        assert_legal_email_campaign_transition(src, dst, context="test/forbidden")


def test_all_declared_edges_are_legal():
    for src, dests in LEGAL_EMAIL_CAMPAIGN_TRANSITIONS.items():
        for dst in dests:
            assert is_legal_email_campaign_transition(src, dst) is True, f"edge {src!r}->{dst!r}"


def test_same_status_always_legal():
    for s in KNOWN_STATUSES:
        assert is_legal_email_campaign_transition(s, s) is True


def test_normalize_empty_defaults_pending():
    assert is_legal_email_campaign_transition(None, "scheduled") is True
    assert is_legal_email_campaign_transition("", "scheduled") is True


def test_transition_map_markdown_documents_bulk_pending_scheduled():
    md = transition_map_markdown()
    assert "EmailCampaign.status" in md
    assert "campaign_scheduler" in md
    assert BULK_PENDING_TO_SCHEDULED in md
    assert BULK_PROCESSING_TO_PAUSED_STALE in md


def test_pending_to_scheduled_row_level_legal_mirrors_bulk_intent():
    assert is_legal_email_campaign_transition("pending", "scheduled") is True


def test_processing_to_scheduled_group_pause():
    assert is_legal_email_campaign_transition("processing", "scheduled") is True


def test_failed_to_pending_retry_path():
    assert is_legal_email_campaign_transition("failed", "pending") is True


def test_sent_to_replied_and_sent_to_failed():
    assert is_legal_email_campaign_transition("sent", "replied") is True
    assert is_legal_email_campaign_transition("sent", "failed") is True


def test_replied_is_terminal_in_graph():
    assert LEGAL_EMAIL_CAMPAIGN_TRANSITIONS["replied"] == frozenset({"replied"})


def test_cancelled_and_expired_terminals():
    assert LEGAL_EMAIL_CAMPAIGN_TRANSITIONS["cancelled"] == frozenset({"cancelled"})
    assert LEGAL_EMAIL_CAMPAIGN_TRANSITIONS["expired"] == frozenset({"expired"})


def test_terminal_const_matches_fsm_self_loops():
    for t in TERMINAL_STATUSES:
        assert t in LEGAL_EMAIL_CAMPAIGN_TRANSITIONS
        assert LEGAL_EMAIL_CAMPAIGN_TRANSITIONS[t] == frozenset({t})


def test_build_mermaid_state_diagram_includes_edges():
    s = build_mermaid_state_diagram()
    assert "stateDiagram-v2" in s
    assert "-->" in s
    assert "pending" in s and "sent" in s


def test_build_lifecycle_visualization_payload_schema_roundtrip():
    from app.database.config import SessionLocal
    from app.schemas.campaign_lifecycle import LifecycleVisualizationResponse

    db = SessionLocal()
    try:
        raw = build_lifecycle_visualization_payload(db)
        m = LifecycleVisualizationResponse(**raw)
        assert m.total_campaign_rows >= 0
        assert len(m.edges) >= 5
        assert m.mermaid_state_diagram.startswith("stateDiagram")
    finally:
        db.close()
