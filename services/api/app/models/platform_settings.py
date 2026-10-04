# services/api/app/models/platform_settings.py
from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from services.api.app.db.base import Base


class PlatformEmailSettings(Base):
    __tablename__ = "platform_email_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    provider: Mapped[str] = mapped_column(
        String(30), nullable=False, default="custom"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    host: Mapped[str] = mapped_column(
        String(255), nullable=False, default=""
    )
    port: Mapped[int] = mapped_column(
        Integer, nullable=False, default=587
    )
    username: Mapped[str] = mapped_column(
        String(320), nullable=False, default=""
    )
    credential_ciphertext: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    from_email: Mapped[str] = mapped_column(
        String(320), nullable=False, default=""
    )
    from_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default="AUGMIS"
    )
    use_starttls: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    use_ssl: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("iam_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
