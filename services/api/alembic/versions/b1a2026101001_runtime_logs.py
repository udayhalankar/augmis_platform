"""B1A: bounded historical runtime log snapshots.

Revision ID: b1a2026101001
Revises: 9d3a4c7e1b20
"""
from alembic import op
import sqlalchemy as sa

revision = "b1a2026101001"
down_revision = "9d3a4c7e1b20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("application_deployments", sa.Column("archived_logs", sa.Text(), nullable=True))
    op.add_column("application_deployments", sa.Column("archived_logs_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("application_deployments", sa.Column("archived_logs_truncated", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("application_deployments", sa.Column("archived_logs_error", sa.String(length=80), nullable=True))


def downgrade() -> None:
    # Destructive downgrade: back up historical evidence before running.
    op.drop_column("application_deployments", "archived_logs_error")
    op.drop_column("application_deployments", "archived_logs_truncated")
    op.drop_column("application_deployments", "archived_logs_at")
    op.drop_column("application_deployments", "archived_logs")
