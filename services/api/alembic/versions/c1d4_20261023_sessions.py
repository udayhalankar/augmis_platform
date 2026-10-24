"""C1-D4: revocable sessions and configurable tenant idle policies.

Revision ID: c1d4_sessions_1023
Revises: c1d23_20261018
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "c1d4_sessions_1023"
down_revision = "c1d23_20261018"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "iam_auth_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("iam_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("refresh_hash", sa.String(64), nullable=False),
        sa.Column("previous_refresh_hash", sa.String(64)),
        sa.Column("rotated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoke_reason", sa.String(60)),
    )
    op.create_index("ix_iam_auth_sessions_user_id", "iam_auth_sessions", ["user_id"])
    op.create_index("ix_iam_auth_sessions_user_active", "iam_auth_sessions", ["user_id", "revoked_at"])
    op.create_table(
        "iam_session_policies",
        sa.Column("policy_key", sa.String(90), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), unique=True),
        sa.Column("idle_minutes", sa.Integer(), nullable=False),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("iam_users.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("idle_minutes BETWEEN 5 AND 120", name="ck_iam_session_idle_minutes"),
    )


def downgrade():
    # Downgrade revokes active sessions, and is intentionally blocked by default.
    raise RuntimeError("C1-D4 security tables cannot be downgraded without explicit data-loss approval")
