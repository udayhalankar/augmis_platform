"""add real email delivery tracking

Revision ID: f2a7c4d91e60
Revises: e7a4b2c91d30
Create Date: 2026-10-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f2a7c4d91e60"
down_revision: Union[str, Sequence[str], None] = (
    "e7a4b2c91d30"
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_invitations",
        sa.Column(
            "delivery_message_id",
            sa.String(length=320),
            nullable=True,
        ),
    )

    op.add_column(
        "tenant_invitations",
        sa.Column(
            "provider_message_id",
            sa.String(length=120),
            nullable=True,
        ),
    )

    op.add_column(
        "tenant_invitations",
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "tenant_invitations",
        sa.Column(
            "last_delivery_event_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_tenant_invitations_delivery_message_id",
        "tenant_invitations",
        ["delivery_message_id"],
        unique=True,
    )

    op.create_index(
        "ix_tenant_invitations_provider_message_id",
        "tenant_invitations",
        ["provider_message_id"],
        unique=False,
    )

    op.create_table(
        "email_delivery_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "provider",
            sa.String(length=30),
            nullable=False,
        ),
        sa.Column(
            "external_event_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "event_type",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "invitation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "message_id",
            sa.String(length=320),
            nullable=True,
        ),
        sa.Column(
            "provider_message_id",
            sa.String(length=120),
            nullable=True,
        ),
        sa.Column(
            "recipient",
            sa.String(length=320),
            nullable=True,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"],
            ["tenant_invitations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "external_event_id",
        ),
    )

    op.create_index(
        "ix_email_delivery_events_external_event_id",
        "email_delivery_events",
        ["external_event_id"],
        unique=True,
    )

    op.create_index(
        "ix_email_delivery_events_event_type",
        "email_delivery_events",
        ["event_type"],
        unique=False,
    )

    op.create_index(
        "ix_email_delivery_events_invitation_id",
        "email_delivery_events",
        ["invitation_id"],
        unique=False,
    )

    op.create_index(
        "ix_email_delivery_events_tenant_id",
        "email_delivery_events",
        ["tenant_id"],
        unique=False,
    )

    op.create_index(
        "ix_email_delivery_events_message_id",
        "email_delivery_events",
        ["message_id"],
        unique=False,
    )

    op.create_index(
        "ix_email_delivery_events_provider_message_id",
        "email_delivery_events",
        ["provider_message_id"],
        unique=False,
    )

    op.create_index(
        "ix_email_delivery_events_invitation_occurred",
        "email_delivery_events",
        [
            "invitation_id",
            "occurred_at",
        ],
        unique=False,
    )

    op.create_index(
        "ix_email_delivery_events_provider_message",
        "email_delivery_events",
        [
            "provider",
            "provider_message_id",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_delivery_events_provider_message",
        table_name="email_delivery_events",
    )
    op.drop_index(
        "ix_email_delivery_events_invitation_occurred",
        table_name="email_delivery_events",
    )
    op.drop_index(
        "ix_email_delivery_events_provider_message_id",
        table_name="email_delivery_events",
    )
    op.drop_index(
        "ix_email_delivery_events_message_id",
        table_name="email_delivery_events",
    )
    op.drop_index(
        "ix_email_delivery_events_tenant_id",
        table_name="email_delivery_events",
    )
    op.drop_index(
        "ix_email_delivery_events_invitation_id",
        table_name="email_delivery_events",
    )
    op.drop_index(
        "ix_email_delivery_events_event_type",
        table_name="email_delivery_events",
    )
    op.drop_index(
        "ix_email_delivery_events_external_event_id",
        table_name="email_delivery_events",
    )
    op.drop_table(
        "email_delivery_events"
    )

    op.drop_index(
        "ix_tenant_invitations_provider_message_id",
        table_name="tenant_invitations",
    )
    op.drop_index(
        "ix_tenant_invitations_delivery_message_id",
        table_name="tenant_invitations",
    )

    op.drop_column(
        "tenant_invitations",
        "last_delivery_event_at",
    )
    op.drop_column(
        "tenant_invitations",
        "delivered_at",
    )
    op.drop_column(
        "tenant_invitations",
        "provider_message_id",
    )
    op.drop_column(
        "tenant_invitations",
        "delivery_message_id",
    )
