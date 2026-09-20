import uuid

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    JSON,
    String,
    Text,
    func,
)

from sqlalchemy.dialects.postgresql import UUID

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from services.api.app.db.base import Base


class AuditEvent(Base):

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # -----------------------------------------------------
    # WHO
    # -----------------------------------------------------

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam_users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    # -----------------------------------------------------
    # SECURITY / BUSINESS SCOPE
    # -----------------------------------------------------

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "tenants.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    publisher_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "publishers.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    # -----------------------------------------------------
    # WHAT HAPPENED
    # Examples:
    # application.deploy
    # application.upgrade
    # application.rollback
    # application.stop
    # application.restart
    # subscription.suspend
    # -----------------------------------------------------

    action: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        index=True,
    )

    # -----------------------------------------------------
    # TARGET RESOURCE
    # -----------------------------------------------------

    resource_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    # String instead of UUID deliberately.
    # Future resources may not always use UUID identifiers.

    resource_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        index=True,
    )

    # -----------------------------------------------------
    # RESULT
    # success / denied / failed
    # -----------------------------------------------------

    outcome: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="success",
        index=True,
    )

    message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # -----------------------------------------------------
    # STRUCTURED CONTEXT
    # -----------------------------------------------------

    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # Future HTTP request correlation.

    request_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )