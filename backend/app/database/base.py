"""Declarative Base re-export — single metadata registry for Alembic and models."""
from app.database.config import Base

__all__ = ["Base"]
