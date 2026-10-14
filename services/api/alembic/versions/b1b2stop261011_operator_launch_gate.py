"""B1+B2: persistent tenant/application operator stop gate and gateway session epoch.

Revision ID: b1b2stop261011
Revises: dynamically selected by the guarded installer
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b1b2stop261011"
down_revision = "b1b22026101001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tenant_application_runtime_controls",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("desired_state", sa.String(length=30), nullable=False, server_default="running"),
        sa.Column("launch_epoch", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["iam_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("tenant_id", "application_id", name="pk_tenant_application_runtime_controls"),
        sa.CheckConstraint("desired_state IN ('running','stopped')", name="ck_tenant_application_runtime_state"),
    )
    # Respect already stopped legacy instances. Ignore stale stopped history
    # if the same tenant/application currently has a running/in-flight instance.
    op.execute("""
        INSERT INTO tenant_application_runtime_controls
          (tenant_id, application_id, desired_state, launch_epoch)
        SELECT DISTINCT i.tenant_id, i.application_id, 'stopped', 1
        FROM application_instances AS i
        WHERE i.status = 'stopped'
          AND NOT EXISTS (
            SELECT 1 FROM application_instances AS active
             WHERE active.tenant_id = i.tenant_id
               AND active.application_id = i.application_id
               AND active.status IN ('running','provisioning','upgrading','stopping')
          )
    """)


def downgrade():
    # Reverting this migration removes the administrative stop gates.
    # Never downgrade while applications are relied upon to remain stopped.
    op.drop_table("tenant_application_runtime_controls")
