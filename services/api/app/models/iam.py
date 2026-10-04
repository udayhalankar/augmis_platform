import uuid

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Integer,
    UniqueConstraint,
    func,
    text,
)

from sqlalchemy.dialects.postgresql import UUID

from sqlalchemy.orm import (
    Mapped,
    mapped_column
)

from services.api.app.db.base import Base


class User(Base):

    __tablename__ = "iam_users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    email: Mapped[str] = mapped_column(
        String(320),
        nullable=False
    )

    email_normalized: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
        unique=True,
        index=True
    )

    password_hash: Mapped[str] = mapped_column(
        String(500),
        nullable=False
    )

    first_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    last_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="active",
        index=True
    )

    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now()
    )


class Role(Base):

    __tablename__ = "iam_roles"

    __table_args__ = (
        UniqueConstraint(
            "scope_type",
            "code",
            name="uq_iam_role_scope_code"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    scope_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True
    )

    code: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False
    )

    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now()
    )


class Permission(Base):

    __tablename__ = "iam_permissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    code: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        unique=True,
        index=True
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False
    )


class RolePermission(Base):

    __tablename__ = "iam_role_permissions"

    __table_args__ = (
        UniqueConstraint(
            "role_id",
            "permission_id",
            name="uq_iam_role_permission"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam_roles.id",
            ondelete="CASCADE"
        ),
        nullable=False,
        index=True
    )

    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam_permissions.id",
            ondelete="CASCADE"
        ),
        nullable=False,
        index=True
    )

class PlatformUserRole(Base):

    __tablename__ = "platform_user_roles"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "role_id",
            name="uq_platform_user_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam_users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam_roles.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

class TenantMembership(Base):

    __tablename__ = "tenant_memberships"

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            name="uq_tenant_membership"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "tenants.id",
            ondelete="CASCADE"
        ),
        nullable=False,
        index=True
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam_users.id",
            ondelete="CASCADE"
        ),
        nullable=False,
        index=True
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="active"
    )

    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now()
    )


class TenantMembershipRole(Base):

    __tablename__ = "tenant_membership_roles"

    __table_args__ = (
        UniqueConstraint(
            "membership_id",
            "role_id",
            name="uq_tenant_membership_role"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    membership_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "tenant_memberships.id",
            ondelete="CASCADE"
        ),
        nullable=False,
        index=True
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam_roles.id",
            ondelete="CASCADE"
        ),
        nullable=False
    )

class TenantInvitation(Base):

    __tablename__ = (
        "tenant_invitations"
    )

    __table_args__ = (
        Index(
            "uq_tenant_invitations_pending_email",
            "tenant_id",
            "email_normalized",
            unique=True,
            postgresql_where=text(
                "status = 'pending'"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "tenants.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    email: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
    )

    email_normalized: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
        index=True,
    )

    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )

    delivery_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="not_attempted",
    )

    delivery_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    last_sent_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_delivery_error: Mapped[
        str | None
    ] = mapped_column(
        String(1000),
        nullable=True,
    )

    delivery_message_id: Mapped[
        str | None
    ] = mapped_column(
        String(320),
        nullable=True,
        unique=True,
        index=True,
    )

    provider_message_id: Mapped[
        str | None
    ] = mapped_column(
        String(120),
        nullable=True,
        index=True,
    )

    delivered_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_delivery_event_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        index=True,
    )

    invited_by_user_id: Mapped[
        uuid.UUID | None
    ] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam_users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    accepted_by_user_id: Mapped[
        uuid.UUID | None
    ] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam_users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    expires_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    accepted_at: Mapped[
        object | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    revoked_at: Mapped[
        object | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class TenantInvitationRole(Base):

    __tablename__ = (
        "tenant_invitation_roles"
    )

    __table_args__ = (
        UniqueConstraint(
            "invitation_id",
            "role_id",
            name=(
                "uq_tenant_invitation_role"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    invitation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "tenant_invitations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam_roles.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )


class PublisherMembership(Base):

    __tablename__ = "publisher_memberships"

    __table_args__ = (
        UniqueConstraint(
            "publisher_id",
            "user_id",
            name="uq_publisher_membership"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    publisher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "publishers.id",
            ondelete="CASCADE"
        ),
        nullable=False,
        index=True
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam_users.id",
            ondelete="CASCADE"
        ),
        nullable=False,
        index=True
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="active"
    )

    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now()
    )


class PublisherMembershipRole(Base):

    __tablename__ = "publisher_membership_roles"

    __table_args__ = (
        UniqueConstraint(
            "membership_id",
            "role_id",
            name="uq_publisher_membership_role"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    membership_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "publisher_memberships.id",
            ondelete="CASCADE"
        ),
        nullable=False,
        index=True
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "iam_roles.id",
            ondelete="CASCADE"
        ),
        nullable=False
    )