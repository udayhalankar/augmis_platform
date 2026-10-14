"""B1+B2 runtime upgrade jobs, configuration and tenant limits.

Revision ID: b1b22026101001
Revises: b1a2026101001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b1b22026101001"
down_revision = "b1a2026101001"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)

def upgrade():
    op.create_table("runtime_upgrade_jobs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("idempotency_key", sa.String(220), nullable=False),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instance_id", UUID, sa.ForeignKey("application_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", UUID, sa.ForeignKey("tenant_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_version_id", UUID, sa.ForeignKey("application_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_version_id", UUID, sa.ForeignKey("application_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("claimed_by", sa.String(100)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_runtime_upgrade_job_key"),
    )
    for col in ("tenant_id", "instance_id", "status"):
        op.create_index(f"ix_runtime_upgrade_jobs_{col}", "runtime_upgrade_jobs", [col])
    op.create_table("runtime_instance_configs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instance_id", UUID, sa.ForeignKey("application_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("variables_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("secret_refs_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("instance_id", name="uq_runtime_instance_config"),
    )
    op.create_index("ix_runtime_instance_configs_tenant_id", "runtime_instance_configs", ["tenant_id"])
    op.create_table("tenant_runtime_quotas",
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("max_running_containers", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("application_builds", sa.Column("immutable_image_id", sa.String(90), nullable=True))
    op.add_column("application_deployments", sa.Column("deployed_image_id", sa.String(90), nullable=True))
    op.add_column("application_deployments", sa.Column("config_revision", sa.BigInteger(), nullable=True))
    op.add_column("application_deployments", sa.Column("config_snapshot_json", postgresql.JSONB(), nullable=True))

def downgrade():
    # WARNING: dropping tables deletes all runtime job/config evidence.
    op.drop_column("application_deployments", "config_snapshot_json")
    op.drop_column("application_deployments", "config_revision")
    op.drop_column("application_deployments", "deployed_image_id")
    op.drop_column("application_builds", "immutable_image_id")
    op.drop_table("tenant_runtime_quotas")
    op.drop_index("ix_runtime_instance_configs_tenant_id", table_name="runtime_instance_configs")
    op.drop_table("runtime_instance_configs")
    for col in ("status", "instance_id", "tenant_id"):
        op.drop_index(f"ix_runtime_upgrade_jobs_{col}", table_name="runtime_upgrade_jobs")
    op.drop_table("runtime_upgrade_jobs")
