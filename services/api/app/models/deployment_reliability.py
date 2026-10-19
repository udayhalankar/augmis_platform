"""C1-D2/D3 durable qualification and operation ownership metadata.

No raw assertion tokens, Docker credentials, or business records are stored here.
These objects do not grant deployment authority by themselves.
"""
from __future__ import annotations

import uuid
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from services.api.app.db.base import Base


class ApplicationBuildQualification(Base):
    __tablename__ = 'application_build_qualifications'
    __table_args__ = (UniqueConstraint('build_id', name='uq_c1d_build_qualification'),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    build_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('application_builds.id', ondelete='RESTRICT'), nullable=False, index=True)
    application_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('application_versions.id', ondelete='RESTRICT'), nullable=False)
    image_id: Mapped[str] = mapped_column(String(90), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(28), nullable=False, default='pending_smoke', index=True)
    qualifier_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checks_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DeploymentOperationJournal(Base):
    __tablename__ = 'deployment_operation_journals'
    __table_args__ = (UniqueConstraint('deployment_id', name='uq_c1d_deployment_journal'),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deployment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('application_deployments.id', ondelete='RESTRICT'), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='RESTRICT'), nullable=False)
    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('application_instances.id', ondelete='RESTRICT'), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default='reserved', index=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default='queued', index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_until: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
