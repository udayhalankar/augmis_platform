"""C1-D2/D3 fail-closed qualification binding and non-destructive operation state.

This library intentionally never starts, removes or retries a Docker container.
A subsequent authorized smoke runner must populate qualification evidence. A
recovery worker must inspect actual resource ownership before touching Docker.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from services.api.app.models.deployment_reliability import (
    ApplicationBuildQualification, DeploymentOperationJournal,
)

IMAGE = re.compile(r'sha256:[a-f0-9]{64}\Z')
CODE = re.compile(r'[A-Z][A-Z0-9_]{2,79}\Z')

STAGES = (
    'reserved', 'database_provisioning', 'database_ready', 'schema_initializing',
    'runtime_starting', 'health_checking', 'gateway_verifying', 'active',
)
TERMINAL = frozenset({'active', 'failed', 'needs_reconciliation'})
REQUIRED_SMOKE = frozenset({'image_identity', 'database_isolation', 'schema_rls',
                            'internal_health', 'gateway_auth', 'gateway_rejection'})


class ReliabilityError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def manifest_digest(manifest: dict) -> str:
    if not isinstance(manifest, dict):
        raise ReliabilityError('C1D_MANIFEST_INVALID')
    try:
        encoded = json.dumps(manifest, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, OverflowError) as exc:
        raise ReliabilityError('C1D_MANIFEST_INVALID') from exc
    if len(encoded) > 262144:
        raise ReliabilityError('C1D_MANIFEST_TOO_LARGE')
    return hashlib.sha256(encoded).hexdigest()


def valid_qualification(qualification: ApplicationBuildQualification | None, *,
                        build_id: Any, version_id: Any, image_id: str,
                        manifest: dict) -> bool:
    """Only a real smoke attestation for the exact immutable build can pass."""
    if qualification is None or not IMAGE.fullmatch(image_id):
        return False
    if (qualification.status != 'passed' or qualification.build_id != build_id
            or qualification.application_version_id != version_id
            or qualification.image_id != image_id
            or qualification.manifest_sha256 != manifest_digest(manifest)
            or not qualification.finished_at or not qualification.qualifier_revision):
        return False
    checks = qualification.checks_json
    return (isinstance(checks, dict) and REQUIRED_SMOKE <= checks.keys()
            and all(checks[key] is True for key in REQUIRED_SMOKE))


def record_pending_qualification(db: Session, *, build_id: Any, version_id: Any,
                                 image_id: str, manifest: dict) -> ApplicationBuildQualification:
    """Prepares *pending* work; does not mark an image qualified or publish it."""
    if not isinstance(image_id, str) or not IMAGE.fullmatch(image_id):
        raise ReliabilityError('C1D_IMAGE_ID_REQUIRED')
    digest = manifest_digest(manifest)
    row = db.scalar(select(ApplicationBuildQualification)
                    .where(ApplicationBuildQualification.build_id == build_id)
                    .with_for_update())
    if row is None:
        row = ApplicationBuildQualification(build_id=build_id,
            application_version_id=version_id, image_id=image_id,
            manifest_sha256=digest, status='pending_smoke')
        db.add(row)
    elif row.application_version_id != version_id:
        raise ReliabilityError('C1D_BUILD_VERSION_MISMATCH')
    elif row.image_id != image_id or row.manifest_sha256 != digest:
        # Never recycle a pass after image/manifest drift. Quarantine for audit.
        row.status = 'needs_review'
        row.failure_code = 'C1D_BUILD_IDENTITY_CHANGED'
        row.checks_json = None
        row.finished_at = None
    return row


def record_smoke_result(db: Session, *, build_id: Any, version_id: Any,
                        image_id: str, manifest: dict, qualifier_revision: str,
                        checks: dict[str, bool], failure_code: str | None = None,
                        at: datetime | None = None) -> ApplicationBuildQualification:
    """Trusted-internal executor only. Never expose directly as a publisher API.

    This service cannot establish that checks actually ran; the calling
    qualification executor must own isolated smoke infrastructure and results.
    """
    if not isinstance(qualifier_revision, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}', qualifier_revision):
        raise ReliabilityError('C1D_QUALIFIER_REVISION_INVALID')
    if not isinstance(checks, dict) or set(checks) != REQUIRED_SMOKE or any(type(v) is not bool for v in checks.values()):
        raise ReliabilityError('C1D_SMOKE_EVIDENCE_INVALID')
    if failure_code is not None and not CODE.fullmatch(failure_code):
        raise ReliabilityError('C1D_FAILURE_CODE_INVALID')
    row = db.scalar(select(ApplicationBuildQualification).where(
        ApplicationBuildQualification.build_id == build_id).with_for_update())
    if row is None or row.application_version_id != version_id or row.image_id != image_id or row.manifest_sha256 != manifest_digest(manifest):
        raise ReliabilityError('C1D_QUALIFICATION_IDENTITY_MISMATCH')
    if row.status != 'pending_smoke':
        raise ReliabilityError('C1D_QUALIFICATION_NOT_PENDING')
    passed = all(checks.values())
    if not passed and not failure_code:
        raise ReliabilityError('C1D_FAILURE_CODE_REQUIRED')
    row.status = 'passed' if passed else 'failed'
    row.failure_code = None if passed else failure_code
    row.qualifier_revision = qualifier_revision
    row.checks_json = checks
    row.finished_at = at or utcnow()
    return row


def _get_locked(db: Session, deployment_id: Any) -> DeploymentOperationJournal:
    journal = db.scalar(select(DeploymentOperationJournal)
                        .where(DeploymentOperationJournal.deployment_id == deployment_id)
                        .with_for_update())
    if journal is None:
        raise ReliabilityError('C1D_JOURNAL_NOT_FOUND')
    return journal


def reserve_journal(db: Session, *, deployment_id: Any, tenant_id: Any,
                    instance_id: Any) -> DeploymentOperationJournal:
    """Call inside the same transaction as creation of a deployment record."""
    row = db.scalar(select(DeploymentOperationJournal).where(
        DeploymentOperationJournal.deployment_id == deployment_id).with_for_update())
    if row is not None:
        if row.tenant_id != tenant_id or row.instance_id != instance_id:
            raise ReliabilityError('C1D_JOURNAL_OWNERSHIP_CONFLICT')
        return row
    row = DeploymentOperationJournal(deployment_id=deployment_id,
              tenant_id=tenant_id, instance_id=instance_id,
              stage='reserved', state='queued', attempt=0)
    db.add(row)
    return row


def claim_journal(db: Session, *, deployment_id: Any, worker: str,
                  lease_seconds: int = 300, at: datetime | None = None) -> DeploymentOperationJournal:
    if not isinstance(worker, str) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,100}', worker):
        raise ReliabilityError('C1D_WORKER_INVALID')
    if not 30 <= lease_seconds <= 1800:
        raise ReliabilityError('C1D_LEASE_INVALID')
    now = at or utcnow()
    row = _get_locked(db, deployment_id)
    if row.state != 'queued':
        raise ReliabilityError('C1D_JOURNAL_NOT_QUEUED')
    row.state = 'running'
    row.owner = worker
    row.lease_until = now + timedelta(seconds=lease_seconds)
    row.attempt += 1
    return row


def advance_stage(db: Session, *, deployment_id: Any, worker: str,
                  stage: str, at: datetime | None = None) -> DeploymentOperationJournal:
    if stage not in STAGES:
        raise ReliabilityError('C1D_STAGE_INVALID')
    now = at or utcnow()
    row = _get_locked(db, deployment_id)
    if row.state != 'running' or row.owner != worker:
        raise ReliabilityError('C1D_STAGE_NOT_OWNED')
    if row.lease_until is None or row.lease_until <= now:
        raise ReliabilityError('C1D_STAGE_LEASE_EXPIRED')
    if STAGES.index(stage) < STAGES.index(row.stage):
        raise ReliabilityError('C1D_STAGE_REGRESSION')
    # Never mark active by skipping health and signed ingress verification.
    if stage == 'active' and row.stage != 'gateway_verifying':
        raise ReliabilityError('C1D_GATEWAY_VERIFICATION_REQUIRED')
    if stage == 'gateway_verifying' and row.stage != 'health_checking':
        raise ReliabilityError('C1D_HEALTH_VERIFICATION_REQUIRED')
    row.stage = stage
    if stage == 'active':
        row.state = 'active'
        row.owner = None
        row.lease_until = None
    return row


def quarantine_expired(db: Session, *, at: datetime | None = None,
                       limit: int = 100) -> int:
    """No Docker writes or implicit retry. Unknown outcomes require inspection."""
    if not 1 <= limit <= 1000:
        raise ReliabilityError('C1D_SCAN_LIMIT_INVALID')
    now = at or utcnow()
    rows = list(db.scalars(select(DeploymentOperationJournal).where(
        DeploymentOperationJournal.state == 'running',
        or_(DeploymentOperationJournal.lease_until.is_(None),
            DeploymentOperationJournal.lease_until <= now))
        .order_by(DeploymentOperationJournal.created_at.asc())
        .with_for_update(skip_locked=True).limit(limit)))
    for row in rows:
        row.state = 'needs_reconciliation'
        row.failure_code = 'C1D_LEASE_EXPIRED_REVIEW_REQUIRED'
        row.owner = None
        row.lease_until = None
    return len(rows)


def record_failure(db: Session, *, deployment_id: Any, worker: str,
                   failure_code: str) -> DeploymentOperationJournal:
    if not isinstance(failure_code, str) or not CODE.fullmatch(failure_code):
        raise ReliabilityError('C1D_FAILURE_CODE_INVALID')
    row = _get_locked(db, deployment_id)
    if row.state != 'running' or row.owner != worker:
        raise ReliabilityError('C1D_STAGE_NOT_OWNED')
    row.state = 'failed'
    row.failure_code = failure_code
    row.owner = None
    row.lease_until = None
    return row
