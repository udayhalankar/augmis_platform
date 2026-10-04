"""add platform email settings

Revision ID: e7a4b2c91d30
Revises: 6b1c4f8a2d90
Create Date: 2026-10-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e7a4b2c91d30"
down_revision: Union[str, Sequence[str], None] = "6b1c4f8a2d90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_email_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=320), nullable=False),
        sa.Column("credential_ciphertext", sa.Text(), nullable=True),
        sa.Column("from_email", sa.String(length=320), nullable=False),
        sa.Column("from_name", sa.String(length=200), nullable=False),
        sa.Column("use_starttls", sa.Boolean(), nullable=False),
        sa.Column("use_ssl", sa.Boolean(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["iam_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_platform_email_settings_updated_by_user_id",
        "platform_email_settings",
        ["updated_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_platform_email_settings_updated_by_user_id",
        table_name="platform_email_settings",
    )
    op.drop_table("platform_email_settings")
