"""Signed OAuth state so callbacks cannot bind arbitrary student_id values.

Payload includes a random nonce so state tokens are high-entropy and not predictable
from student_id alone. Full ownership binding still needs a logged-in user model (future).
"""

from __future__ import annotations

import os
import secrets
from uuid import UUID

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


def _serializer() -> URLSafeTimedSerializer:
    secret = (os.getenv("SESSION_SECRET_KEY") or os.getenv("ADMIN_API_KEY") or "").strip()
    if not secret:
        from app.auth import is_production_runtime

        if is_production_runtime():
            raise RuntimeError(
                "SESSION_SECRET_KEY or ADMIN_API_KEY must be set for Gmail OAuth state signing in production."
            )
        secret = "dev-only-oauth-state-signing-change-in-production"
    return URLSafeTimedSerializer(secret, salt="gmail-oauth-student-v1")


def sign_oauth_student_id(student_id: UUID) -> str:
    """Opaque state string passed to Google and echoed to our callback."""
    nonce = secrets.token_urlsafe(24)
    return _serializer().dumps({"sid": str(student_id), "n": nonce})


def verify_oauth_student_state(token: str, max_age: int = 3600) -> UUID:
    """Recover student UUID or raise ValueError."""
    try:
        data = _serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired) as e:
        raise ValueError("invalid oauth state") from e
    sid = data.get("sid")
    n = data.get("n")
    if not sid:
        raise ValueError("missing sid")
    if not n or not isinstance(n, str) or len(n) < 16:
        raise ValueError("missing or weak nonce")
    return UUID(str(sid))
