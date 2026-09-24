"""separate application version publication status

Revision ID: 79b7599334bc
Revises: 4ace2634625e
Create Date: 2026-09-22 16:33:03.934912

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '79b7599334bc'
down_revision: Union[str, Sequence[str], None] = '4ace2634625e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.add_column(
        "application_versions",
        sa.Column(
            "publication_status",
            sa.String(length=30),
            nullable=False,
            server_default="draft",
        ),
    )

    op.create_index(
        "ix_application_versions_publication_status",
        "application_versions",
        ["publication_status"],
        unique=False,
    )

    # Recover publication lifecycle from the temporary design that
    # overwrote the technical status with published / retired.
    op.execute(
        """
        UPDATE application_versions
        SET publication_status = status
        WHERE status IN ('published', 'retired')
        """
    )

    # Restore technical lifecycle for versions that had their
    # technical status overwritten by publication state.
    #
    # Static applications do not require a container image.
    op.execute(
        """
        UPDATE application_versions
        SET status = 'validated'
        WHERE status IN ('published', 'retired')
          AND build_type = 'static_web'
        """
    )

    # The platform only allowed container versions to publish after
    # reaching image_ready, so published/retired container versions
    # can safely be restored to image_ready.
    op.execute(
        """
        UPDATE application_versions
        SET status = 'image_ready'
        WHERE status IN ('published', 'retired')
          AND build_type <> 'static_web'
        """
    )

    # Enforce one currently published version per application.
    op.create_index(
        "uq_application_versions_one_published_per_app",
        "application_versions",
        ["application_id"],
        unique=True,
        postgresql_where=sa.text(
            "publication_status = 'published'"
        ),
    )


def downgrade() -> None:

    op.drop_index(
        "uq_application_versions_one_published_per_app",
        table_name="application_versions",
    )

    # Best-effort restoration of the previous combined lifecycle.
    op.execute(
        """
        UPDATE application_versions
        SET status = publication_status
        WHERE publication_status IN ('published', 'retired')
        """
    )

    op.drop_index(
        "ix_application_versions_publication_status",
        table_name="application_versions",
    )

    op.drop_column(
        "application_versions",
        "publication_status",
    )

