"""C1-D3 automatic, non-destructive reconciliation of stale deployment journals.

The worker observes only existing authorization-created deployment operations.
It NEVER starts, stops, deletes, adopts, or promotes Docker resources. A stale
operation may be quarantined for later operator-approved resolution; a stopped
historical deployment with a terminal 'active' journal is never replayed.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from types import SimpleNamespace

from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import Session

from services.api.app.models.platform import ApplicationDeployment, ApplicationInstance
from services.api.app.models.deployment_reliability import DeploymentOperationJournal
from services.api.app.services.c1d3_recovery_audit import (
    DockerState, DockerInspectionError, inspect_exact_container,
)

# Extra delay after a lease expiry allows in-flight Docker/DB operations to
# finish; stale metadata is still never treated as permission for replay.
DEFAULT_LEASE_GRACE_SECONDS = 900
DEFAULT_QUEUED_STALE_SECONDS = 3600
_VALID_STATES = frozenset({'queued', 'running'})


@dataclass(frozen=True)
class Observation:
    code: str
    decision: str
    container_state: str


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def stale_reason(journal: DeploymentOperationJournal, *, now: datetime,
                 grace_seconds: int = DEFAULT_LEASE_GRACE_SECONDS,
                 queued_seconds: int = DEFAULT_QUEUED_STALE_SECONDS) -> str | None:
    """A lease is stale only after the grace; queued requires a longer wait."""
    if not 60 <= grace_seconds <= 86400 or not 300 <= queued_seconds <= 604800:
        raise ValueError('C1D3_RECOVERY_WINDOW_INVALID')
    current = _utc(now)
    if journal.state == 'running':
        lease = _utc(journal.lease_until)
        # A missing lease is invalid; do not decide instantly if it was just claimed.
        if lease is None:
            updated = _utc(journal.updated_at or journal.created_at)
            return 'C1D3_LEASE_MISSING' if updated and updated <= current - timedelta(seconds=queued_seconds) else None
        return 'C1D3_LEASE_EXPIRED' if lease <= current - timedelta(seconds=grace_seconds) else None
    if journal.state == 'queued':
        created = _utc(journal.created_at)
        return 'C1D3_QUEUED_ABANDONED' if created and created <= current - timedelta(seconds=queued_seconds) else None
    return None


def observe_operation(*, instance: ApplicationInstance,
                      deployment: ApplicationDeployment,
                      journal: DeploymentOperationJournal,
                      docker_state: DockerState | None,
                      docker_error: str | None = None) -> Observation:
    """Plan a metadata quarantine; never infer HTTP/gateway health from Docker.

    If ownership is suspicious the operator sees a security stop, not a replay.
    Raw Docker inspect data, environment and credentials are never serialized.
    """
    if (deployment.instance_id != instance.id or journal.instance_id != instance.id
            or journal.tenant_id != instance.tenant_id or journal.deployment_id != deployment.id):
        return Observation('C1D3_OWNERSHIP_CONFLICT', 'SECURITY_REVIEW', 'unknown')
    if journal.stage == 'active' or journal.state not in _VALID_STATES:
        return Observation('C1D3_TERMINAL_OR_ACTIVE', 'NO_ACTION', 'unknown')
    if docker_error:
        return Observation('C1D3_DOCKER_INSPECT_UNAVAILABLE', 'QUARANTINE', 'unknown')
    if docker_state is None:
        return Observation('C1D3_CONTAINER_UNVERIFIED', 'QUARANTINE', 'unknown')
    if docker_state.state == 'missing':
        return Observation('C1D3_CONTAINER_MISSING', 'QUARANTINE', 'missing')
    required = {
        'augmis.managed': 'true',
        'augmis.instance_id': str(instance.id),
        'augmis.tenant_id': str(instance.tenant_id),
        'augmis.application_id': str(instance.application_id),
    }
    if any(docker_state.labels.get(k) != value for k, value in required.items()):
        return Observation('C1D3_LABEL_MISMATCH', 'SECURITY_REVIEW', docker_state.state)
    # If a Docker ID was previously durably recorded it must match exactly.
    if deployment.container_id and docker_state.id != deployment.container_id:
        return Observation('C1D3_CONTAINER_ID_MISMATCH', 'SECURITY_REVIEW', docker_state.state)
    if docker_state.state == 'running':
        return Observation('C1D3_RUNNING_UNRESOLVED', 'QUARANTINE', 'running')
    return Observation('C1D3_RUNTIME_UNAVAILABLE', 'QUARANTINE', docker_state.state)


def _make_report(*, deployment_id, instance_id, journal_state, stage,
                 observation: Observation, applied: bool) -> dict:
    return {
        'instanceId': str(instance_id),
        'deploymentId': str(deployment_id),
        'journalState': journal_state,
        'journalStage': stage,
        'code': observation.code,
        'decision': observation.decision,
        'containerState': observation.container_state,
        'quarantined': applied,
    }


def reconcile_once(db: Session, *, tenant_id: uuid.UUID,
                   apply: bool = False, limit: int = 25,
                   now: datetime | None = None,
                   lease_grace_seconds: int = DEFAULT_LEASE_GRACE_SECONDS,
                   queued_stale_seconds: int = DEFAULT_QUEUED_STALE_SECONDS,
                   inspector: Callable[[str], DockerState] = inspect_exact_container) -> dict:
    """One tenant-scoped scan. No Docker writes; updates *only* journal metadata.

    SELECT FOR UPDATE SKIP LOCKED on the final mutation prevents competing
    recovery workers from racing each other. Recheck exact journal snapshot after
    Docker inspection: an in-flight operator action always wins.
    """
    if not isinstance(tenant_id, uuid.UUID):
        raise ValueError('C1D3_TENANT_REQUIRED')
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('C1D3_SCAN_LIMIT_INVALID')
    current = _utc(now or datetime.now(timezone.utc))
    if not 60 <= lease_grace_seconds <= 86400 or not 300 <= queued_stale_seconds <= 604800:
        raise ValueError('C1D3_RECOVERY_WINDOW_INVALID')
    # Filter stale candidates BEFORE LIMIT to avoid starving older incomplete
    # operations behind a page of healthy, still-leased operations.
    lease_cutoff = current - timedelta(seconds=lease_grace_seconds)
    queue_cutoff = current - timedelta(seconds=queued_stale_seconds)
    stale_clause = or_(
        and_(DeploymentOperationJournal.state == 'queued',
             DeploymentOperationJournal.created_at <= queue_cutoff),
        and_(DeploymentOperationJournal.state == 'running',
             or_(DeploymentOperationJournal.lease_until <= lease_cutoff,
                 and_(DeploymentOperationJournal.lease_until.is_(None),
                      func.coalesce(DeploymentOperationJournal.updated_at,
                                    DeploymentOperationJournal.created_at) <= queue_cutoff))),
    )
    stmt = (select(DeploymentOperationJournal, ApplicationDeployment, ApplicationInstance)
            .join(ApplicationDeployment, DeploymentOperationJournal.deployment_id == ApplicationDeployment.id)
            .join(ApplicationInstance, DeploymentOperationJournal.instance_id == ApplicationInstance.id)
            .where(DeploymentOperationJournal.tenant_id == tenant_id,
                   ApplicationInstance.tenant_id == tenant_id,
                   stale_clause,
                   DeploymentOperationJournal.stage != 'active')
            .order_by(DeploymentOperationJournal.created_at.asc())
            .limit(limit))
    # Freeze ORM data before rollback: rollback normally expires ORM fields.
    snapshots = []
    for j, d, i in db.execute(stmt):
        snapshots.append((
            SimpleNamespace(id=j.id, deployment_id=j.deployment_id,
                tenant_id=j.tenant_id, instance_id=j.instance_id,
                state=j.state, stage=j.stage, owner=j.owner,
                lease_until=j.lease_until, created_at=j.created_at,
                updated_at=j.updated_at),
            SimpleNamespace(id=d.id, instance_id=d.instance_id,
                container_name=d.container_name, container_id=d.container_id,
                status=d.status),
            SimpleNamespace(id=i.id, tenant_id=i.tenant_id,
                application_id=i.application_id)
        ))
    # End the initial read-only transaction before slow Docker inspect.
    db.rollback()
    reports = []
    for journal, deployment, instance in snapshots:
        reason = stale_reason(journal, now=current, grace_seconds=lease_grace_seconds,
                              queued_seconds=queued_stale_seconds)
        if reason is None or journal.stage == 'active':
            continue
        prior_owner = journal.owner
        prior_state = journal.state
        prior_stage = journal.stage
        prior_lease = _utc(journal.lease_until)
        prior_updated = _utc(journal.updated_at)
        name = deployment.container_name
        state, error = None, None
        if name:
            try:
                state = inspector(name)
            except DockerInspectionError as exc:
                error = exc.code
        observation = observe_operation(instance=instance, deployment=deployment,
                                        journal=journal, docker_state=state,
                                        docker_error=error)
        if not apply or observation.decision == 'NO_ACTION':
            reports.append(_make_report(deployment_id=deployment.id,
                          instance_id=instance.id, journal_state=prior_state,
                          stage=prior_stage, observation=observation, applied=False))
            continue
        # Recheck all ownership and freshness invariants under a row lock.
        locked = db.scalar(select(DeploymentOperationJournal)
                           .where(DeploymentOperationJournal.id == journal.id,
                                  DeploymentOperationJournal.tenant_id == tenant_id)
                           .with_for_update(skip_locked=True))
        if (locked is None or locked.owner != prior_owner or locked.state != prior_state
                or locked.stage != prior_stage or _utc(locked.lease_until) != prior_lease
                or _utc(locked.updated_at) != prior_updated
                or stale_reason(locked, now=current,
                                grace_seconds=lease_grace_seconds,
                                queued_seconds=queued_stale_seconds) is None):
            db.rollback()
            reports.append(_make_report(deployment_id=deployment.id,
                instance_id=instance.id, journal_state=prior_state, stage=prior_stage,
                observation=Observation('C1D3_CONCURRENT_CHANGE', 'RECHECK', 'unknown'),
                applied=False))
            continue
        # Never mark a deployment running, failed, or stopped; never alter
        # subscription baseline, active version, DB resources, or Docker state.
        locked.state = 'needs_reconciliation'
        locked.failure_code = observation.code
        locked.owner = None
        locked.lease_until = None
        db.commit()
        reports.append(_make_report(deployment_id=deployment.id,
            instance_id=instance.id, journal_state=prior_state, stage=prior_stage,
            observation=observation, applied=True))
    return {'mode': 'metadata_quarantine' if apply else 'read_only',
            'tenantId': str(tenant_id), 'scanned': len(snapshots),
            'stale': len(reports), 'quarantined': sum(int(r['quarantined']) for r in reports),
            'records': reports}
