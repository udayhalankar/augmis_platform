"""C1-D2/D3: durable qualification and deployment journal metadata.

Additive control-plane tables ONLY. No existing deployment, subscription,
application database, Docker network, container or volume is touched.
Do not downgrade without an explicit data-preservation review.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c1d23_20261018'
down_revision = 'c1b2_20261017'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'application_build_qualifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('build_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('application_version_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('image_id', sa.String(90), nullable=False),
        sa.Column('manifest_sha256', sa.String(64), nullable=False),
        sa.Column('status', sa.String(28), nullable=False),
        sa.Column('qualifier_revision', sa.String(64)),
        sa.Column('checks_json', postgresql.JSONB()),
        sa.Column('failure_code', sa.String(80)),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['build_id'], ['application_builds.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['application_version_id'], ['application_versions.id'], ondelete='RESTRICT'),
        sa.UniqueConstraint('build_id', name='uq_c1d_build_qualification'),
    )
    op.create_index('ix_c1d_qualification_build_id', 'application_build_qualifications', ['build_id'])
    op.create_index('ix_c1d_qualification_status', 'application_build_qualifications', ['status'])
    op.create_table(
        'deployment_operation_journals',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('deployment_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('instance_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('stage', sa.String(32), nullable=False),
        sa.Column('state', sa.String(32), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('owner', sa.String(100)),
        sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.Column('failure_code', sa.String(80)),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['deployment_id'], ['application_deployments.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['instance_id'], ['application_instances.id'], ondelete='RESTRICT'),
        sa.UniqueConstraint('deployment_id', name='uq_c1d_deployment_journal'),
    )
    op.create_index('ix_c1d_journal_deployment_id', 'deployment_operation_journals', ['deployment_id'])
    op.create_index('ix_c1d_journal_stage', 'deployment_operation_journals', ['stage'])
    op.create_index('ix_c1d_journal_state', 'deployment_operation_journals', ['state'])


def downgrade():
    raise RuntimeError('C1-D qualification and recovery evidence requires an audited manual downgrade plan')
