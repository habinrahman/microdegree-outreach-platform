"""Debug endpoints for DB verification (development / operations)."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db

router = APIRouter(prefix="/debug", tags=["debug"], dependencies=[Depends(require_api_key)])


@router.get("/db-columns")
def debug_db_columns(db: Session = Depends(get_db)):
    """List column_name for public.email_campaigns (same as information_schema query)."""
    result = db.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'email_campaigns'
            ORDER BY ordinal_position
            """
        )
    )
    rows = [{"column_name": row[0]} for row in result]
    return {"table": "email_campaigns", "columns": rows}


@router.get("/db-name")
def debug_db_name(db: Session = Depends(get_db)):
    """Current database name."""
    row = db.execute(text("SELECT current_database()")).one()
    return {"current_database": row[0]}
