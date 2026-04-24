"""Correlation ID propagation (HTTP → logs → optional audit meta)."""
from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def set_correlation_id(value: str) -> Token[str | None]:
    return _correlation_id.set((value or "").strip() or str(uuid.uuid4()))


def reset_correlation_id(token: Token[str | None]) -> None:
    _correlation_id.reset(token)
