"""add invitation delivery tracking

Revision ID: 3c4d1e2f7a90
Revises: 8f3c2d1a6b90
Create Date: 2026-10-03

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3c4d1e2f7a90"

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "8f3c2d1a6b90"

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

    op.add_column(
        "tenant_invitations",
        sa.Column(
            "delivery_status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text(
                "'not_attempted'"
            ),
        ),
    )

    op.add_column(
        "tenant_invitations",
        sa.Column(
            "delivery_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text(
                "0"
            ),
        ),
    )

    op.add_column(
        "tenant_invitations",
        sa.Column(
            "last_sent_at",
            sa.DateTime(
                timezone=True
            ),
            nullable=True,
        ),
    )

    op.add_column(
        "tenant_invitations",
        sa.Column(
            "last_delivery_error",
            sa.String(
                length=1000
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:

    op.drop_column(
        "tenant_invitations",
        "last_delivery_error",
    )

    op.drop_column(
        "tenant_invitations",
        "last_sent_at",
    )

    op.drop_column(
        "tenant_invitations",
        "delivery_attempts",
    )

    op.drop_column(
        "tenant_invitations",
        "delivery_status",
    )