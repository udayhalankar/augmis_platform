"""B4 pending Techtango tenant identity links (no access granted)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b3b4tenant261012"
down_revision = "b1b2stop261011"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("techtango_tenant_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("external_tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("augmis_tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("iam_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending','verified','disabled')", name="ck_techtango_link_status"),
        sa.UniqueConstraint("external_tenant_id", name="uq_techtango_external_tenant"),
        sa.UniqueConstraint("augmis_tenant_id", name="uq_techtango_augmis_tenant"),
    )

def downgrade():
    op.drop_table("techtango_tenant_links")
