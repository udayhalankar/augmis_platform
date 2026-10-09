"""Enforce one publisher workspace per organization.

Revision ID: 9d3a4c7e1b20
Revises: c8b6a53d29e1

Nullable tenant_id is retained for legacy publisher reconciliation.
PostgreSQL UNIQUE allows multiple NULL values; each assigned tenant has at most one publisher.
"""
from alembic import op
import sqlalchemy as sa

revision = "9d3a4c7e1b20"
down_revision = "c8b6a53d29e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_publishers_single_workspace_per_tenant",
        "publishers",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_publishers_single_workspace_per_tenant",
        "publishers",
        type_="unique",
    )
