import os
import time
from typing import Any

import bcrypt
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


def _admin_username() -> str:
    return (os.getenv("ADMIN_USERNAME") or "").strip()


def _admin_password_hash() -> str:
    return (os.getenv("ADMIN_PASSWORD_HASH") or "").strip()


def _is_logged_in(request: Request) -> bool:
    return bool(request.session.get("admin_logged_in") is True)


@router.post("/login")
def login(body: LoginBody, request: Request) -> dict[str, Any]:
    expected_user = _admin_username()
    expected_hash = _admin_password_hash()
    if not expected_user or not expected_hash:
        raise HTTPException(status_code=500, detail="Server auth is not configured")

    user_ok = body.username.strip() == expected_user
    try:
        pw_ok = bcrypt.checkpw(body.password.encode("utf-8"), expected_hash.encode("utf-8"))
    except Exception:
        pw_ok = False

    if not (user_ok and pw_ok):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    request.session.clear()
    request.session["admin_logged_in"] = True
    request.session["admin_username"] = expected_user
    request.session["login_at"] = int(time.time())
    return {"ok": True, "username": expected_user}


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    if not _is_logged_in(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {
        "ok": True,
        "username": str(request.session.get("admin_username") or "admin"),
        "login_at": request.session.get("login_at"),
    }


@router.post("/logout")
def logout(request: Request) -> dict[str, Any]:
    request.session.clear()
    return {"ok": True}

