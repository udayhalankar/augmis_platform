"""Add explicit owning-organization link to publisher workspaces.

Revision ID: c8b6a53d29e1
Revises: f2a7c4d91e60

Legacy publishers remain NULL until each mapping has been explicitly approved.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c8b6a53d29e1"
down_revision = "f2a7c4d91e60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("publishers", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_publishers_tenant_id_tenants",
        "publishers", "tenants", ["tenant_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_publishers_tenant_id", "publishers", ["tenant_id"])


def downgrade() -> None:
    # WARNING: downgrading removes all publisher/organization associations.
    op.drop_index("ix_publishers_tenant_id", table_name="publishers")
    op.drop_constraint("fk_publishers_tenant_id_tenants", "publishers", type_="foreignkey")
    op.drop_column("publishers", "tenant_id")
