"""Phase 2 priority queue diversity layer tests."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app.services.priority_queue_diversity import apply_diversity_layer, compute_diversity_metrics


def _hr(hid, company="Acme", email="x@acme.com"):
    return SimpleNamespace(id=hid, company=company, email=email)


def _st(sid, name="S"):
    return SimpleNamespace(id=sid, name=name, gmail_address=f"{name}@t.com")


def _row(
    sid,
    hid,
    *,
    bucket="SEND_NOW",
    score=80.0,
    fu="WAITING",
    reasons=None,
    opp=50.0,
    health=60.0,
    dim_urg=50.0,
):
    return SimpleNamespace(
        student=_st(sid),
        hr=_hr(hid),
        priority_score=score,
        queue_bucket=bucket,
        hr_tier="B",
        health_score=health,
        opportunity_score=opp,
        dimension_scores={"followup_urgency": dim_urg},
        followup_status=fu,
        recommendation_reason=reasons or [],
        ranking_slot_type=None,
    )


def test_deterministic_standard_matches_slice():
    hid = uuid.uuid4()
    rows = [
        _row(uuid.uuid4(), hid, score=90.0),
        _row(uuid.uuid4(), hid, score=80.0),
        _row(uuid.uuid4(), hid, score=70.0),
    ]
    std, m = apply_diversity_layer(rows, limit=2, diversified=False)
    assert [r.priority_score for r in std] == [90.0, 80.0]
    assert m["diversity_layer_applied"] is False


def test_hr_cap_reduces_concentration():
    hr1, hr2 = uuid.uuid4(), uuid.uuid4()
    rows = []
    rows.append(_row(uuid.uuid4(), hr1, score=100.0, bucket="SEND_NOW"))
    rows.append(_row(uuid.uuid4(), hr1, score=99.0, bucket="SEND_NOW"))
    rows.append(_row(uuid.uuid4(), hr1, score=98.0, bucket="SEND_NOW"))
    rows.append(_row(uuid.uuid4(), hr2, score=97.0, bucket="SEND_NOW"))
    rows.append(_row(uuid.uuid4(), hr2, score=96.0, bucket="SEND_NOW"))
    rows.append(_row(uuid.uuid4(), hr2, score=95.0, bucket="SEND_NOW"))
    with patch.multiple(
        "app.services.priority_queue_diversity",
        DIV_HR_CAP=2,
        DIV_STUDENT_FLOOR=0,
        DIV_EXPLORATION_PCT=0.0,
        DIV_MMR_ENABLED=False,
    ):
        out, m = apply_diversity_layer(rows, limit=6, diversified=True)
    hr_counts = __import__("collections").Counter(r.hr.id for r in out)
    assert max(hr_counts.values()) <= 2
    assert len(out) >= 4
    assert m["hr_concentration_max_share"] <= max(hr_counts.values()) / max(len(out), 1) + 0.001
    assert m["diversity_layer_applied"] is True


def test_exploration_never_tags_suppress():
    sid = uuid.uuid4()
    hid = uuid.uuid4()
    rows = [
        _row(sid, hid, bucket="SUPPRESS", score=99.0, reasons=["- bad"]),
        _row(uuid.uuid4(), uuid.uuid4(), bucket="LOW_PRIORITY", score=40.0, reasons=["+ Fresh assignment"]),
    ]
    with patch.multiple(
        "app.services.priority_queue_diversity",
        DIV_HR_CAP=3,
        DIV_STUDENT_FLOOR=0,
        DIV_EXPLORATION_PCT=0.5,
        DIV_MMR_ENABLED=False,
    ):
        out, _m = apply_diversity_layer(rows, limit=4, diversified=True)
    for r in out:
        if getattr(r, "ranking_slot_type", None) == "EXPLORATION":
            assert r.queue_bucket != "SUPPRESS"


def test_no_unsafe_promotion_suppress_not_exploration():
    """Suppress rows are never selected as exploration picks (pool is non-sup only)."""
    rows = [
        _row(uuid.uuid4(), uuid.uuid4(), bucket="SUPPRESS", score=100.0),
        _row(
            uuid.uuid4(),
            uuid.uuid4(),
            bucket="LOW_PRIORITY",
            score=30.0,
            reasons=["+ Fresh assignment — initial not sent"],
        ),
    ]
    with patch.multiple(
        "app.services.priority_queue_diversity",
        DIV_HR_CAP=2,
        DIV_STUDENT_FLOOR=0,
        DIV_EXPLORATION_PCT=0.4,
        DIV_MMR_ENABLED=False,
    ):
        out, _m = apply_diversity_layer(rows, limit=2, diversified=True)
    assert any(r.queue_bucket == "SUPPRESS" for r in out)
    assert not any(
        getattr(r, "ranking_slot_type", None) == "EXPLORATION" and r.queue_bucket == "SUPPRESS" for r in out
    )


def test_student_floor_reduces_starvation():
    """Second student appears in diversified top-k when standard top-k would be hr-greedy."""
    hr_a, hr_b = uuid.uuid4(), uuid.uuid4()
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    rows = [
        _row(s1, hr_a, score=95.0, bucket="SEND_NOW"),
        _row(s1, hr_b, score=94.0, bucket="SEND_NOW"),
        _row(s2, hr_a, score=50.0, bucket="SEND_NOW"),
    ]
    with patch.multiple(
        "app.services.priority_queue_diversity",
        DIV_HR_CAP=2,
        DIV_STUDENT_FLOOR=1,
        DIV_EXPLORATION_PCT=0.0,
        DIV_MMR_ENABLED=False,
    ):
        out, m = apply_diversity_layer(rows, limit=2, diversified=True)
    students = {r.student.id for r in out}
    assert s2 in students
    assert m.get("students_gained_visibility_vs_standard_top_k", 0) >= 0


def test_diversity_metrics_top_k():
    hid = uuid.uuid4()
    r1 = _row(uuid.uuid4(), hid, score=80.0)
    r2 = _row(uuid.uuid4(), hid, score=70.0)
    m = compute_diversity_metrics([r1, r2], k=2, pool_nonsup_student_ids={r1.student.id, r2.student.id})
    assert m["hr_concentration_max_share"] == 1.0
    assert m["unique_hrs_in_top_k"] == 1
