"""
Backward-compatible ASGI entry when running from `backend/`:

    uvicorn main:app --reload --port 8000

Canonical entry (recommended):

    uvicorn app.main:app --reload --port 8000
"""
from app.main import app

__all__ = ["app"]
