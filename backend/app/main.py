"""
MicroDegree HR Outreach Automation - ASGI application.

Run from the `backend/` directory:
  uvicorn app.main:app --reload --port 8010

Backward-compatible:
  uvicorn main:app --reload  (root `main.py` re-exports `app`)
"""
import app.config  # noqa: F401 — load dotenv (repo + backend .env) before DATABASE_URL / engine

import logging
import os
import asyncio
import re
import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi import WebSocket
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.exc import OperationalError
from app.routers import students, hr, assignments, outreach, responses, campaigns
from app.routers import hrs_legacy, analytics, notifications, interviews
from app.routers import campaign_manager, replies, outreach as outreach_router
from app.routers import campaigns_admin
from app.routers import audit
from app.routers import backups_admin
from app.routers import reliability_admin
from app.routers import health
from app.routers import debug as debug_router
from app.routers import hr_contacts_compat
from app.routers import gmail_oauth, blocked_hr
from app.routers import followups
from app.routers import priority_queue as priority_queue_router
from app.routes.notifications import router as notification_router
from app.services.campaign_scheduler import start_scheduler, shutdown_scheduler
from app.database import get_db
from app.routers.outreach import SendOutreachBody, resolve_outreach_hr_id
from app.services.outreach_service import send_one
from app.services.log_stream import websocket_logs as logs_ws, set_main_loop
from app.services.deprecation_guard import assert_no_deprecated_legacy_log_usage
from app.auth import _admin_key_configured, is_production_runtime, require_api_key

logger = logging.getLogger(__name__)


def _enforce_production_secrets() -> None:
    """Fail fast in production: no DATABASE_URL / session / admin key fallbacks."""
    if not is_production_runtime():
        return
    missing: list[str] = []
    if not (os.getenv("DATABASE_URL") or "").strip():
        missing.append("DATABASE_URL")
    if not (os.getenv("SESSION_SECRET_KEY") or "").strip():
        missing.append("SESSION_SECRET_KEY")
    if not (os.getenv("ADMIN_API_KEY") or "").strip():
        missing.append("ADMIN_API_KEY")
    if missing:
        raise RuntimeError(
            "Production requires non-empty environment variables (no dev fallbacks): "
            + ", ".join(missing)
            + ". For local development set APP_ENV=dev (or development/local)."
        )


_enforce_production_secrets()

# Single source of truth: middleware and the global exception handler must use the same allowlist
# so 500 responses still include Access-Control-Allow-Origin (browsers hide the body otherwise).
_cors_origins_env = (os.getenv("CORS_ALLOW_ORIGINS") or "").strip()
if _cors_origins_env:
    # Comma-separated list of exact origins. Example:
    # CORS_ALLOW_ORIGINS=https://dashboard.example.com,https://admin.example.com
    CORS_ALLOW_ORIGINS = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
else:
    # Dev defaults (exact origins). Prefer env in prod.
    CORS_ALLOW_ORIGINS = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]

_cors_origin_regex_raw = (os.getenv("CORS_ALLOW_ORIGIN_REGEX") or "").strip()
_cors_origin_regex = re.compile(_cors_origin_regex_raw) if _cors_origin_regex_raw else None


def _apply_cors_to_response(request: Request, response: JSONResponse) -> JSONResponse:
    """Mirror CORSMiddleware headers so browsers still see allowed origin on 500s and odd paths."""
    origin = request.headers.get("origin")
    if origin and (origin in CORS_ALLOW_ORIGINS or (_cors_origin_regex and _cors_origin_regex.match(origin))):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


# Structured logs: correlation id on every record (see observability.logging_setup)
from app.observability.logging_setup import configure_root_logging

configure_root_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Single startup path: lightweight DB init (no runtime DDL), then start APScheduler.
    """
    if os.getenv("LEGACY_LOG_DEPRECATION_CHECK", "").strip().lower() in ("1", "true", "yes"):
        assert_no_deprecated_legacy_log_usage()

    set_main_loop(asyncio.get_running_loop())

    env_name = (os.getenv("APP_ENV") or os.getenv("ENV") or os.getenv("ENVIRONMENT") or "dev").strip().lower()
    is_dev = env_name in ("dev", "development", "local")  # keep in sync with auth.is_production_runtime()
    port_env = (os.getenv("PORT") or "").strip()
    if not port_env and not is_dev:
        logger.warning("PORT is not set (non-dev). Ensure your process manager exposes the listening port.")
    if not is_dev:
        if not (os.getenv("CORS_ALLOW_ORIGINS") or "").strip() and not (os.getenv("CORS_ALLOW_ORIGIN_REGEX") or "").strip():
            logger.warning("CORS is not configured (non-dev). Set CORS_ALLOW_ORIGINS or CORS_ALLOW_ORIGIN_REGEX.")
        if not (os.getenv("FRONTEND_URL") or "").strip():
            logger.warning("FRONTEND_URL is not set (non-dev). OAuth redirects may be brittle.")

    if os.getenv("ALEMBIC_UPGRADE_ON_START", "").strip().lower() in ("1", "true", "yes"):
        try:
            from app.database.alembic_upgrade import run_alembic_upgrade_head

            await asyncio.to_thread(run_alembic_upgrade_head)
            logger.info("Alembic upgrade head completed.")
        except Exception as e:
            logger.warning("Alembic upgrade on startup failed (continuing): %s", e)

    try:
        from app.database import init_db

        await asyncio.to_thread(init_db)
    except Exception as e:
        # Log and continue: init_db itself treats OperationalError as soft-failure; other errors still surface per-route.
        logger.exception("Database initialization failed: %s", e)

    try:
        if os.getenv("DISABLE_SCHEDULER", "").strip().lower() in ("1", "true", "yes"):
            logger.warning("Scheduler disabled by DISABLE_SCHEDULER=1")
        else:
            start_scheduler()
    except Exception as e:
        logger.warning("Campaign scheduler not started: %s", e)

    yield

    try:
        shutdown_scheduler()
    except Exception as e:
        logger.warning("Campaign scheduler shutdown failed: %s", e)


app = FastAPI(
    title="MicroDegree HR Outreach API",
    description="Internal placement outreach automation (Part 1 - no email sending)",
    lifespan=lifespan,
)


@app.middleware("http")
async def wait_for_db(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    from app.observability.context import reset_correlation_id, set_correlation_id
    from app.services.observability_metrics import record_http_request

    cid = (request.headers.get("x-correlation-id") or request.headers.get("x-request-id") or "").strip()
    if not cid:
        cid = str(uuid.uuid4())
    token = set_correlation_id(cid)
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        record_http_request(request.method, response.status_code, (time.perf_counter() - t0) * 1000.0)
        return response
    finally:
        reset_correlation_id(token)


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_origin_regex=_cors_origin_regex_raw or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OAuth /auth/* routes use request.session (gmail_oauth.auth_router).
# Production: SESSION_SECRET_KEY is enforced by _enforce_production_secrets() above.
_session_secret = (os.getenv("SESSION_SECRET_KEY") or "").strip() or "dev-only-insecure-session-key-minimum-32-chars!!"
app.add_middleware(SessionMiddleware, secret_key=_session_secret, same_site="lax")


@app.exception_handler(OperationalError)
async def database_operational_error_handler(request: Request, exc: OperationalError):
    """Pooler timeouts / dropped connections → 503 instead of generic 500."""
    logger.error("Internal server error", exc_info=exc)
    resp = JSONResponse(
        status_code=503,
        content={"detail": "Database temporarily unavailable"},
    )
    return _apply_cors_to_response(request, resp)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Return 500 as JSON; attach CORS when Origin matches (same rules as CORSMiddleware)."""
    logger.error("Internal server error", exc_info=exc)
    resp = JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
    return _apply_cors_to_response(request, resp)


# API key (ADMIN_API_KEY + X-API-Key / X-Admin-Key) enforced on students, outreach, campaigns, replies routers
# and on /oauth/gmail/start + /auth/google. Leave ADMIN_API_KEY unset for fully open local dev.
app.include_router(students.router)
app.include_router(hr.router, prefix="/hr")
app.include_router(hrs_legacy.router)
app.include_router(assignments.router)
app.include_router(outreach.router)
app.include_router(responses.router)
app.include_router(campaigns.router)
app.include_router(campaign_manager.router)
app.include_router(replies.router)
app.include_router(analytics.router)
app.include_router(notifications.router)
app.include_router(interviews.router)
app.include_router(audit.router)
app.include_router(backups_admin.router)
app.include_router(reliability_admin.router)
app.include_router(campaigns_admin.router)
app.include_router(health.router)
if os.getenv("DEBUG", "").strip().lower() in ("1", "true", "yes"):
    app.include_router(debug_router.router)
app.include_router(hr_contacts_compat.router)
app.include_router(gmail_oauth.router)
app.include_router(gmail_oauth.auth_router)
app.include_router(blocked_hr.router)
app.include_router(followups.router)
app.include_router(priority_queue_router.router)
app.include_router(notification_router)


@app.get("/")
def root():
    return {"message": "MicroDegree HR Outreach API", "docs": "/docs"}


@app.get("/scheduler/status")
def scheduler_status_root():
    """Alias for GET /health/scheduler/status (dashboard spec)."""
    return health.scheduler_status()


@app.get("/email-logs")
def email_logs_alias(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    include_demo: bool = False,
    _auth: bool = Depends(require_api_key),
):
    """Alias for GET /outreach/logs (dashboard compatibility)."""
    return outreach_router.get_logs(db=db, skip=skip, limit=limit, include_demo=include_demo)


@app.post("/followup1/send")
def followup1_send_alias(
    body: SendOutreachBody,
    db: Session = Depends(get_db),
    _auth: bool = Depends(require_api_key),
):
    """Alias for POST /outreach/send (sends next due campaign for the pair)."""
    hr_uuid = resolve_outreach_hr_id(db, body)
    result = send_one(
        db,
        body.student_id,
        hr_uuid,
        template_label=body.template_label,
        subject=body.subject,
        body=body.body,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message", "Send failed"))
    return {"message": "Email sent successfully"}


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    expected = _admin_key_configured()
    if is_production_runtime():
        if not expected:
            await websocket.close(code=1008)
            return
        token = (websocket.query_params.get("api_key") or "").strip()
        if token != expected:
            await websocket.close(code=1008)
            return
    elif expected:
        token = (websocket.query_params.get("api_key") or "").strip()
        if token != expected:
            await websocket.close(code=1008)
            return
    await logs_ws(websocket)
