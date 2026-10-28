"""C1-D2: durable auto-qualification queue, release gate and trusted worker.

No client-provided evidence is trusted. The qualifier is executed only by a
trusted local worker after a successful immutable Docker build. Existing
published versions are not modified. Recovery of interrupted qualifications
is intentionally manual until C1-D3 reconciliation is delivered.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from services.api.app.models.deployment_reliability import ApplicationBuildQualification
from services.api.app.models.platform import ApplicationBuild, ApplicationVersion
from services.api.app.services.aaps_deployment_contract import assess_manifest, DeploymentContractError
from services.api.app.services.aaps_declarative_schema import read_declarative_schema
from services.api.app.services.deployment_reliability import (
    record_pending_qualification, record_smoke_result, valid_qualification,
    ReliabilityError,
)
from services.api.app.services.runtime_controls_service import pinned_image_identity, RuntimeControlError
from services.api.app.services.c1d2_disposable_qualification import (
    DisposableQualification, RuntimeImages, QualificationFailure,
)
from services.api.app.core.runtime_host import read_profile
from services.api.app.services.runtime_host_readiness import check_runtime_host
from services.api.app.services.audit_service import record_audit_event

REVISION = 'c1d2-disposable-2'
SMOKE_KEYS = ('image_identity', 'database_isolation', 'schema_rls',
              'internal_health', 'gateway_auth', 'gateway_rejection')

class QualificationGateError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def supported_manifest(manifest: dict) -> bool:
    try:
        plan = assess_manifest(manifest)
        return bool(plan.requires_private_database and plan.has_migration_contract and
                    plan.has_route_contract and read_declarative_schema(manifest) is not None)
    except (DeploymentContractError, TypeError, ValueError):
        return False


def enqueue_ready_build(db, *, build: ApplicationBuild, version: ApplicationVersion):
    """Called ONLY after a successful Docker build. Never starts Docker."""
    if build.status != 'ready' or version.status != 'image_ready':
        raise QualificationGateError('C1D2_BUILD_NOT_READY')
    if version.build_type != 'dockerfile' or not supported_manifest(version.manifest):
        # Incompatible container packages must not get a false qualification.
        raise QualificationGateError('C1D2_CONTRACT_NOT_QUALIFIABLE')
    try:
        image_id = pinned_image_identity(db, build)
        return record_pending_qualification(db, build_id=build.id,
            version_id=version.id, image_id=image_id, manifest=version.manifest)
    except (RuntimeControlError, ReliabilityError) as exc:
        raise QualificationGateError('C1D2_BUILD_IDENTITY_NOT_PINNED') from exc


def require_passing_build(db, *, version: ApplicationVersion):
    """Fail-closed publication boundary for NEW Docker versions."""
    if version.build_type == 'static_web':
        return None
    if version.build_type != 'dockerfile' or not supported_manifest(version.manifest):
        raise QualificationGateError('C1D2_UNSUPPORTED_APPLICATION_CONTRACT')
    build = db.scalar(select(ApplicationBuild).where(
        ApplicationBuild.application_version_id == version.id,
        ApplicationBuild.status == 'ready').order_by(ApplicationBuild.created_at.desc()))
    if build is None:
        raise QualificationGateError('C1D2_READY_BUILD_REQUIRED')
    try:
        image_id = pinned_image_identity(db, build)
    except RuntimeControlError as exc:
        raise QualificationGateError('C1D2_IMMUTABLE_IMAGE_NOT_AVAILABLE') from exc
    evidence = db.scalar(select(ApplicationBuildQualification).where(
        ApplicationBuildQualification.build_id == build.id))
    if not valid_qualification(evidence, build_id=build.id, version_id=version.id,
                               image_id=image_id, manifest=version.manifest):
        raise QualificationGateError('C1D2_QUALIFICATION_REQUIRED')
    return evidence


def worker_one(db, *, runner_class=DisposableQualification) -> str:
    """Return IDLE, PASS or FAIL. Claim once; no blind replays after crashes."""
    profile = read_profile()
    if profile is None or not check_runtime_host().ready:
        raise QualificationGateError('C1D2_RUNTIME_HOST_UNREADY')
    row = db.scalar(select(ApplicationBuildQualification).where(
        ApplicationBuildQualification.status == 'pending_smoke',
        ApplicationBuildQualification.started_at.is_(None)).order_by(
        ApplicationBuildQualification.created_at.asc()
        ).with_for_update(skip_locked=True).limit(1))
    if row is None:
        return 'IDLE'
    build = db.get(ApplicationBuild, row.build_id)
    version = db.get(ApplicationVersion, row.application_version_id)
    if not build or not version or build.application_version_id != version.id or (
            build.status != 'ready' or version.status != 'image_ready' or
            version.publication_status != 'draft' or not supported_manifest(version.manifest)):
        row.status = 'needs_review'
        row.failure_code = 'C1D2_CANDIDATE_CHANGED'
        db.commit()
        return 'FAIL'
    try:
        pinned = pinned_image_identity(db, build)
        if row.image_id != pinned:
            raise QualificationGateError('C1D2_CANDIDATE_IMAGE_CHANGED')
        runner = runner_class(manifest=version.manifest, image_id=pinned,
            images=RuntimeImages(
                postgres_image_id=profile.environment['AUGMIS_C1B_POSTGRES_IMAGE_ID'],
                relay_image_id=profile.environment['AUGMIS_C1C_GENERIC_RELAY_IMAGE_ID'],
                ingress_network=profile.environment['AUGMIS_C1B_CRUD_INGRESS_NETWORK']))
    except (QualificationFailure, QualificationGateError, RuntimeControlError, KeyError):
        row.status = 'needs_review'
        row.failure_code = 'C1D2_PRECHECK_REQUIRES_REVIEW'
        db.commit()
        return 'FAIL'
    row.started_at = datetime.now(timezone.utc)
    db.commit()  # Durable claim. A crash leaves an un-replayed, inspectable row.
    code = None
    try:
        checks = runner.run()
    except QualificationFailure as exc:
        code = exc.code
        checks = {name: False for name in SMOKE_KEYS}
    except Exception:
        code = 'C1D2_UNEXPECTED_SMOKE_FAILURE'
        checks = {name: False for name in SMOKE_KEYS}
    if not isinstance(checks, dict) or set(checks) != set(SMOKE_KEYS) or any(
            type(value) is not bool for value in checks.values()):
        code = 'C1D2_SMOKE_EVIDENCE_INVALID'
        checks = {name: False for name in SMOKE_KEYS}
    elif code is None and not all(checks.values()):
        code = 'C1D2_SMOKE_ASSERTION_FAILED'
    try:
        record_smoke_result(db, build_id=build.id, version_id=version.id,
            image_id=pinned, manifest=version.manifest,
            qualifier_revision=REVISION, checks=checks, failure_code=code)
        db.commit()
    except Exception:
        db.rollback()
        raise QualificationGateError('C1D2_RESULT_PERSISTENCE_FAILED')
    return 'PASS' if code is None else 'FAIL'


def quarantine_interrupted_smokes(db, *, older_than_seconds: int = 14400,
                                  limit: int = 25, at: datetime | None = None) -> int:
    """Explicit, audited metadata quarantine for an abandoned durable claim.

    Never retries Docker work, resets started_at, or issues a PASS. Must be
    executed only by the trusted operator worker with explicit approval.
    """
    if type(older_than_seconds) is not int or not 3600 <= older_than_seconds <= 604800:
        raise QualificationGateError('R06_STALE_WINDOW_INVALID')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise QualificationGateError('R06_STALE_LIMIT_INVALID')
    now = at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise QualificationGateError('R06_UTC_REQUIRED')
    cutoff = now - timedelta(seconds=older_than_seconds)
    rows = list(db.scalars(select(ApplicationBuildQualification).where(
        ApplicationBuildQualification.status == 'pending_smoke',
        ApplicationBuildQualification.started_at.is_not(None),
        ApplicationBuildQualification.started_at <= cutoff,
    ).order_by(ApplicationBuildQualification.started_at.asc())
      .with_for_update(skip_locked=True).limit(limit)))
    for row in rows:
        row.status = 'needs_review'
        row.failure_code = 'R06_INTERRUPTED_QUALIFICATION_REVIEW_REQUIRED'
        row.checks_json = None
        # Preserve claim time and do not set finished_at, evidence or qualifier_revision.
        record_audit_event(db, action='application.qualification.interrupted',
            resource_type='application_build_qualification', resource_id=row.build_id,
            outcome='failed', message='Interrupted qualification requires manual review.',
            metadata={'code':'R06_INTERRUPTED_QUALIFICATION_REVIEW_REQUIRED'})
    db.commit()  # Atomic qualification status and audit trail.
    return len(rows)
