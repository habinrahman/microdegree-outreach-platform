"""
HR Health + Opportunity scoring and A/B/C/D tiering.

Two independent 0–100 scores:
- health_score: deliverability / list hygiene (bounces, failures, validity, pause, domain heuristics)
- opportunity_score: responsiveness / upside (replies, positive signals, recency, engagement)

Tiers are derived from both scores plus hard suppress rules. Reasons[] explain outcomes (not a black box).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from app.models import HRContact
from app.models.email_campaign import EmailCampaign

# --- Tier ordering (1 = best) -------------------------------------------------
TIER_RANK: dict[str, int] = {"A": 1, "B": 2, "C": 3, "D": 4}
RANK_TIER: dict[int, str] = {1: "A", 2: "B", 3: "C", 4: "D"}

# --- Tunable thresholds (override via env for ops tuning) --------------------
def _f(name: str, default: str) -> float:
    try:
        return float((os.getenv(name) or default).strip())
    except ValueError:
        return float(default)


# Health: penalize bounce rate above this fraction heavily
HR_HEALTH_BOUNCE_SOFT = _f("HR_HEALTH_BOUNCE_SOFT", "0.12")
HR_HEALTH_BOUNCE_HARD = _f("HR_HEALTH_BOUNCE_HARD", "0.28")

# Tier boundaries (health × opportunity space)
HR_TIER_A_HEALTH_MIN = _f("HR_TIER_A_HEALTH_MIN", "72")
HR_TIER_A_OPP_MIN = _f("HR_TIER_A_OPP_MIN", "58")
HR_TIER_B_HEALTH_MIN = _f("HR_TIER_B_HEALTH_MIN", "50")
HR_TIER_B_OPP_MIN = _f("HR_TIER_B_OPP_MIN", "42")
HR_TIER_D_HEALTH_MAX = _f("HR_TIER_D_HEALTH_MAX", "28")
HR_TIER_D_COMBO_HEALTH = _f("HR_TIER_D_COMBO_HEALTH", "40")
HR_TIER_D_COMBO_OPP = _f("HR_TIER_D_COMBO_OPP", "22")
HR_TIER_D_BOUNCE_RATE = _f("HR_TIER_D_BOUNCE_RATE", "0.35")

CONSUMER_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "yahoo.co.in",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "msn.com",
        "icloud.com",
        "protonmail.com",
        "proton.me",
        "aol.com",
        "ymail.com",
    }
)

POSITIVE_REPLY_TYPES = frozenset({"INTERESTED", "INTERVIEW"})
POSITIVE_REPLY_STATUSES = frozenset({"INTERESTED", "INTERVIEW"})


def email_domain(email: str) -> str:
    parts = (email or "").strip().lower().split("@")
    return parts[1] if len(parts) == 2 else ""


def is_consumer_email_domain(email: str) -> bool:
    return email_domain(email) in CONSUMER_EMAIL_DOMAINS


@dataclass
class _CampaignAgg:
    n_rows: int = 0
    n_sent_like: int = 0  # status in sent, replied, failed (outbound attempted)
    n_replied: int = 0
    n_positive: int = 0
    n_delivery_problem: int = 0  # single bucket: bounce OR delivery failed (no double count per row)
    n_failed_other: int = 0  # status failed but not counted as delivery_problem


def _batch_campaign_aggregates(db: Session, hr_ids: list) -> dict[Any, _CampaignAgg]:
    if not hr_ids:
        return {}
    # Per-row: delivery_problem = bounce-ish OR delivery_status FAILED (one flag per row max in SQL)
    delivery_problem = or_(
        EmailCampaign.reply_status.in_(("BOUNCED", "BOUNCE")),
        EmailCampaign.delivery_status == "FAILED",
    )
    sent_like = EmailCampaign.status.in_(("sent", "replied", "failed", "cancelled", "paused", "expired"))
    replied = EmailCampaign.replied.is_(True)
    positive = or_(
        EmailCampaign.reply_type.in_(tuple(POSITIVE_REPLY_TYPES)),
        EmailCampaign.reply_status.in_(tuple(POSITIVE_REPLY_STATUSES)),
    )
    failed_status = EmailCampaign.status == "failed"

    rows = (
        db.query(
            EmailCampaign.hr_id,
            func.count(EmailCampaign.id).label("n_rows"),
            func.sum(case((sent_like, 1), else_=0)).label("n_sent_like"),
            func.sum(case((replied, 1), else_=0)).label("n_replied"),
            func.sum(case((and_(positive, replied), 1), else_=0)).label("n_positive"),
            func.sum(case((delivery_problem, 1), else_=0)).label("n_delivery_problem"),
            func.sum(
                case(
                    (
                        and_(failed_status, ~delivery_problem),
                        1,
                    ),
                    else_=0,
                )
            ).label("n_failed_other"),
        )
        .filter(EmailCampaign.hr_id.in_(hr_ids))
        .group_by(EmailCampaign.hr_id)
        .all()
    )
    out: dict[Any, _CampaignAgg] = {}
    for r in rows:
        hid = r[0]
        out[hid] = _CampaignAgg(
            n_rows=int(r.n_rows or 0),
            n_sent_like=int(r.n_sent_like or 0),
            n_replied=int(r.n_replied or 0),
            n_positive=int(r.n_positive or 0),
            n_delivery_problem=int(r.n_delivery_problem or 0),
            n_failed_other=int(r.n_failed_other or 0),
        )
    return out


def _domain_histogram(db: Session) -> dict[str, int]:
    """Lowercased email domains -> HR row count (portable SQLite + Postgres)."""
    from collections import Counter

    c: Counter[str] = Counter()
    for (em,) in db.query(HRContact.email).all():
        d = email_domain(em or "")
        if d:
            c[d] += 1
    return dict(c)


def tier_rank(tier: str) -> int:
    return TIER_RANK.get(tier.upper(), 4)


def tier_at_or_above(hr_tier: str, minimum_tier: str | None) -> bool:
    """True if hr_tier is same or better than minimum_tier (A is best)."""
    if not minimum_tier:
        return True
    mt = minimum_tier.strip().upper()
    if mt not in TIER_RANK:
        return True
    return tier_rank(hr_tier) <= TIER_RANK[mt]


def parse_scheduler_min_hr_tier() -> str | None:
    v = (os.getenv("SCHEDULER_MIN_HR_TIER") or "").strip().upper()
    return v if v in TIER_RANK else None


def score_hr(
    hr: HRContact,
    agg: _CampaignAgg | None,
    domain_counts: dict[str, int],
) -> dict[str, Any]:
    """
    Compute health_score, opportunity_score, tier, reasons, components.
    """
    health_reasons: list[dict[str, Any]] = []
    opp_reasons: list[dict[str, Any]] = []
    dom = email_domain(hr.email or "")
    dup_n = domain_counts.get(dom, 0) if dom else 0

    agg = agg or _CampaignAgg()
    denom = max(agg.n_sent_like, 1)
    bounce_rate = agg.n_delivery_problem / denom
    fail_other_rate = agg.n_failed_other / denom
    reply_rate = agg.n_replied / denom
    positive_rate = agg.n_positive / denom if agg.n_sent_like else 0.0

    # --- Health score (start 100, subtract risks) --------------------------------
    health = 100.0
    if not hr.is_valid:
        health = 0.0
        health_reasons.append(
            {
                "code": "invalid_or_suppressed",
                "label": "Contact marked invalid — do not send",
                "impact": "negative",
                "weight": -100.0,
            }
        )
    if (hr.status or "").lower() in ("invalid", "blacklisted"):
        if health > 0:
            health = min(health, 5.0)
        health_reasons.append(
            {
                "code": "status_blocked",
                "label": f"HR status is {hr.status} (blocked list)",
                "impact": "negative",
                "weight": None,
            }
        )

    if hr.is_valid and (hr.status or "").lower() not in ("invalid", "blacklisted"):
        # Bounce / delivery problems (bounded penalty — same signal bucket, no double count)
        bounce_penalty = min(55.0, bounce_rate * 130.0)
        if bounce_penalty >= 8:
            health -= bounce_penalty
            health_reasons.append(
                {
                    "code": "bounce_or_delivery_failure_rate",
                    "label": f"Delivery problems on {agg.n_delivery_problem} / {denom} outbound rows",
                    "impact": "negative",
                    "weight": -round(bounce_penalty, 2),
                }
            )
        elif bounce_rate > HR_HEALTH_BOUNCE_SOFT:
            health_reasons.append(
                {
                    "code": "bounce_rate_moderate",
                    "label": "Some delivery problems — monitor",
                    "impact": "neutral",
                    "weight": None,
                }
            )

        fail_penalty = min(35.0, fail_other_rate * 90.0)
        if fail_penalty >= 6:
            health -= fail_penalty
            health_reasons.append(
                {
                    "code": "send_failed_other",
                    "label": f"Send failures (non-bounce bucket) {agg.n_failed_other} / {denom}",
                    "impact": "negative",
                    "weight": -round(fail_penalty, 2),
                }
            )

        if hr.paused_until is not None:
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)
            pu = hr.paused_until
            if getattr(pu, "tzinfo", None) is None:
                pu = pu.replace(tzinfo=timezone.utc) if pu else pu
            if pu and pu > now:
                health -= 12.0
                health_reasons.append(
                    {
                        "code": "cooldown_active",
                        "label": "HR is paused until a future date (cooldown)",
                        "impact": "negative",
                        "weight": -12.0,
                    }
                )

        if is_consumer_email_domain(hr.email or ""):
            health -= 8.0
            health_reasons.append(
                {
                    "code": "consumer_email_domain",
                    "label": "Consumer-style email domain (lower confidence for corporate HR)",
                    "impact": "negative",
                    "weight": -8.0,
                }
            )

        if dup_n >= 8:
            vol_pen = min(14.0, (dup_n - 7) * 1.5)
            health -= vol_pen
            health_reasons.append(
                {
                    "code": "high_volume_domain",
                    "label": f"Many contacts share domain @{dom} ({dup_n} HR rows) — possible list quality risk",
                    "impact": "negative",
                    "weight": -round(vol_pen, 2),
                }
            )
        elif dup_n >= 4:
            health_reasons.append(
                {
                    "code": "shared_domain_cluster",
                    "label": f"Several HRs on @{dom} — verify not duplicate listings",
                    "impact": "neutral",
                    "weight": None,
                }
            )

        if bounce_rate > HR_HEALTH_BOUNCE_HARD and health > 15:
            health_reasons.append(
                {
                    "code": "bounce_rate_high_tier_risk",
                    "label": "Bounce rate high — likely tier D if combined with low opportunity",
                    "impact": "negative",
                    "weight": None,
                }
            )

    health = max(0.0, min(100.0, health))

    # --- Opportunity score ------------------------------------------------------
    opportunity = 38.0
    if agg.n_sent_like == 0:
        opportunity += 12.0
        opp_reasons.append(
            {
                "code": "no_outbound_history",
                "label": "No outbound history yet — neutral upside (cold)",
                "impact": "neutral",
                "weight": 12.0,
            }
        )
    else:
        opportunity += min(38.0, reply_rate * 95.0)
        if reply_rate >= 0.08:
            opp_reasons.append(
                {
                    "code": "reply_rate_strong",
                    "label": f"Reply rate ~{reply_rate:.0%} across outbound rows",
                    "impact": "positive",
                    "weight": round(min(38.0, reply_rate * 95.0), 2),
                }
            )
        elif reply_rate > 0:
            opp_reasons.append(
                {
                    "code": "reply_rate_low",
                    "label": f"Some replies ({reply_rate:.0%})",
                    "impact": "neutral",
                    "weight": round(min(38.0, reply_rate * 95.0), 2),
                }
            )

        pr = min(1.0, positive_rate)
        opportunity += min(28.0, pr * 120.0)
        if pr >= 0.04:
            opp_reasons.append(
                {
                    "code": "positive_reply_signal",
                    "label": "Interested / interview-class replies observed",
                    "impact": "positive",
                    "weight": round(min(28.0, pr * 120.0), 2),
                }
            )

        if agg.n_sent_like >= 10 and reply_rate < 0.04:
            opportunity -= 18.0
            opp_reasons.append(
                {
                    "code": "low_engagement_history",
                    "label": "Many sends with very low reply rate",
                    "impact": "negative",
                    "weight": -18.0,
                }
            )

    # Recency from HR row
    lc = hr.last_contacted_at
    if lc is not None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        if getattr(lc, "tzinfo", None) is None:
            lc = lc.replace(tzinfo=timezone.utc)
        days = (now - lc).days
        if days <= 14:
            opportunity += 8.0
            opp_reasons.append(
                {
                    "code": "recently_contacted",
                    "label": "Last contacted within 14 days — warm timing window",
                    "impact": "positive",
                    "weight": 8.0,
                }
            )
        elif days >= 120:
            opportunity += 4.0
            opp_reasons.append(
                {
                    "code": "dormant_long_retry",
                    "label": "Long gap since last contact — retry candidate",
                    "impact": "neutral",
                    "weight": 4.0,
                }
            )
    else:
        opportunity += 6.0
        opp_reasons.append(
            {
                "code": "never_contacted_record",
                "label": "No last_contacted_at — net-new outreach potential",
                "impact": "positive",
                "weight": 6.0,
            }
        )

    if not hr.is_valid or (hr.status or "").lower() in ("invalid", "blacklisted"):
        opportunity = min(opportunity, 15.0)
        opp_reasons.append(
            {
                "code": "suppressed_opportunity_cap",
                "label": "Invalid / blocked — opportunity capped",
                "impact": "negative",
                "weight": None,
            }
        )

    opportunity = max(0.0, min(100.0, opportunity))

    # --- Tier mapping ------------------------------------------------------------
    tier = "C"
    if not hr.is_valid or (hr.status or "").lower() in ("invalid", "blacklisted"):
        tier = "D"
    elif health <= HR_TIER_D_HEALTH_MAX:
        tier = "D"
    elif health < HR_TIER_D_COMBO_HEALTH and opportunity < HR_TIER_D_COMBO_OPP:
        tier = "D"
    elif bounce_rate >= HR_TIER_D_BOUNCE_RATE and health < 55:
        tier = "D"
    elif health >= HR_TIER_A_HEALTH_MIN and opportunity >= HR_TIER_A_OPP_MIN:
        tier = "A"
    elif health >= HR_TIER_B_HEALTH_MIN and opportunity >= HR_TIER_B_OPP_MIN:
        tier = "B"
    else:
        tier = "C"

    components = {
        "n_campaign_rows": agg.n_rows,
        "n_sent_like": agg.n_sent_like,
        "n_replied": agg.n_replied,
        "n_positive": agg.n_positive,
        "n_delivery_problem": agg.n_delivery_problem,
        "n_failed_other": agg.n_failed_other,
        "bounce_rate": round(bounce_rate, 4),
        "reply_rate": round(reply_rate, 4),
        "positive_rate": round(positive_rate, 4),
        "email_domain": dom,
        "domain_peer_count": dup_n,
    }

    return {
        "tier": tier,
        "health_score": round(health, 2),
        "opportunity_score": round(opportunity, 2),
        "health_reasons": health_reasons,
        "opportunity_reasons": opp_reasons,
        "components": components,
    }


def compute_health_for_hr_ids(
    db: Session,
    hr_ids: Iterable,
    *,
    skip_domain_histogram: bool = False,
) -> dict[Any, dict[str, Any]]:
    """Batch compute score bundles keyed by hr_id.

    When ``skip_domain_histogram`` is True, skip the global domain peer scan (O(all HR rows));
    peer-domain heuristics in ``score_hr`` see an empty histogram (faster for large DBs, e.g. priority queue).
    """
    ids = list({i for i in hr_ids if i is not None})
    if not ids:
        return {}
    aggs = _batch_campaign_aggregates(db, ids)
    domain_counts: dict[str, int] = {} if skip_domain_histogram else _domain_histogram(db)
    hrs = db.query(HRContact).filter(HRContact.id.in_(ids)).all()
    by_id = {h.id: h for h in hrs}
    out: dict[Any, dict[str, Any]] = {}
    for hid in ids:
        hr = by_id.get(hid)
        if hr is None:
            continue
        out[hid] = score_hr(hr, aggs.get(hid), domain_counts)
    return out


def compute_health_for_one(db: Session, hr_id) -> dict[str, Any] | None:
    hr = db.query(HRContact).filter(HRContact.id == hr_id).first()
    if not hr:
        return None
    return score_hr(hr, _batch_campaign_aggregates(db, [hr_id]).get(hr_id), _domain_histogram(db))
