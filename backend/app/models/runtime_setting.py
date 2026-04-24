"""Operator-persisted key/value settings (feature flags, toggles)."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text

from app.database.config import Base, UuidType
from app.utils.datetime_utils import utc_now


class RuntimeSetting(Base):
    __tablename__ = "runtime_settings"

    id = Column(UuidType(), primary_key=True, default=uuid.uuid4)
    key = Column(String(128), nullable=False, unique=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
