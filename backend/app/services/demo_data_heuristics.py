"""
Heuristics to flag likely seeded / demo / synthetic test rows.

Conservative by default: short or odd names alone do NOT qualify unless combined
with a disposable domain, is_demo, or other strong signals.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

# Domains that should never appear on real production outreach.
DISPOSABLE_EMAIL_DOMAINS: frozenset[str] = frozenset(
    {
        "example.com",
        "example.org",
        "example.net",
        "test.com",
        "test.org",
        "localhost",
        "invalid",
        "mailinator.com",
        "yopmail.com",
        "guerrillamail.com",
        "10minutemail.com",
        "discard.email",
    }
)

# Local-part prefixes typical of fixtures / smoke tests.
SYNTHETIC_LOCALPART_PREFIXES: tuple[str, ...] = (
    "test",
    "demo",
    "fake",
    "dummy",
    "seed",
    "fixture",
    "noreply",
    "no-reply",
    "donotreply",
    "bounce",
    "mailer-daemon",
)

# Exact student/HR names seen in tests or trivial placeholders (case-insensitive match).
SYNTHETIC_EXACT_NAMES: frozenset[str] = frozenset(
    {
        "s",
        "s2",
        "t",
        "x",
        "tie",
        "od",
        "dim",
        "test",
        "demo",
        "fake",
        "student",
        "hr",
        "placeholder",
        "sample",
        "foo",
        "bar",
        "baz",
        "a",
        "b",
        "c",
        "d",
        "e",
    }
)

# Company patterns (tests / synthetic orgs).
_COMPANY_SYNTHETIC_RES = (
    re.compile(r"^c\d+$", re.I),
    re.compile(r"^co\d*$", re.I),
    re.compile(r"^corp\s*test", re.I),
    re.compile(r"^test\s+(corp|company|co)", re.I),
    re.compile(r"^demo\s+", re.I),
    re.compile(r"^fake\s+", re.I),
    re.compile(r"^sample\s+", re.I),
    re.compile(r"^acme\b", re.I),
    re.compile(r"^widget\s+inc", re.I),
    re.compile(r"^company\s*\d+$", re.I),
)


def _domain_from_email(email: str) -> str:
    e = (email or "").strip().lower()
    if "@" not in e:
        return ""
    return e.rsplit("@", 1)[-1]


def _local_from_email(email: str) -> str:
    e = (email or "").strip().lower()
    if "@" not in e:
        return e
    return e.split("@", 1)[0]


def email_domain_flags(email: str) -> list[str]:
    out: list[str] = []
    dom = _domain_from_email(email)
    if not dom:
        return ["email_empty_or_invalid"]
    disposable_hit = dom in DISPOSABLE_EMAIL_DOMAINS or any(dom.endswith("." + d) for d in DISPOSABLE_EMAIL_DOMAINS)
    if disposable_hit:
        out.append(f"domain_disposable:{dom}")
    # Patterned dev hosts
    if dom.endswith(".local") or dom.endswith(".test") or dom.endswith(".invalid"):
        out.append(f"domain_tld_testlike:{dom}")
    return out


def email_local_flags(email: str) -> list[str]:
    out: list[str] = []
    local = _local_from_email(email)
    if not local:
        return out
    for p in SYNTHETIC_LOCALPART_PREFIXES:
        if local == p or local.startswith(p + ".") or local.startswith(p + "+") or local.startswith(p + "_"):
            out.append(f"local_prefix:{p}")
            break
    # user123@ / hr1@ style
    if re.match(r"^(user|hr|student|contact|u|h)\d+$", local, re.I):
        out.append("local_pattern_numeric_fixture")
    if "+" in local:
        tag = local.split("+", 1)[-1]
        if any(tag.lower().startswith(p) for p in ("test", "demo", "fake", "seed")):
            out.append("local_plus_tag_testlike")
    return out


def name_flags(name: str, *, field: str = "name") -> list[str]:
    out: list[str] = []
    n = (name or "").strip()
    if not n:
        out.append(f"{field}_empty")
        return out
    key = n.lower()
    if key in SYNTHETIC_EXACT_NAMES:
        out.append(f"{field}_exact_synthetic:{key}")
    # All-caps very short token (often test matrix labels)
    if len(n) <= 3 and n.isalpha() and n.isupper() and n.upper() == n:
        out.append(f"{field}_short_allcaps")
    return out


def company_flags(company: str) -> list[str]:
    out: list[str] = []
    c = (company or "").strip()
    if not c:
        return out
    cl = c.lower()
    if cl in {"test", "demo", "fake", "sample", "acme", "none", "n/a"}:
        out.append("company_exact_placeholder")
    for rx in _COMPANY_SYNTHETIC_RES:
        if rx.search(c):
            out.append(f"company_pattern:{rx.pattern}")
            break
    return out


@dataclass(frozen=True)
class RiskAssessment:
    """Higher score = more likely demo/synthetic. ``reasons`` are human-readable flags."""

    score: int
    reasons: tuple[str, ...]


def _score_from_flags(flags: Iterable[str]) -> int:
    s = 0
    for f in flags:
        if f.startswith("is_demo"):
            s += 100
        elif f.startswith("domain_disposable") or f.startswith("domain_tld_testlike"):
            s += 50
        elif f.startswith("local_prefix") or f.startswith("local_pattern") or f.startswith("local_plus"):
            s += 35
        elif (
            f.startswith("student_name_exact_synthetic")
            or f.startswith("hr_name_exact_synthetic")
            or f.startswith("name_exact_synthetic")
        ):
            s += 25
        elif f.startswith("company_exact_placeholder") or f.startswith("company_pattern"):
            s += 20
        elif f.endswith("_short_allcaps"):
            s += 8
        elif f.endswith("_empty"):
            s += 5
    return s


def assess_student(*, name: str, gmail_address: str, is_demo: bool | None) -> RiskAssessment:
    flags: list[str] = []
    if is_demo is True:
        flags.append("is_demo:true")
    flags.extend(email_domain_flags(gmail_address))
    flags.extend(email_local_flags(gmail_address))
    flags.extend(name_flags(name, field="student_name"))
    # Short synthetic name only counts extra if email also looks non-production
    if any(x.startswith("student_name_short_allcaps") for x in flags) and (
        any(x.startswith("domain_") for x in flags) or any(x.startswith("local_") for x in flags)
    ):
        flags.append("combo_short_name_and_suspicious_email")
    return RiskAssessment(score=_score_from_flags(flags), reasons=tuple(dict.fromkeys(flags)))


def assess_hr(*, name: str, company: str, email: str, is_demo: bool | None) -> RiskAssessment:
    flags: list[str] = []
    if is_demo is True:
        flags.append("is_demo:true")
    flags.extend(email_domain_flags(email))
    flags.extend(email_local_flags(email))
    flags.extend(name_flags(name, field="hr_name"))
    flags.extend(company_flags(company))
    if any(x.startswith("hr_name_short_allcaps") for x in flags) and (
        any(x.startswith("domain_") for x in flags) or any(x.startswith("local_") for x in flags) or any(
            x.startswith("company_") for x in flags
        )
    ):
        flags.append("combo_hr_short_name_and_context")
    return RiskAssessment(score=_score_from_flags(flags), reasons=tuple(dict.fromkeys(flags)))
