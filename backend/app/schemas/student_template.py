"""Student template schemas (CRUD only)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator

TemplateType = Literal["INITIAL", "FOLLOWUP_1", "FOLLOWUP_2", "FOLLOWUP_3"]


class StudentTemplateIn(BaseModel):
    subject: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1, max_length=10000)

    @field_validator("subject", "body")
    @classmethod
    def _strip_and_reject_whitespace_only(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("Must not be empty")
        return s


class StudentTemplateUpsert(StudentTemplateIn):
    """Upsert payload with optional optimistic concurrency token."""

    if_match: Optional[str] = Field(
        None,
        description="ISO timestamp (updated_at or created_at) from the last GET; prevents stale overwrites",
        max_length=64,
    )


class StudentTemplateOut(StudentTemplateIn):
    model_config = ConfigDict(from_attributes=True)
    template_type: TemplateType
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class StudentTemplateBundle(BaseModel):
    """Bundle keyed by canonical template type; missing entries are treated as 'no template'."""

    INITIAL: Optional[StudentTemplateOut] = None
    FOLLOWUP_1: Optional[StudentTemplateOut] = None
    FOLLOWUP_2: Optional[StudentTemplateOut] = None
    FOLLOWUP_3: Optional[StudentTemplateOut] = None


class StudentTemplateBundleUpdate(BaseModel):
    """Upsert payload. Any provided key is applied; omitted keys are untouched.

    - Set value to null to delete that template row (optional convenience).
    """

    INITIAL: Optional[StudentTemplateUpsert] | None = None
    FOLLOWUP_1: Optional[StudentTemplateUpsert] | None = None
    FOLLOWUP_2: Optional[StudentTemplateUpsert] | None = None
    FOLLOWUP_3: Optional[StudentTemplateUpsert] | None = None

