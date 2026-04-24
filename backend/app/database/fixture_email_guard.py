"""
Block test fixture email patterns from reaching non-test databases.

Synthetic rows used by pytest (inv_*, tb0_*, …) must never flush when
``PYTEST_RUNNING`` is unset and ``APP_ENV``/``ENVIRONMENT`` is not ``test``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session, attributes

logger = logging.getLogger(__name__)

# Always-blocked: historically leaked into real DBs (must never flush outside tests).
ALWAYS_BLOCKED_SYNTHETIC_EMAIL_LOCAL_PREFIXES: tuple[str, ...] = (
    "inv_",
    "tb0_",
    "tb1_",
    "od1_",
    "od2_",
    "dm_",
    "dedup_",
    "xx_",
    "s_reply_",
    "s_pause_",
)

# Disposable-domain-only: broader families observed as residual fixtures.
# These are blocked when the domain is clearly synthetic (example.com / test.com / etc.).
DISPOSABLE_DOMAIN_BLOCKED_LOCAL_PREFIXES: tuple[str, ...] = (
    "s2_",
    "s_",
    "fulist_",
    "h2_",
    "h_inflight_",
    "h_step_",
    "h_reply_",
    "h_pause_",
    "hrl_",
    "h_",
    "od_",
    "sr_",
    "tb_",
)

# Exact synthetic fixture emails (legacy tests often used these).
EXACT_BLOCKED_FIXTURE_EMAILS: frozenset[str] = frozenset({"s@example.com", "h@example.com", "s2@example.com", "h2@example.com"})

DISPOSABLE_FIXTURE_DOMAINS: frozenset[str] = frozenset(
    {
        "example.com",
        "example.org",
        "example.net",
        "test.com",
        "test.org",
        "localhost",
        "invalid",
    }
)

_guard_installed = False


def _split_local_domain(email: str | None) -> tuple[str, str]:
    if not email or "@" not in email:
        return "", ""
    local, dom = email.split("@", 1)
    return local.strip().lower(), dom.strip().lower()


def email_local_matches_blocked_fixture_prefix(email: str | None) -> bool:
    local, _ = _split_local_domain(email)
    if not local:
        return False
    return any(local.startswith(p) for p in (*ALWAYS_BLOCKED_SYNTHETIC_EMAIL_LOCAL_PREFIXES, *DISPOSABLE_DOMAIN_BLOCKED_LOCAL_PREFIXES))


def email_matches_blocked_fixture_taxonomy(email: str | None) -> bool:
    e = (email or "").strip().lower()
    if not e:
        return False
    if e in EXACT_BLOCKED_FIXTURE_EMAILS:
        return True
    local, dom = _split_local_domain(e)
    if any(local.startswith(p) for p in ALWAYS_BLOCKED_SYNTHETIC_EMAIL_LOCAL_PREFIXES):
        return True
    if dom in DISPOSABLE_FIXTURE_DOMAINS and any(local.startswith(p) for p in DISPOSABLE_DOMAIN_BLOCKED_LOCAL_PREFIXES):
        return True
    return False


def runtime_allows_synthetic_fixture_emails() -> bool:
    if os.getenv("PYTEST_RUNNING", "").strip() == "1":
        return True
    env = (os.getenv("APP_ENV") or os.getenv("ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    return env == "test"


def _collect_violations(session: Session) -> list[tuple[str, str]]:
    from app.models import HRContact, Student

    violations: list[tuple[str, str]] = []

    for obj in session.new:
        if isinstance(obj, Student):
            if getattr(obj, "is_fixture_test_data", False):
                violations.append(("Student(insert fixture_tag)", str(obj.gmail_address)))
            elif email_matches_blocked_fixture_taxonomy(obj.gmail_address):
                violations.append(("Student(insert)", str(obj.gmail_address)))
        if isinstance(obj, HRContact):
            if getattr(obj, "is_fixture_test_data", False):
                violations.append(("HRContact(insert fixture_tag)", str(obj.email)))
            elif email_matches_blocked_fixture_taxonomy(obj.email):
                violations.append(("HRContact(insert)", str(obj.email)))

    for obj in session.dirty:
        if isinstance(obj, Student):
            if getattr(obj, "is_fixture_test_data", False):
                violations.append(("Student(update fixture_tag)", str(obj.gmail_address)))
            hist: Any = attributes.get_history(obj, "gmail_address")
            if hist.has_changes() and email_matches_blocked_fixture_taxonomy(obj.gmail_address):
                violations.append(("Student(update gmail_address)", str(obj.gmail_address)))
        if isinstance(obj, HRContact):
            if getattr(obj, "is_fixture_test_data", False):
                violations.append(("HRContact(update fixture_tag)", str(obj.email)))
            hist = attributes.get_history(obj, "email")
            if hist.has_changes() and email_matches_blocked_fixture_taxonomy(obj.email):
                violations.append(("HRContact(update email)", str(obj.email)))

    return violations


def _before_flush(session: Session, flush_context, instances) -> None:
    if runtime_allows_synthetic_fixture_emails():
        return
    violations = _collect_violations(session)
    if not violations:
        return
    detail = "; ".join(f"{kind}={addr!r}" for kind, addr in violations)
    logger.error("Blocked synthetic fixture email(s) in non-test runtime: %s", detail)
    raise ValueError(
        "Refusing to persist rows that look like pytest fixture data "
        f"(blocked fixture taxonomy). {detail}"
    )


def install_fixture_email_guard() -> None:
    global _guard_installed
    if _guard_installed:
        return
    event.listen(Session, "before_flush", _before_flush)
    _guard_installed = True
