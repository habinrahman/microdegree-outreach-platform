"""
Explicit allow-list style matching for seeded / synthetic ``hr_contacts`` rows only.

No substring domain matching — domains must match the synthetic set exactly (after
normalization). Email synthetic rules apply only to the **local part** prefix.
The ``x_`` prefix does **not** apply to locals starting with ``x_user`` (common real pattern).
"""

from __future__ import annotations

# Longer prefixes first so ``xx_`` wins over ``x_`` for locals like ``xx_a``.
SYNTHETIC_EMAIL_LOCAL_PREFIXES: tuple[str, ...] = (
    "tb0_",
    "tb1_",
    "tb_",
    "sr_",
    "od_",
    "od1_",
    "od2_",
    "dm_",
    "xx_",
    "x_",
    "h_",
    "h2_",
    "hrl_",
    "h_inflight_",
    "h_step_",
    "h_reply_",
    "h_pause_",
)

SYNTHETIC_DOMAINS: frozenset[str] = frozenset(
    {
        "samecorp.com",
        "corp2.com",
        "acme.com",
        "blk.com",
    }
)

# Exact match (case-insensitive, trimmed) on **name** OR **company** alone.
SYNTHETIC_EXACT_NAME_OR_COMPANY: frozenset[str] = frozenset(
    {
        "c0",
        "c1",
        "co",
        "co2",
        "a",
        "b",
        "x",
        "y",
        "z",
        "h",
        "h2",
        "good",
    }
)

_PATTERN_VERSION = 1


def _local_domain(email: str) -> tuple[str, str]:
    e = (email or "").strip().lower()
    if "@" not in e:
        return "", ""
    local, _, dom = e.partition("@")
    return local, dom


def synthetic_match_reasons(*, email: str, name: str, company: str) -> list[str]:
    """All explicit reasons this row is considered synthetic (empty if not)."""
    reasons: list[str] = []
    local, dom = _local_domain(email)

    if dom and dom in SYNTHETIC_DOMAINS:
        reasons.append(f"domain:{dom}")

    for p in SYNTHETIC_EMAIL_LOCAL_PREFIXES:
        if p == "x_" and local.startswith("x_user"):
            # Avoid false positives for locals like ``x_user@exactlycorp.com``.
            continue
        if local.startswith(p):
            reasons.append(f"email_local_prefix:{p}")
            break

    n = (name or "").strip().lower()
    c = (company or "").strip().lower()
    if n in SYNTHETIC_EXACT_NAME_OR_COMPANY:
        reasons.append(f"name_exact:{n}")
    if c in SYNTHETIC_EXACT_NAME_OR_COMPANY:
        reasons.append(f"company_exact:{c}")

    return reasons


def is_synthetic_hr(*, email: str, name: str, company: str) -> bool:
    return bool(synthetic_match_reasons(email=email, name=name, company=company))


def primary_synthetic_bucket(*, email: str, name: str, company: str) -> str | None:
    """Single bucket key for reporting (priority: domain → email prefix → name → company)."""
    rs = synthetic_match_reasons(email=email, name=name, company=company)
    if not rs:
        return None
    for key in ("domain:", "email_local_prefix:", "name_exact:", "company_exact:"):
        for r in rs:
            if r.startswith(key):
                return r
    return rs[0]


def pattern_version() -> int:
    return _PATTERN_VERSION


def assert_safe_real_domain_examples() -> None:
    """Runtime self-check (also covered by unit tests)."""
    samples = [
        ("r@exactlycorp.com", "Rec", "Exactly"),
        ("h@unacademy.com", "HR", "Unacademy"),
        ("t@talkdesk.com", "T", "Talkdesk"),
        ("xavier@exactlycorp.com", "U", "Exactly"),
    ]
    for email, name, company in samples:
        assert not is_synthetic_hr(email=email, name=name, company=company), email
