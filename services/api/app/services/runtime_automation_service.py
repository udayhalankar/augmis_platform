"""Durable, opt-in runtime upgrade planning and execution (B2).

This module does NOT impersonate a user or call an HTTP route. The worker
runs as a separately deployed trusted control-plane process. The executor
revalidates the subscription and target before making Docker changes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from services.api.app.models.commerce import ApplicationOffer, TenantSubscription, SubscriptionEntitlement
from services.api.app.models.platform import ApplicationBuild, ApplicationInstance, ApplicationVersion
from services.api.app.models.runtime_control import RuntimeUpgradeJob
from services.api.app.services.version_policy_service import (
    VersionPolicyError, is_version_technically_ready, parse_version,
    require_subscription_version_allowed,
)
from services.api.app.services.audit_service import record_audit_event

LEASE = timedelta(minutes=30)  # Expired work is quarantined, never blindly replayed.


def utcnow():
    return datetime.now(timezone.utc)


def _valid_subscription(sub, now):
    return (
        sub.status == "active" and sub.auto_upgrade is True
        and (sub.starts_at is None or sub.starts_at <= now)
        and (sub.ends_at is None or sub.ends_at > now)
    )


def _matching_subscription(db: Session, instance: ApplicationInstance):
    """Match the canonical subscription selected by manual upgrade code.

    This is deliberate while old development data has multiple subscriptions.
    Do NOT authorize with a different subscription's opt-in.
    """
    from services.api.app.services.entitlement_service import require_active_subscription
    try:
        sub = require_active_subscription(db=db, tenant_id=instance.tenant_id,
                                          application_id=instance.application_id)
    except Exception:
        return None
    if not _valid_subscription(sub, utcnow()):
        return None
    # Some development tenants have duplicate live subscriptions for one app.
    # Without an instance.subscription_id binding, do not guess which contract
    # authorized the running instance or its future upgrade.
    rows = list(db.execute(select(TenantSubscription.id).join(
        ApplicationOffer, ApplicationOffer.id == TenantSubscription.offer_id,
    ).where(
        TenantSubscription.tenant_id == instance.tenant_id,
        ApplicationOffer.application_id == instance.application_id,
        TenantSubscription.status == "active",
        ApplicationOffer.status == "active",
    )).all())
    if len(rows) != 1 or rows[0][0] != sub.id:
        return None
    return sub


def _has_deploy_entitlement(db: Session, sub: TenantSubscription):
    now = utcnow()
    return db.scalar(select(SubscriptionEntitlement.id).where(
        SubscriptionEntitlement.subscription_id == sub.id,
        SubscriptionEntitlement.code == "application.deploy",
        SubscriptionEntitlement.status == "active",
        (SubscriptionEntitlement.starts_at.is_(None) | (SubscriptionEntitlement.starts_at <= now)),
        (SubscriptionEntitlement.ends_at.is_(None) | (SubscriptionEntitlement.ends_at > now)),
    )) is not None


def eligible_upgrade(db: Session, instance: ApplicationInstance):
    """Return (subscription, target) or None; no writes or Docker calls."""
    if instance.status != "running":
        return None
    subscription = _matching_subscription(db, instance)
    if not subscription or not _has_deploy_entitlement(db, subscription):
        return None
    current = db.get(ApplicationVersion, instance.active_version_id)
    if not current or current.build_type == "static_web":
        return None  # Static is served as immutable assets; no Docker upgrade.
    try:
        current_number = parse_version(current.version)
    except VersionPolicyError:
        return None
    versions = list(db.scalars(select(ApplicationVersion).where(
        ApplicationVersion.application_id == instance.application_id,
        ApplicationVersion.status == "image_ready",
        ApplicationVersion.publication_status == "published",
    )))
    candidates = []
    for version in versions:
        if version.id == current.id or not is_version_technically_ready(version):
            continue
        try:
            ver = parse_version(version.version)
            if ver <= current_number:
                continue
            require_subscription_version_allowed(db=db, subscription=subscription,
                                                 target_version=version)
        except VersionPolicyError:
            continue
        build = db.scalar(select(ApplicationBuild).where(
            ApplicationBuild.application_version_id == version.id,
            ApplicationBuild.status == "ready",
            ApplicationBuild.image_ref.is_not(None),
        ).order_by(ApplicationBuild.created_at.desc()))
        if build:
            candidates.append((ver, version))
    if not candidates:
        return None
    return subscription, max(candidates, key=lambda pair: pair[0])[1]


def plan_upgrades(db: Session, *, dry_run: bool = True, limit: int = 100):
    """Published opt-in versions only; idempotent enqueue on PostgreSQL."""
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    results = []
    query = select(ApplicationInstance).where(
        ApplicationInstance.status == "running"
    ).order_by(ApplicationInstance.created_at.asc()).limit(limit)
    if not dry_run:
        query = query.with_for_update(skip_locked=True)
    instances = list(db.scalars(query))
    for instance in instances:
        choice = eligible_upgrade(db, instance)
        if not choice:
            continue
        sub, target = choice
        key = f"{instance.id}:{instance.active_version_id}:{target.id}"
        if db.scalar(select(RuntimeUpgradeJob.id).where(RuntimeUpgradeJob.idempotency_key == key)):
            continue
        # At most one queued/running job per instance; prevents staged races.
        if db.scalar(select(RuntimeUpgradeJob.id).where(
            RuntimeUpgradeJob.instance_id == instance.id,
            RuntimeUpgradeJob.status.in_(("queued", "running", "needs_reconciliation")),
        )):
            continue
        results.append({"tenantId": str(instance.tenant_id),
                        "instanceId": str(instance.id), "from": str(instance.active_version_id),
                        "to": str(target.id), "subscriptionId": str(sub.id)})
        if dry_run:
            continue
        job = RuntimeUpgradeJob(
            idempotency_key=key, tenant_id=instance.tenant_id,
            instance_id=instance.id, subscription_id=sub.id,
            source_version_id=instance.active_version_id,
            target_version_id=target.id, status="queued",
        )
        db.add(job)
        db.flush()
        record_audit_event(db, action="application.auto_upgrade.queued",
            resource_type="runtime_upgrade_job", resource_id=job.id,
            tenant_id=instance.tenant_id, outcome="success",
            message="Automatic upgrade queued by authorized system worker.",
            metadata={"systemActor":"runtime_worker", "instanceId":str(instance.id),
                      "targetVersionId":str(target.id)})
    if not dry_run:
        db.commit()
    return results


def claim_one(db: Session, worker_id: str):
    """Non-overlapping durable claim; expired executions quarantine for review."""
    import re
    if not isinstance(worker_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', worker_id):
        raise ValueError('R06_WORKER_ID_INVALID')
    now = utcnow()
    expired = list(db.scalars(select(RuntimeUpgradeJob).where(
        RuntimeUpgradeJob.status == "running",
        RuntimeUpgradeJob.lease_until < now,
    ).with_for_update(skip_locked=True).limit(50)))
    for job in expired:
        job.status = "needs_reconciliation"  # NEVER automatically retry unknown Docker outcome.
        job.last_error_code = "LEASE_EXPIRED_REVIEW_REQUIRED"
        record_audit_event(db, action="application.auto_upgrade.reconciliation_required",
            resource_type="runtime_upgrade_job", resource_id=job.id,
            tenant_id=job.tenant_id, outcome="failed",
            message="Expired auto-upgrade lease requires operator review.",
            metadata={"systemActor":"runtime_worker","code":"LEASE_EXPIRED_REVIEW_REQUIRED"})
    job = db.scalar(select(RuntimeUpgradeJob).where(
        RuntimeUpgradeJob.status == "queued",
    ).order_by(RuntimeUpgradeJob.created_at.asc()).with_for_update(skip_locked=True).limit(1))
    if not job:
        db.commit()
        return None
    job.status = "running"
    job.claimed_by = worker_id
    job.lease_until = now + LEASE
    job.attempts += 1
    db.commit()
    return job.id


def execute_one(db: Session, job_id: uuid.UUID, *, expected_worker_id: str | None = None):
    """Revalidate consent and policy before shared internal lifecycle executor."""
    from services.api.app.services.runtime_upgrade_executor import perform_instance_upgrade
    from fastapi import HTTPException
    job = db.get(RuntimeUpgradeJob, job_id)
    if not job or job.status != "running":
        return "SKIPPED"
    if expected_worker_id is not None:
        # Reject stale or foreign claims before any Docker side effect.
        if job.claimed_by != expected_worker_id or job.lease_until is None:
            return "SKIPPED"
        lease = job.lease_until
        if lease.tzinfo is None:
            lease = lease.replace(tzinfo=timezone.utc)
        if lease <= utcnow():
            return "SKIPPED"
    instance = db.get(ApplicationInstance, job.instance_id)
    valid = (
        instance is not None and instance.tenant_id == job.tenant_id
        and instance.status == "running"
        and instance.active_version_id == job.source_version_id
    )
    choice = eligible_upgrade(db, instance) if valid else None
    # Revalidate EXACT queued target and consent; selection must not drift.
    if not choice or choice[0].id != job.subscription_id or choice[1].id != job.target_version_id:
        job.status = "deferred"
        job.last_error_code = "ELIGIBILITY_CHANGED"
        job.completed_at = utcnow()
        db.commit()
        return "DEFERRED"
    try:
        perform_instance_upgrade(db=db, instance_id=instance.id,
                                 target_version_id=job.target_version_id,
                                 actor_user_id=None, system_actor=True,
                                 authorized_subscription_id=job.subscription_id)
    except Exception as exc:
        # The executor may have committed a candidate or retired an old Docker
        # container before raising. Known 4xx lifecycle failures are recorded
        # as failed. Unknown / server failures have an UNCERTAIN Docker outcome:
        # quarantine them, never classify as a safe retryable failure.
        db.rollback()
        job = db.get(RuntimeUpgradeJob, job_id)
        known_failure = isinstance(exc, HTTPException) and exc.status_code in (400, 403, 404, 409, 422)
        if job:
            if known_failure:
                job.status = "failed"
                job.last_error_code = "HTTP_" + str(exc.status_code)
                job.completed_at = utcnow()
                job.lease_until = None
            else:
                job.status = "needs_reconciliation"
                job.last_error_code = "UNKNOWN_DOCKER_OUTCOME_REVIEW_REQUIRED"
                # Preserve original lease and do not mark completed. A trusted
                # operator must compare deployment rows with actual containers.
            record_audit_event(db,
                action=("application.auto_upgrade.failed" if known_failure
                        else "application.auto_upgrade.reconciliation_required"),
                resource_type="runtime_upgrade_job", resource_id=job.id,
                tenant_id=job.tenant_id, outcome="failed",
                message=("Known automatic-upgrade failure." if known_failure
                         else "Uncertain automatic-upgrade outcome. Operator reconciliation required."),
                metadata={"systemActor":"runtime_worker","code":job.last_error_code})
            db.commit()
        return "FAILED" if known_failure else "NEEDS_RECONCILIATION"
    db.rollback()  # discard stale in-memory job after executor commits
    job = db.get(RuntimeUpgradeJob, job_id)
    # The shared executor may commit; do not stamp success if ownership changed.
    if job is None or (expected_worker_id is not None and
                       (job.status != "running" or job.claimed_by != expected_worker_id)):
        return "NEEDS_RECONCILIATION"
    job.status = "succeeded"
    job.completed_at = utcnow()
    job.lease_until = None
    db.commit()
    return "SUCCEEDED"
