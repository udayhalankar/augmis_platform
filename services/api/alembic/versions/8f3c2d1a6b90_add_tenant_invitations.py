"""add tenant invitations

Revision ID: 8f3c2d1a6b90
Revises: 79b7599334bc
Create Date: 2026-09-30

"""

from typing import (
    Sequence,
    Union,
)

from alembic import op
import sqlalchemy as sa


revision: str = (
    "8f3c2d1a6b90"
)

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "79b7599334bc"

branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None

depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


def upgrade() -> None:

    op.create_table(
        "tenant_invitations",

        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "tenant_id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "email",
            sa.String(
                length=320
            ),
            nullable=False,
        ),

        sa.Column(
            "email_normalized",
            sa.String(
                length=320
            ),
            nullable=False,
        ),

        sa.Column(
            "token_hash",
            sa.String(
                length=64
            ),
            nullable=False,
        ),

        sa.Column(
            "status",
            sa.String(
                length=30
            ),
            nullable=False,
        ),

        sa.Column(
            "invited_by_user_id",
            sa.UUID(),
            nullable=True,
        ),

        sa.Column(
            "accepted_by_user_id",
            sa.UUID(),
            nullable=True,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(
                timezone=True
            ),
            server_default=(
                sa.text(
                    "now()"
                )
            ),
            nullable=False,
        ),

        sa.Column(
            "expires_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=False,
        ),

        sa.Column(
            "accepted_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=True,
        ),

        sa.Column(
            "revoked_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=True,
        ),

        sa.ForeignKeyConstraint(
            [
                "tenant_id"
            ],
            [
                "tenants.id"
            ],
            ondelete="CASCADE",
        ),

        sa.ForeignKeyConstraint(
            [
                "invited_by_user_id"
            ],
            [
                "iam_users.id"
            ],
            ondelete="SET NULL",
        ),

        sa.ForeignKeyConstraint(
            [
                "accepted_by_user_id"
            ],
            [
                "iam_users.id"
            ],
            ondelete="SET NULL",
        ),

        sa.PrimaryKeyConstraint(
            "id"
        ),
    )

    op.create_index(
        "ix_tenant_invitations_tenant_id",
        "tenant_invitations",
        [
            "tenant_id"
        ],
        unique=False,
    )

    op.create_index(
        "ix_tenant_invitations_email_normalized",
        "tenant_invitations",
        [
            "email_normalized"
        ],
        unique=False,
    )

    op.create_index(
        "ix_tenant_invitations_status",
        "tenant_invitations",
        [
            "status"
        ],
        unique=False,
    )

    op.create_index(
        "ix_tenant_invitations_token_hash",
        "tenant_invitations",
        [
            "token_hash"
        ],
        unique=True,
    )

    op.create_index(
        "uq_tenant_invitations_pending_email",
        "tenant_invitations",
        [
            "tenant_id",
            "email_normalized",
        ],
        unique=True,
        postgresql_where=(
            sa.text(
                "status = 'pending'"
            )
        ),
    )

    op.create_table(
        "tenant_invitation_roles",

        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "invitation_id",
            sa.UUID(),
            nullable=False,
        ),

        sa.Column(
            "role_id",
            sa.UUID(),
            nullable=False,
        ),

        sa.ForeignKeyConstraint(
            [
                "invitation_id"
            ],
            [
                "tenant_invitations.id"
            ],
            ondelete="CASCADE",
        ),

        sa.ForeignKeyConstraint(
            [
                "role_id"
            ],
            [
                "iam_roles.id"
            ],
            ondelete="CASCADE",
        ),

        sa.PrimaryKeyConstraint(
            "id"
        ),

        sa.UniqueConstraint(
            "invitation_id",
            "role_id",
            name=(
                "uq_tenant_invitation_role"
            ),
        ),
    )

    op.create_index(
        "ix_tenant_invitation_roles_invitation_id",
        "tenant_invitation_roles",
        [
            "invitation_id"
        ],
        unique=False,
    )


def downgrade() -> None:

    op.drop_index(
        "ix_tenant_invitation_roles_invitation_id",
        table_name=(
            "tenant_invitation_roles"
        ),
    )

    op.drop_table(
        "tenant_invitation_roles"
    )

    op.drop_index(
        "uq_tenant_invitations_pending_email",
        table_name=(
            "tenant_invitations"
        ),
    )

    op.drop_index(
        "ix_tenant_invitations_token_hash",
        table_name=(
            "tenant_invitations"
        ),
    )

    op.drop_index(
        "ix_tenant_invitations_status",
        table_name=(
            "tenant_invitations"
        ),
    )

    op.drop_index(
        "ix_tenant_invitations_email_normalized",
        table_name=(
            "tenant_invitations"
        ),
    )

    op.drop_index(
        "ix_tenant_invitations_tenant_id",
        table_name=(
            "tenant_invitations"
        ),
    )

    op.drop_table(
        "tenant_invitations"
    )
