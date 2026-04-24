"""Simple admin authentication (basic for now)."""
import os
from fastapi import Header, HTTPException
from dotenv import load_dotenv

load_dotenv()

_PRODUCTION_EXCLUDED_ENVS = frozenset({"dev", "development", "local", "test", "testing", "ci"})


def is_production_runtime() -> bool:
    """True when APP_ENV/ENV/ENVIRONMENT is set to a non-local value (e.g. production, staging)."""
    env_name = (os.getenv("APP_ENV") or os.getenv("ENV") or os.getenv("ENVIRONMENT") or "dev").strip().lower()
    return env_name not in _PRODUCTION_EXCLUDED_ENVS


def _admin_key_configured() -> str | None:
    """Non-empty ADMIN_API_KEY from env, or None if unset/blank (open API for local dev)."""
    v = (os.getenv("ADMIN_API_KEY") or "").strip()
    return v if v else None


# Resolved key for callers that need the string (may be empty)
ADMIN_API_KEY = _admin_key_configured() or ""


def require_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
):
    """Require X-API-Key or X-Admin-Key when ADMIN_API_KEY is set (non-empty)."""
    expected = _admin_key_configured()
    if not expected:
        return True
    sent = (x_api_key or x_admin_key or "").strip()
    if sent != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
    return True


def require_admin(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
):
    """Dependency: require ADMIN_API_KEY in X-Admin-Key or X-API-Key (same secret as operator key)."""
    expected = _admin_key_configured()
    if not expected:
        return
    sent = (x_api_key or x_admin_key or "").strip()
    if sent != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing admin key")
    return True
