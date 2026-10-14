"""B4 Pass 2: independently verified tenant link + immutable metadata staging."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b4pass2261012"
down_revision = "b3b4tenant261012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("techtango_tenant_links", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "techtango_bridge_nonces",
        sa.Column("jti", sa.String(128), primary_key=True),
        sa.Column("link_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("techtango_tenant_links.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "techtango_app_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("link_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("techtango_tenant_links.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("external_app_id", sa.BigInteger(), nullable=False),
        sa.Column("app_slug", sa.String(64), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("staged_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("iam_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("staged_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("link_id", "app_slug", "sha256", name="uq_techtango_stage_snapshot_digest"),
    )
    op.create_index("ix_techtango_app_snapshots_link", "techtango_app_snapshots", ["link_id"])


def downgrade():
    op.drop_index("ix_techtango_app_snapshots_link", table_name="techtango_app_snapshots")
    op.drop_table("techtango_app_snapshots")
    op.drop_table("techtango_bridge_nonces")
    op.drop_column("techtango_tenant_links", "verified_at")
