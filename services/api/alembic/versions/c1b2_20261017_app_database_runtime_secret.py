"""C1-B2: durable per-instance runtime credential volume identity.

No secrets, database passwords, or Docker resources are created by Alembic.
The column is deterministic for existing reservations, including retained data.
"""
from alembic import op
import sqlalchemy as sa

revision = "c1b2_20261017"
down_revision = "c1a_appdb_20261016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("application_database_resources", sa.Column("runtime_secret_volume", sa.String(80), nullable=True))
    op.execute("""
        UPDATE application_database_resources
           SET runtime_secret_volume = 'augmis-pgruntime-' || replace(instance_id::text, '-', '')
         WHERE runtime_secret_volume IS NULL
    """)
    op.alter_column("application_database_resources", "runtime_secret_volume", nullable=False)
    op.create_unique_constraint("uq_application_database_runtime_volume", "application_database_resources", ["runtime_secret_volume"])


def downgrade():
    raise RuntimeError("C1-B2 persistent credential-volume ownership metadata requires an audited rollback")
