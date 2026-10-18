"""B1/B2 add-on models. Imported by runtime control service and worker."""
import uuid
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from services.api.app.db.base import Base

class RuntimeUpgradeJob(Base):
    __tablename__ = "runtime_upgrade_jobs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_runtime_upgrade_job_key"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("application_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenant_subscriptions.id", ondelete="CASCADE"), nullable=False)
    source_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("application_versions.id", ondelete="RESTRICT"), nullable=False)
    target_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("application_versions.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_until: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class RuntimeInstanceConfig(Base):
    __tablename__ = "runtime_instance_configs"
    __table_args__ = (UniqueConstraint("instance_id", name="uq_runtime_instance_config"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("application_instances.id", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    variables_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Values never stored here. External references require provider integration before injection.
    secret_refs_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

class TenantRuntimeQuota(Base):
    __tablename__ = "tenant_runtime_quotas"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    max_running_containers: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


# C1-A: One dedicated PostgreSQL environment belongs to each logical instance.
# NEVER cascade-delete this row with instance/subscription lifecycle actions:
# it records recoverable resources and retained persistent data.
class ApplicationDatabaseResource(Base):
    __tablename__ = "application_database_resources"
    __table_args__ = (
        UniqueConstraint("instance_id", name="uq_application_database_instance"),
        UniqueConstraint("network_name", name="uq_application_database_network"),
        UniqueConstraint("container_name", name="uq_application_database_container"),
        UniqueConstraint("data_volume", name="uq_application_database_volume"),
        UniqueConstraint("bootstrap_secret_volume", name="uq_application_database_bootstrap_volume"),
        UniqueConstraint("runtime_secret_volume", name="uq_application_database_runtime_volume"),
        # The DB runtime is intentionally NOT constrained to one status per app.
        # Multiple instances of the same application must have isolated databases.
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("application_instances.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    engine: Mapped[str] = mapped_column(String(24), nullable=False, default="postgresql")
    engine_version: Mapped[str] = mapped_column(String(12), nullable=False, default="15")
    storage_request: Mapped[str] = mapped_column(String(24), nullable=False)
    database_name: Mapped[str] = mapped_column(String(63), nullable=False)
    database_host_alias: Mapped[str] = mapped_column(String(63), nullable=False)
    network_name: Mapped[str] = mapped_column(String(80), nullable=False)
    container_name: Mapped[str] = mapped_column(String(80), nullable=False)
    data_volume: Mapped[str] = mapped_column(String(80), nullable=False)
    bootstrap_secret_volume: Mapped[str] = mapped_column(String(80), nullable=False)
    runtime_secret_volume: Mapped[str] = mapped_column(String(80), nullable=False)
    # Only immutable image identities may be recorded after approval, not tags.
    database_image_id: Mapped[str | None] = mapped_column(String(90), nullable=True)
    migration_revision: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # This is a state machine. No Docker operations occur during reservation.
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="reserved", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )
    ready_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)












# """B1/B2 add-on models. Imported by runtime control service and worker."""
# import uuid
# from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
# from sqlalchemy.dialects.postgresql import UUID, JSONB
# from sqlalchemy.orm import Mapped, mapped_column
# from services.api.app.db.base import Base

# class RuntimeUpgradeJob(Base):
#     __tablename__ = "runtime_upgrade_jobs"
#     __table_args__ = (UniqueConstraint("idempotency_key", name="uq_runtime_upgrade_job_key"),)
#     id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
#     idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False)
#     tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
#     instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("application_instances.id", ondelete="CASCADE"), nullable=False, index=True)
#     subscription_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenant_subscriptions.id", ondelete="CASCADE"), nullable=False)
#     source_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("application_versions.id", ondelete="RESTRICT"), nullable=False)
#     target_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("application_versions.id", ondelete="RESTRICT"), nullable=False)
#     status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
#     claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
#     lease_until: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
#     attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
#     last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
#     completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
#     created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

# class RuntimeInstanceConfig(Base):
#     __tablename__ = "runtime_instance_configs"
#     __table_args__ = (UniqueConstraint("instance_id", name="uq_runtime_instance_config"),)
#     id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
#     tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
#     instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("application_instances.id", ondelete="CASCADE"), nullable=False)
#     revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
#     variables_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
#     # Values never stored here. External references require provider integration before injection.
#     secret_refs_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
#     updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

# class TenantRuntimeQuota(Base):
#     __tablename__ = "tenant_runtime_quotas"
#     tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
#     max_running_containers: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
#     updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
