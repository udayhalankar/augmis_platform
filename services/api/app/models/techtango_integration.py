"""B4: immutable verified-scope bridge binding, pending until proof exchange."""
import uuid
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from services.api.app.db.base import Base


class TechtangoTenantLink(Base):
    __tablename__ = "techtango_tenant_links"
    __table_args__ = (
        UniqueConstraint("external_tenant_id", name="uq_techtango_external_tenant"),
        UniqueConstraint("augmis_tenant_id", name="uq_techtango_augmis_tenant"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    augmis_tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("iam_users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    verified_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TechtangoBridgeNonce(Base):
    """Durable one-use JTI across API workers (unique primary key)."""
    __tablename__ = "techtango_bridge_nonces"
    jti: Mapped[str] = mapped_column(String(128), primary_key=True)
    link_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("techtango_tenant_links.id", ondelete="RESTRICT"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    used_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TechtangoAppSnapshot(Base):
    """Immutable allowlisted metadata. Not an AAPS/hostable app package."""
    __tablename__ = "techtango_app_snapshots"
    __table_args__ = (
        UniqueConstraint("link_id", "app_slug", "sha256", name="uq_techtango_stage_snapshot_digest"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    link_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("techtango_tenant_links.id", ondelete="RESTRICT"), nullable=False)
    external_app_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    app_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False)
    staged_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("iam_users.id", ondelete="RESTRICT"), nullable=False)
    staged_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
