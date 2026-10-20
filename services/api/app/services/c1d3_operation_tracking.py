"""Durable lifecycle journal for AUGMIS-owned deployment operations.

The calling route/service must already have enforced tenant RBAC, subscription,
quotas, and upgrade policy. This module never performs Docker operations or
replays an incomplete operation. Its journal is durable before Docker launch.
"""
from __future__ import annotations

import uuid
from sqlalchemy.orm import Session
from services.api.app.models.platform import ApplicationDeployment, ApplicationInstance
from services.api.app.services.deployment_reliability import (
    reserve_journal, claim_journal, advance_stage, record_failure,
)


def journal_reserved(db: Session, *, instance: ApplicationInstance,
                     deployment: ApplicationDeployment) -> None:
    """Reserve atomically with deployment row in caller's next commit."""
    db.flush()  # Ensure IDs exist; no external side-effects.
    reserve_journal(db, deployment_id=deployment.id,
                    tenant_id=instance.tenant_id, instance_id=instance.id)


def journal_launch_started(db: Session, *, deployment: ApplicationDeployment) -> str:
    """Commit an owned 30-minute lease before calling existing runtime engine."""
    owner = 'sync-' + uuid.uuid4().hex
    claim_journal(db, deployment_id=deployment.id, worker=owner,
                  lease_seconds=1800)
    advance_stage(db, deployment_id=deployment.id, worker=owner,
                  stage='runtime_starting')
    db.commit()
    return owner


def journal_runtime_ready(db: Session, *, deployment: ApplicationDeployment,
                          owner: str, result: dict) -> None:
    """Container and existing engine health passed; retain candidate for promotion.

    This is the existing engine's runtime/relay readiness, NOT proof of a
    browser-level authenticated session. C1-D2 independently checks signed
    gateway behavior on the immutable image; live session tests remain C1-D4.
    """
    if not isinstance(result, dict) or not all(
        isinstance(result.get(k), str) and result.get(k)
        for k in ('container_id','container_name','runtime_url','health_url')
    ):
        raise ValueError('C1D3_RUNTIME_RESULT_INCOMPLETE')
    advance_stage(db, deployment_id=deployment.id, worker=owner,
                  stage='health_checking')
    advance_stage(db, deployment_id=deployment.id, worker=owner,
                  stage='gateway_verifying')
    # Preserve minimal returned identity ahead of any old-container removal.
    deployment.container_id = result['container_id']
    deployment.container_name = result['container_name']
    deployment.runtime_url = result['runtime_url']
    db.commit()


def journal_promoted(db: Session, *, deployment: ApplicationDeployment,
                     owner: str) -> None:
    """Call only with the successful metadata promotion in the same commit."""
    if deployment.status != "running" or deployment.health_status != "healthy":
        raise ValueError("C1D3_PROMOTION_NOT_HEALTHY")
    advance_stage(db, deployment_id=deployment.id, worker=owner,
                  stage='active')


def journal_failed(db: Session, *, deployment: ApplicationDeployment,
                   owner: str, code: str) -> None:
    """Record a stable error code; keep live/resources intact for reconciliation."""
    record_failure(db, deployment_id=deployment.id, worker=owner,
                   failure_code=code)
