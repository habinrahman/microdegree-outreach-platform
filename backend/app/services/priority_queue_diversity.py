"""
Phase 2: diversity & exploration layer on top of standard priority ordering.

Re-ranks visible rows only; does not change base scores, buckets, or suppress rules.
Exploration never selects SUPPRESS rows.
"""

from __future__ import annotations

import math
import os
from collections import Counter
from collections.abc import Sequence
from typing import Any, Protocol, TypeVar

from app.services.hr_health_scoring import email_domain

T = TypeVar("T", bound="PriorityRowLike")


class PriorityRowLike(Protocol):
    student: Any
    hr: Any
    priority_score: float
    queue_bucket: str
    hr_tier: str
    health_score: float
    opportunity_score: float
    dimension_scores: dict[str, float]
    followup_status: str | None
    recommendation_reason: list[str]


def _i(name: str, default: str) -> int:
    try:
        return int((os.getenv(name) or default).strip())
    except ValueError:
        return int(default)


def _f(name: str, default: str) -> float:
    try:
        return float((os.getenv(name) or default).strip())
    except ValueError:
        return float(default)


DIV_HR_CAP = max(1, _i("PRIORITY_DIV_HR_CAP", "2"))
DIV_STUDENT_FLOOR = max(0, _i("PRIORITY_DIV_STUDENT_FLOOR", "1"))
DIV_EXPLORATION_PCT = max(0.0, min(0.25, _f("PRIORITY_DIV_EXPLORATION_PCT", "0.075")))
DIV_MMR_ENABLED = (os.getenv("PRIORITY_DIV_MMR_ENABLED") or "").strip().lower() in ("1", "true", "yes")
DIV_MMR_LAMBDA = max(0.0, _f("PRIORITY_DIV_MMR_LAMBDA", "0.22"))
DIV_MMR_WINDOW = max(5, _i("PRIORITY_DIV_MMR_WINDOW", "24"))


def _pair_key(row: PriorityRowLike) -> tuple[Any, Any]:
    return (row.student.id, row.hr.id)


def _norm_company(row: PriorityRowLike) -> str:
    return (getattr(row.hr, "company", None) or "").strip().lower()


def _norm_domain(row: PriorityRowLike) -> str:
    return email_domain(getattr(row.hr, "email", None) or "")


def _is_suppress(row: PriorityRowLike) -> bool:
    return (row.queue_bucket or "").upper() == "SUPPRESS"


def _is_send_or_fu(row: PriorityRowLike) -> bool:
    return row.queue_bucket in ("SEND_NOW", "FOLLOW_UP_DUE")


def _clear_slot_tags(rows: Sequence[PriorityRowLike]) -> None:
    for r in rows:
        if hasattr(r, "ranking_slot_type"):
            setattr(r, "ranking_slot_type", None)


def _mmr_adjusted(row: PriorityRowLike, selected: Sequence[PriorityRowLike], lam: float) -> float:
    pen = 0.0
    hid = row.hr.id
    co = _norm_company(row)
    dom = _norm_domain(row)
    for s in selected:
        if s.hr.id == hid:
            pen += 40.0
        if _norm_company(s) == co and co:
            pen += 14.0
        if _norm_domain(s) == dom and dom:
            pen += 9.0
    return float(row.priority_score) - lam * pen


def _exploration_eligible(row: PriorityRowLike) -> bool:
    if _is_suppress(row):
        return False
    if row.queue_bucket in ("SEND_NOW", "FOLLOW_UP_DUE"):
        return False
    reasons = " ".join(row.recommendation_reason or "").lower()
    if "initial not sent" in reasons or "fresh assignment" in reasons:
        return True
    if row.queue_bucket == "LOW_PRIORITY" and row.opportunity_score >= 42.0:
        return True
    if (row.followup_status or "").upper() == "WAITING" and "initial" in reasons:
        return True
    return False


def _exploration_score(row: PriorityRowLike) -> float:
    u = float(row.dimension_scores.get("followup_urgency", 0.0))
    return row.opportunity_score * 0.55 + row.health_score * 0.25 + (55.0 - min(u, 55.0)) * 0.2


def compute_diversity_metrics(
    top_rows: Sequence[PriorityRowLike],
    *,
    k: int,
    pool_nonsup_student_ids: set[Any] | None = None,
) -> dict[str, Any]:
    """Concentration and starvation stats for visible top-K."""
    if not top_rows:
        return {
            "top_k": 0,
            "hr_concentration_max_share": 0.0,
            "student_concentration_max_share": 0.0,
            "exploration_share": 0.0,
            "unique_hrs_in_top_k": 0,
            "unique_students_in_top_k": 0,
            "students_starved_in_top_k_nonsup": 0,
        }

    k = max(1, min(k, len(top_rows)))
    slice_r = list(top_rows[:k])
    hr_c = Counter(r.hr.id for r in slice_r)
    st_c = Counter(r.student.id for r in slice_r)
    expl = sum(1 for r in slice_r if getattr(r, "ranking_slot_type", None) == "EXPLORATION")

    nonsup_slice = [r for r in slice_r if not _is_suppress(r)]
    st_nonsup = {r.student.id for r in nonsup_slice}
    starved = 0
    if pool_nonsup_student_ids:
        starved = len(pool_nonsup_student_ids - st_nonsup)

    return {
        "top_k": k,
        "hr_concentration_max_share": round(max(hr_c.values()) / k, 4),
        "student_concentration_max_share": round(max(st_c.values()) / k, 4),
        "exploration_share": round(expl / k, 4),
        "unique_hrs_in_top_k": len(hr_c),
        "unique_students_in_top_k": len(st_c),
        "students_starved_in_top_k_nonsup": starved,
    }


def apply_diversity_layer(
    standard_sorted: list[T],
    limit: int,
    *,
    diversified: bool,
) -> tuple[list[T], dict[str, Any]]:
    """
    Re-rank up to ``limit`` rows. Standard mode returns ``standard_sorted[:limit]`` unchanged
    (after clearing exploration tags) and baseline metrics.
    """
    lim = max(1, min(int(limit), 500))
    _clear_slot_tags(standard_sorted)
    std_top = list(standard_sorted[:lim])
    m_base = compute_diversity_metrics(
        std_top,
        k=lim,
        pool_nonsup_student_ids={r.student.id for r in standard_sorted if not _is_suppress(r)},
    )
    m_base["ranking_mode"] = "standard"
    m_base["diversity_layer_applied"] = False
    m_base["requested_limit"] = lim
    m_base["returned_count"] = len(std_top)

    if not diversified:
        return std_top, m_base

    non_sup = [r for r in standard_sorted if not _is_suppress(r)]
    sup_tail = [r for r in standard_sorted if _is_suppress(r)]
    pool_ns_students = {r.student.id for r in non_sup}

    explore_n = int(math.ceil(lim * DIV_EXPLORATION_PCT))
    explore_n = max(0, min(lim - 1, explore_n))
    main_budget = lim - explore_n

    chosen: list[T] = []
    chosen_keys: set[tuple[Any, Any]] = set()
    hr_counts: Counter[Any] = Counter()
    st_counts: Counter[Any] = Counter()

    def can_take_hr_cap(r: T) -> bool:
        return hr_counts[r.hr.id] < DIV_HR_CAP

    def take(r: T, *, slot: str | None) -> None:
        chosen.append(r)
        chosen_keys.add(_pair_key(r))
        hr_counts[r.hr.id] += 1
        st_counts[r.student.id] += 1
        if slot:
            setattr(r, "ranking_slot_type", slot)
        elif hasattr(r, "ranking_slot_type"):
            setattr(r, "ranking_slot_type", None)

    # --- Student visibility floor (non-suppress): best-effort min rows per student ---
    if DIV_STUDENT_FLOOR > 0 and main_budget > 0:
        first_idx: dict[Any, int] = {}
        for i, r in enumerate(non_sup):
            sid = r.student.id
            if sid not in first_idx:
                first_idx[sid] = i
        ordered_students = sorted(first_idx.keys(), key=lambda s: first_idx[s])
        for sid in ordered_students:
            while st_counts[sid] < DIV_STUDENT_FLOOR and len(chosen) < main_budget:
                placed = False
                for r in non_sup:
                    if r.student.id != sid:
                        continue
                    if _pair_key(r) in chosen_keys:
                        continue
                    if not can_take_hr_cap(r):
                        continue
                    take(r, slot=None)
                    placed = True
                    break
                if not placed:
                    break

    # --- Greedy + optional MMR (SEND_NOW / FOLLOW_UP_DUE only for MMR choice) ---
    def remaining_pool() -> list[T]:
        return [r for r in non_sup if _pair_key(r) not in chosen_keys]

    while len(chosen) < main_budget:
        rem = remaining_pool()
        if not rem:
            break
        window = rem[:DIV_MMR_WINDOW]
        pick: T | None = None
        cand_cap = [r for r in window if can_take_hr_cap(r)]
        if not cand_cap:
            break
        send_fu = [r for r in cand_cap if _is_send_or_fu(r)]
        if DIV_MMR_ENABLED and send_fu:
            pick = max(send_fu, key=lambda r: _mmr_adjusted(r, chosen, DIV_MMR_LAMBDA))
        else:
            pick = cand_cap[0]
        take(pick, slot=None)

    # --- Exploration slots (tail) ---
    explore_pool = [r for r in non_sup if _pair_key(r) not in chosen_keys and _exploration_eligible(r)]
    explore_pool.sort(key=lambda r: (-_exploration_score(r), str(r.student.id), str(r.hr.id)))
    for r in explore_pool:
        if len(chosen) >= lim:
            break
        if _pair_key(r) in chosen_keys:
            continue
        take(r, slot="EXPLORATION")

    # --- Pad with standard order (respect hr cap) ---
    if len(chosen) < lim:
        for r in non_sup:
            if len(chosen) >= lim:
                break
            if _pair_key(r) in chosen_keys:
                continue
            if not can_take_hr_cap(r):
                continue
            take(r, slot=None)

    if len(chosen) < lim:
        for r in sup_tail:
            if len(chosen) >= lim:
                break
            if _pair_key(r) in chosen_keys:
                continue
            take(r, slot=None)

    out = chosen[:lim]
    expl_n = sum(1 for r in out if getattr(r, "ranking_slot_type", None) == "EXPLORATION")
    k_eff = max(1, len(out))

    m_div = compute_diversity_metrics(out, k=k_eff, pool_nonsup_student_ids=pool_ns_students)
    m_std = compute_diversity_metrics(std_top, k=min(lim, len(std_top)), pool_nonsup_student_ids=pool_ns_students)

    std_ns_students = {r.student.id for r in std_top if not _is_suppress(r)}
    div_ns_students = {r.student.id for r in out if not _is_suppress(r)}
    gained = len(div_ns_students - std_ns_students)

    metrics = {
        **m_div,
        "requested_limit": lim,
        "returned_count": len(out),
        "ranking_mode": "diversified",
        "diversity_layer_applied": True,
        "hr_cap": DIV_HR_CAP,
        "student_floor": DIV_STUDENT_FLOOR,
        "exploration_pct_config": DIV_EXPLORATION_PCT,
        "exploration_slots_filled": expl_n,
        "mmr_enabled": DIV_MMR_ENABLED,
        "standard_hr_concentration_max_share": m_std["hr_concentration_max_share"],
        "standard_student_concentration_max_share": m_std["student_concentration_max_share"],
        "hr_concentration_delta_vs_standard": round(
            m_div["hr_concentration_max_share"] - m_std["hr_concentration_max_share"], 4
        ),
        "students_gained_visibility_vs_standard_top_k": gained,
    }
    return out, metrics
