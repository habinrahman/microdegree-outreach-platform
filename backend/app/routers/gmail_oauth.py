"""Gmail OAuth connect flow for students (Part 3 hardening / usability).

Flow:
- GET /oauth/gmail/start?student_id=...  -> returns auth_url
- GET /oauth/gmail/callback?state=...&code=... -> stores refresh token, redirects to UI
"""

import logging
import os
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import require_api_key
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from google_auth_oauthlib.flow import Flow

from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from app.database import get_db
from app.models import Student
from app.services.audit import log_event
from app.services.oauth_state import sign_oauth_student_id, verify_oauth_student_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth/gmail", tags=["gmail_oauth"])
auth_router = APIRouter(tags=["gmail_oauth"])


SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Note: PKCE verifier is persisted on the Student row as `oauth_code_verifier`,
# so the callback can always use it.


def _redirect_uri(request: Request) -> str:
    # callback must be registered in Google Console; this keeps it correct for dev/prod host
    return str(request.url_for("gmail_oauth_callback"))


def _frontend_redirect_base() -> str:
    # Where to send user after OAuth success
    return os.getenv("FRONTEND_URL", "http://127.0.0.1:5173")

# Must match the authorized redirect URI in Google Cloud Console for /auth/* flow.
AUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://127.0.0.1:5173/auth/callback")


def _oauth_web_client_config() -> dict:
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


@router.get("/start", dependencies=[Depends(require_api_key)])
def gmail_oauth_start(student_id: UUID, request: Request, db: Session = Depends(get_db)):
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env and restart the backend.",
        )

    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        redirect_uri=_redirect_uri(request),
    )
    signed_state = sign_oauth_student_id(student_id)
    auth_url, _flow_state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=signed_state,
    )

    # Persist PKCE code_verifier in DB so callback can use it.
    code_verifier = getattr(flow, "code_verifier", None)
    student.oauth_code_verifier = code_verifier
    flow.code_verifier = code_verifier
    db.commit()

    return {"auth_url": auth_url, "state": signed_state}

@auth_router.get("/google", dependencies=[Depends(require_api_key)])
def auth_google(student_id: UUID, request: Request, db: Session = Depends(get_db)):
    """
    GET /auth/google — starts OAuth with server-side state in the session.
    Requires query param student_id (which student will receive the refresh token).
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env and restart the backend.",
        )

    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    flow = Flow.from_client_config(
        _oauth_web_client_config(),
        scopes=SCOPES,
        redirect_uri=AUTH_REDIRECT_URI,
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )

    request.session["state"] = state
    request.session["oauth_student_id"] = str(student_id)
    code_verifier = getattr(flow, "code_verifier", None)
    if code_verifier:
        request.session["oauth_code_verifier"] = code_verifier
    else:
        request.session.pop("oauth_code_verifier", None)

    return RedirectResponse(auth_url)


@router.get("/callback", name="gmail_oauth_callback")
def gmail_oauth_callback(request: Request, state: str, code: str, db: Session = Depends(get_db)):
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env and restart the backend.",
        )

    try:
        student_id = verify_oauth_student_state(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
        redirect_uri=_redirect_uri(request),
    )

    stored_code_verifier = student.oauth_code_verifier
    if not stored_code_verifier:
        raise HTTPException(status_code=400, detail="PKCE verifier missing")

    try:
        flow.fetch_token(code=code, code_verifier=stored_code_verifier)
    except Exception as e:
        logger.error("Internal server error", exc_info=e)
        raise HTTPException(status_code=400, detail="OAuth token exchange failed")

    creds = flow.credentials

    refresh_token = creds.refresh_token

    if not refresh_token:
        raise HTTPException(status_code=400, detail="No refresh token returned; ensure prompt=consent and access_type=offline")

    student.gmail_refresh_token = refresh_token
    student.gmail_connected = True
    # Clear PKCE verifier after successful token exchange to avoid stale verifiers.
    student.oauth_code_verifier = None
    db.commit()

    log_event(
        db,
        actor="user",
        action="oauth_connected",
        entity_type="Student",
        entity_id=str(student.id),
        meta={"gmail_address": student.gmail_address},
    )

    return RedirectResponse(f"{_frontend_redirect_base()}/students?gmail_connected=1")

@auth_router.get("/callback", name="auth_callback")
def auth_callback(request: Request, state: str, code: str, db: Session = Depends(get_db)):
    """
    GET /auth/callback — validates OAuth state against session, exchanges code for tokens.
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env and restart the backend.",
        )

    expected = request.session.get("state")
    if state != expected:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    student_id_raw = request.session.get("oauth_student_id")
    if not student_id_raw:
        raise HTTPException(status_code=400, detail="OAuth session missing student_id")
    try:
        student_id = UUID(student_id_raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid student in session")

    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    flow = Flow.from_client_config(
        _oauth_web_client_config(),
        scopes=SCOPES,
        redirect_uri=AUTH_REDIRECT_URI,
    )

    code_verifier = request.session.get("oauth_code_verifier")
    try:
        if code_verifier:
            flow.fetch_token(code=code, code_verifier=code_verifier)
        else:
            flow.fetch_token(code=code)
    except Exception as e:
        logger.error("Internal server error", exc_info=e)
        raise HTTPException(status_code=400, detail="OAuth token exchange failed")

    credentials = flow.credentials
    refresh_token = credentials.refresh_token
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No refresh token returned; ensure prompt=consent and access_type=offline")

    student.gmail_refresh_token = refresh_token
    student.gmail_connected = True
    student.oauth_code_verifier = None
    db.commit()

    request.session.pop("state", None)
    request.session.pop("oauth_student_id", None)
    request.session.pop("oauth_code_verifier", None)

    log_event(
        db,
        actor="user",
        action="oauth_connected",
        entity_type="Student",
        entity_id=str(student.id),
        meta={"gmail_address": student.gmail_address},
    )

    return RedirectResponse(f"{_frontend_redirect_base()}/students?gmail_connected=1")

