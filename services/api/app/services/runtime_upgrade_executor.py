"""Canonical B1/B2 upgrade lifecycle shared by tenant API and system worker.

The system worker is not a user and cannot impersonate one. Its caller
validates opt-in and tenant entitlement before invoking this function; this
function revalidates commercial permissions and locks the instance again.
"""
import re
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from services.api.app.models.platform import ApplicationInstance, ApplicationVersion, ApplicationBuild, ApplicationDeployment
from services.api.app.services.entitlement_service import (require_active_subscription, require_active_entitlement, EntitlementError)
from services.api.app.services.version_policy_service import (require_subscription_version_allowed, VersionPolicyError)
from services.api.app.services.deployment_engine import DeploymentError, stop_container
from services.api.app.services.runtime_log_archive import archive_before_removal, archive_failed_start
from services.api.app.services.runtime_controls_service import start_scoped_container
from services.api.app.services.c1d3_operation_tracking import (
    journal_reserved, journal_launch_started, journal_runtime_ready,
    journal_promoted, journal_failed,
)
from services.api.app.services.audit_service import record_audit_event

def safe_name(value: str) -> str:
    value = re.sub(r"[^a-z0-9-]", "-", value.lower())
    return re.sub(r"-+", "-", value).strip("-")


def perform_instance_upgrade(*, db: Session, instance_id: uuid.UUID,
                             target_version_id: uuid.UUID,
                             actor_user_id: uuid.UUID | None,
                             system_actor: bool = False,
                             authorized_subscription_id: uuid.UUID | None = None,
                             sync_subscription_baseline: bool = False):
    # =====================================================
    # 1. LOAD INSTANCE
    # =====================================================

    instance = db.scalar(
        select(ApplicationInstance)
        .where(ApplicationInstance.id == instance_id)
        .with_for_update()
    )

    if not instance:

        raise HTTPException(
            status_code=404,
            detail="Instance not found",
        )

    if instance.status != "running":

        raise HTTPException(
            status_code=409,
            detail=(
                "Only a running instance "
                "can be upgraded."
            ),
        )

    # =====================================================
    # 3. LOAD CURRENT + TARGET VERSION
    # =====================================================

    current_version = db.get(
        ApplicationVersion,
        instance.active_version_id,
    )

    if not current_version:

        raise HTTPException(
            status_code=409,
            detail="Current application version not found",
        )

    target_version = db.get(
        ApplicationVersion,
        target_version_id,
    )

    if not target_version:

        raise HTTPException(
            status_code=404,
            detail="Target application version not found",
        )

    if (
        target_version.application_id
        != instance.application_id
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "Target version belongs to "
                "another application."
            ),
        )

    if target_version.status != "image_ready":

        raise HTTPException(
            status_code=409,
            detail=(
                "Target application version "
                "is not image_ready."
            ),
        )

    if target_version.id == current_version.id:

        raise HTTPException(
            status_code=409,
            detail=(
                "Instance is already running "
                "the requested version."
            ),
        )

    # =====================================================
    # 4. COMMERCIAL AUTHORIZATION
    # =====================================================

    try:

        subscription = require_active_subscription(
            db=db,
            tenant_id=instance.tenant_id,
            application_id=instance.application_id,
        )
        if authorized_subscription_id is not None and subscription.id != authorized_subscription_id:
            raise HTTPException(status_code=403, detail="Subscription binding changed")

        require_active_entitlement(
            db=db,
            tenant_id=instance.tenant_id,
            application_id=instance.application_id,
            entitlement_code="application.deploy",
        )

        require_subscription_version_allowed(
            db=db,
            subscription=subscription,
            target_version=target_version,
        )

    except (
        EntitlementError,
        VersionPolicyError,
    ) as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # Release upgrades are explicitly developer/operator initiated. Publication
    # and immutable-build qualification are checked BEFORE Docker is touched.
    # The existing low-level upgrade API and trusted auto-upgrade worker retain
    # their previous behavior when sync_subscription_baseline=False.
    if sync_subscription_baseline:
        from services.api.app.services.version_policy_service import parse_version
        from services.api.app.services.c1d2_automatic_qualification import (
            require_passing_build, QualificationGateError,
        )
        if subscription.version_policy != 'same_major' or subscription.pinned_version_id is not None:
            raise HTTPException(status_code=409, detail='C1D3_RELEASE_POLICY_NOT_SUPPORTED')
        if target_version.publication_status != 'published':
            raise HTTPException(status_code=409, detail='C1D3_TARGET_NOT_PUBLISHED')
        baseline = db.get(ApplicationVersion, subscription.baseline_version_id)
        if baseline is None or parse_version(target_version.version) < parse_version(baseline.version):
            raise HTTPException(status_code=409, detail='C1D3_BASELINE_DOWNGRADE_DENIED')
        if parse_version(target_version.version) <= parse_version(current_version.version):
            raise HTTPException(status_code=409, detail='C1D3_UPGRADE_MUST_ADVANCE_VERSION')
        try:
            require_passing_build(db, version=target_version)
        except QualificationGateError as error:
            raise HTTPException(status_code=409, detail=error.code) from error

    # =====================================================
    # 5. TARGET BUILD
    # =====================================================

    target_build = db.scalar(
        select(ApplicationBuild)
        .where(
            ApplicationBuild.application_version_id
            == target_version.id,

            ApplicationBuild.status
            == "ready",
        )
        .order_by(
            ApplicationBuild.created_at.desc(),
        )
    )

    if not target_build:

        raise HTTPException(
            status_code=409,
            detail=(
                "No ready build found "
                "for target version."
            ),
        )

    if not target_build.image_ref:

        raise HTTPException(
            status_code=409,
            detail=(
                "Target build has no image reference."
            ),
        )

    # =====================================================
    # 6. CURRENT RUNNING DEPLOYMENT
    # =====================================================

    current_deployment = db.scalar(
        select(ApplicationDeployment)
        .where(
            ApplicationDeployment.instance_id
            == instance.id,

            ApplicationDeployment.status
            == "running",
        )
        .order_by(
            ApplicationDeployment.created_at.desc(),
        )
    )

    if not current_deployment:

        raise HTTPException(
            status_code=409,
            detail=(
                "Instance has no running deployment."
            ),
        )

    if not current_deployment.container_name:

        raise HTTPException(
            status_code=409,
            detail=(
                "Current deployment has no container."
            ),
        )

    # Prevent overlapping upgrade operations.

    existing_candidate = db.scalar(
        select(ApplicationDeployment)
        .where(
            ApplicationDeployment.instance_id
            == instance.id,

            ApplicationDeployment.status
            == "deploying",
        )
    )

    if existing_candidate:

        raise HTTPException(
            status_code=409,
            detail=(
                "An upgrade/deployment is already "
                "in progress for this instance."
            ),
        )

    # =====================================================
    # 7. CREATE CANDIDATE DEPLOYMENT
    # =====================================================

    short_id = uuid.uuid4().hex[:8]

    candidate_name = safe_name(
        f"augmis-upgrade-"
        f"{instance.instance_key}-"
        f"{short_id}"
    )

    candidate = ApplicationDeployment(
        instance_id=instance.id,
        application_version_id=target_version.id,
        build_id=target_build.id,
        status="deploying",
        container_name=candidate_name,
        health_status="starting",
    )

    db.add(candidate)
    journal_reserved(db, instance=instance, deployment=candidate)

    instance.status = "upgrading"

    db.commit()

    db.refresh(candidate)
    journal_owner = journal_launch_started(db, deployment=candidate)

    # =====================================================
    # 8. START CANDIDATE CONTAINER
    #
    # OLD CONTAINER REMAINS RUNNING.
    # =====================================================

    try:

        result = start_scoped_container(
            db=db, instance=instance, deployment=candidate, build=target_build,
            manifest=target_version.manifest,
            container_name=candidate_name,
            labels={
                "augmis.managed": "true",

                "augmis.instance_id":
                    str(instance.id),

                "augmis.tenant_id":
                    str(instance.tenant_id),

                "augmis.application_id":
                    str(instance.application_id),

                "augmis.upgrade_candidate":
                    "true",
            },
        )

    except DeploymentError as error:

        # Candidate failed.
        # Old deployment was never stopped.

        candidate.status = "failed"
        candidate.health_status = "unhealthy"
        candidate.error_message = str(error)
        archive_failed_start(candidate, error)
        journal_failed(db, deployment=candidate, owner=journal_owner,
                       code='C1D3_UPGRADE_LAUNCH_FAILED')

        instance.status = "running"

        db.commit()

        raise HTTPException(
            status_code=422,
            detail={
                "message":
                    "Upgrade candidate failed health check",

                "candidateDeploymentId":
                    str(candidate.id),

                "error":
                    str(error),

                "rollback":
                    "Previous deployment remains running",
            },
        ) from error

    # Persist the engine-healthy candidate and handoff stage before retiring old.
    journal_runtime_ready(db, deployment=candidate, owner=journal_owner,
                          result=result)
    # B1A: persist the healthy candidate reference before deleting the old
    # container. A crash now leaves enough DB metadata to reconcile safely.
    candidate.container_id = result["container_id"]
    candidate.container_name = result["container_name"]
    candidate.host_port = result["host_port"]
    candidate.runtime_url = result["runtime_url"]
    candidate.health_status = "healthy"
    db.commit()

    # Snapshot outgoing logs before their Docker container is deleted.
    archive_before_removal(current_deployment)
    db.commit()

    # =====================================================
    # 9. CANDIDATE IS HEALTHY
    #
    # NOW retire old container.
    # =====================================================

    try:

        stop_container(
            current_deployment.container_name,
        )

    except DeploymentError as error:

        # Old runtime could not be retired.
        # Remove the candidate and preserve the old runtime.
        archive_before_removal(candidate)
        db.commit()

        try:

            stop_container(
                result["container_name"],
            )

        except DeploymentError:
            pass

        candidate.status = "failed"
        candidate.health_status = "stopped"
        journal_failed(db, deployment=candidate, owner=journal_owner,
                       code='C1D3_UPGRADE_RETIRE_FAILED')

        candidate.error_message = (
            "Candidate was healthy but previous "
            f"deployment could not be stopped: {error}"
        )

        instance.status = "running"

        db.commit()

        raise HTTPException(
            status_code=422,
            detail={
                "message":
                    "Upgrade promotion failed",

                "error":
                    str(error),

                "rollback":
                    "Previous deployment remains active",
            },
        ) from error

    now = datetime.now(
        timezone.utc
    )

    # =====================================================
    # 10. RETIRE OLD DEPLOYMENT
    # =====================================================

    current_deployment.status = "stopped"
    current_deployment.health_status = "stopped"
    current_deployment.stopped_at = now

    # =====================================================
    # 11. PROMOTE CANDIDATE
    # =====================================================

    candidate.container_id = (
        result["container_id"]
    )

    candidate.container_name = (
        result["container_name"]
    )

    candidate.host_port = (
        result["host_port"]
    )

    candidate.runtime_url = (
        result["runtime_url"]
    )

    candidate.status = "running"
    candidate.health_status = "healthy"
    candidate.deployed_at = now

    # Logical instance now points to new version.

    instance.active_version_id = target_version.id
    instance.status = "running"
    # Publish the new default only after the healthy candidate is activated.
    # This shares the final Control Plane DB commit with active_version_id.
    if sync_subscription_baseline:
        subscription.baseline_version_id = target_version.id
        record_audit_event(
            db, action='subscription.baseline.promoted_by_release_upgrade',
            resource_type='tenant_subscription', resource_id=subscription.id,
            actor_user_id=actor_user_id, tenant_id=instance.tenant_id,
            outcome='success', message='Baseline synchronized after healthy instance upgrade.',
            metadata={'instanceId': str(instance.id), 'targetVersionId': str(target_version.id)},
        )

    record_audit_event(
        db,
        action="application.upgrade",
        resource_type="application_instance",
        resource_id=instance.id,
        actor_user_id=actor_user_id,
        tenant_id=instance.tenant_id,
        outcome="success",
        message="Application instance upgraded successfully.",
        metadata={
        "deploymentId":
            str(candidate.id),

        "fromVersionId":
            str(current_version.id),

        "fromVersion":
            current_version.version,

        "toVersionId":
            str(target_version.id),

        "toVersion":
            target_version.version,

        "containerName":
            candidate.container_name,

        "initiatedBy": "system.runtime_worker" if system_actor else "tenant_user",
        },
    )

    journal_promoted(db, deployment=candidate, owner=journal_owner)
    db.commit()

    return {
        "status": "UPGRADED",

        "instance": {
            "id": str(instance.id),
            "name": instance.name,
            "status": instance.status,
        },

        "previousVersion": {
            "id": str(current_version.id),
            "version": current_version.version,
        },

        "activeVersion": {
            "id": str(target_version.id),
            "version": target_version.version,
        },

        "deployment": {
            "id": str(candidate.id),

            "containerId":
                candidate.container_id,

            "containerName":
                candidate.container_name,

            "hostPort":
                candidate.host_port,

            "url":
                candidate.runtime_url,

            "health":
                candidate.health_status,
        },
    }
