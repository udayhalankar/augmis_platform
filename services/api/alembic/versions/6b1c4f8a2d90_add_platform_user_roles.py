"""add platform user roles

Revision ID: 6b1c4f8a2d90
Revises: 3c4d1e2f7a90
Create Date: 2026-10-03

"""

from typing import (
    Sequence,
    Union,
)

from alembic import op
import sqlalchemy as sa

from sqlalchemy.dialects import (
    postgresql,
)


revision: str = (
    "6b1c4f8a2d90"
)

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "3c4d1e2f7a90"

branch_labels = None
depends_on = None


def upgrade() -> None:

    op.create_table(
        "platform_user_roles",

        sa.Column(
            "id",
            postgresql.UUID(
                as_uuid=True
            ),
            nullable=False,
        ),

        sa.Column(
            "user_id",
            postgresql.UUID(
                as_uuid=True
            ),
            nullable=False,
        ),

        sa.Column(
            "role_id",
            postgresql.UUID(
                as_uuid=True
            ),
            nullable=False,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=False,
            server_default=(
                sa.func.now()
            ),
        ),

        sa.ForeignKeyConstraint(
            ["user_id"],
            ["iam_users.id"],
            ondelete="CASCADE",
        ),

        sa.ForeignKeyConstraint(
            ["role_id"],
            ["iam_roles.id"],
            ondelete="CASCADE",
        ),

        sa.PrimaryKeyConstraint(
            "id"
        ),

        sa.UniqueConstraint(
            "user_id",
            "role_id",
            name=(
                "uq_platform_user_role"
            ),
        ),
    )

    op.create_index(
        "ix_platform_user_roles_user_id",
        "platform_user_roles",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        "ix_platform_user_roles_role_id",
        "platform_user_roles",
        ["role_id"],
        unique=False,
    )


def downgrade() -> None:

    op.drop_index(
        "ix_platform_user_roles_role_id",
        table_name=(
            "platform_user_roles"
        ),
    )

    op.drop_index(
        "ix_platform_user_roles_user_id",
        table_name=(
            "platform_user_roles"
        ),
    )

    op.drop_table(
        "platform_user_roles"
    )