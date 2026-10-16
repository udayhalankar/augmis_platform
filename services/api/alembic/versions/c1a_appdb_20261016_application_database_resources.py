"""C1-A metadata migration.

Parent revision verified from `alembic heads` on 2026-10-16:
  b4pass2261012
This creates control-plane resource metadata only; NO Docker/PG resources.
This ONLY creates control-plane resource metadata; no Docker/PG resources.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c1a_appdb_20261016"
down_revision = "b4pass2261012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "application_database_resources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("engine", sa.String(length=24), nullable=False),
        sa.Column("engine_version", sa.String(length=12), nullable=False),
        sa.Column("storage_request", sa.String(length=24), nullable=False),
        sa.Column("database_name", sa.String(length=63), nullable=False),
        sa.Column("database_host_alias", sa.String(length=63), nullable=False),
        sa.Column("network_name", sa.String(length=80), nullable=False),
        sa.Column("container_name", sa.String(length=80), nullable=False),
        sa.Column("data_volume", sa.String(length=80), nullable=False),
        sa.Column("bootstrap_secret_volume", sa.String(length=80), nullable=False),
        sa.Column("database_image_id", sa.String(length=90), nullable=True),
        sa.Column("migration_revision", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["instance_id"], ["application_instances.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("instance_id", name="uq_application_database_instance"),
        sa.UniqueConstraint("network_name", name="uq_application_database_network"),
        sa.UniqueConstraint("container_name", name="uq_application_database_container"),
        sa.UniqueConstraint("data_volume", name="uq_application_database_volume"),
        sa.UniqueConstraint("bootstrap_secret_volume", name="uq_application_database_bootstrap_volume"),
    )
    op.create_index("ix_application_database_resources_instance_id", "application_database_resources", ["instance_id"])
    op.create_index("ix_application_database_resources_tenant_id", "application_database_resources", ["tenant_id"])
    op.create_index("ix_application_database_resources_status", "application_database_resources", ["status"])


def downgrade():
    # Recoverable persistent data must not lose its ownership metadata through
    # an unreviewed downgrade. Make destructive migration an explicit decision.
    raise RuntimeError("C1-A database ownership metadata requires an audited manual downgrade plan")
