# services/api/app/models/email_delivery.py
from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from services.api.app.db.base import Base


class EmailDeliveryEvent(Base):
    __tablename__ = "email_delivery_events"

    __table_args__ = (
        Index(
            "ix_email_delivery_events_invitation_occurred",
            "invitation_id",
            "occurred_at",
        ),
        Index(
            "ix_email_delivery_events_provider_message",
            "provider",
            "provider_message_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    provider: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="resend",
    )

    external_event_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "tenant_invitations.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "tenants.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    message_id: Mapped[str | None] = mapped_column(
        String(320),
        nullable=True,
        index=True,
    )

    provider_message_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        index=True,
    )

    recipient: Mapped[str | None] = mapped_column(
        String(320),
        nullable=True,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
