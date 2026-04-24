"""Attach correlation_id to LogRecord for structured operator logs."""
from __future__ import annotations

import logging
import os

from app.observability.context import get_correlation_id


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id() or "-"
        return True


class CorrelationFormatter(logging.Formatter):
    """Ensures %(correlation_id)s is always defined before formatting."""

    def format(self, record: logging.LogRecord) -> str:
        if not getattr(record, "correlation_id", None):
            record.correlation_id = get_correlation_id() or "-"
        return super().format(record)


_configured = False


def configure_root_logging() -> None:
    """Single root StreamHandler with correlation-aware formatter (replaces basicConfig)."""
    global _configured
    if _configured:
        return
    if os.getenv("PYTEST_RUNNING", "").strip() == "1":
        # Preserve pytest log capture; correlation still works where handlers exist.
        _configured = True
        return
    _configured = True
    level = (os.getenv("LOG_LEVEL", "INFO") or "INFO").upper()
    root = logging.getLogger()
    root.handlers.clear()
    h = logging.StreamHandler()
    h.addFilter(CorrelationIdFilter())
    h.setFormatter(
        CorrelationFormatter(
            "%(asctime)s %(levelname)s %(name)s [cid=%(correlation_id)s] %(message)s"
        )
    )
    root.addHandler(h)
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).setLevel(level)


def install_correlation_logging() -> None:
    """Backward-compatible alias: configure root logging once."""
    configure_root_logging()
