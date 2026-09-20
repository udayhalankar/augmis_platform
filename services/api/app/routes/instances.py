from __future__ import annotations

import re
import uuid

from datetime import (
    datetime,
    timezone,
)

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.core.auth import (
    get_current_user,
)

from services.api.app.db.session import (
    get_db,
)

from services.api.app.models.iam import (
    User,
)

from services.api.app.models.platform import (
    Application,
    ApplicationBuild,
    ApplicationDeployment,
    ApplicationInstance,
    ApplicationVersion,
    Tenant,
)

from services.api.app.schemas.instance import (
    InstanceDeployRequest,
    InstanceUpgradeRequest,
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_tenant_permission,
)

from services.api.app.services.deployment_engine import (
    DeploymentError,
    start_container,
    stop_container,
)

from services.api.app.services.entitlement_service import (
    EntitlementError,
    require_active_entitlement,
    require_active_subscription,
)

from services.api.app.services.instance_limit_service import (
    InstanceLimitError,
    require_instance_capacity,
)

from services.api.app.services.version_policy_service import (
    VersionPolicyError,
    require_subscription_version_allowed,
)


router = APIRouter(
    prefix="/api/v1",
    tags=["Runtime"],
)


def safe_name(
    value: str,
) -> str:

    value = value.lower()

    value = re.sub(
        r"[^a-z0-9-]",
        "-",
        value,
    )

    value = re.sub(
        r"-+",
        "-",
        value,
    )

    return value.strip("-")

@router.post(
    "/instances/{instance_id}/upgrade",
)
def upgrade_application_instance(
    instance_id: uuid.UUID,
    payload: InstanceUpgradeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    # =====================================================
    # 1. LOAD INSTANCE
    # =====================================================

    instance = db.get(
        ApplicationInstance,
        instance_id,
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
    # 2. RBAC
    # =====================================================

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=instance.tenant_id,
            permission_code="application.deploy",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

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
        payload.target_version_id,
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

    instance.status = "upgrading"

    db.commit()

    db.refresh(candidate)

    # =====================================================
    # 8. START CANDIDATE CONTAINER
    #
    # OLD CONTAINER REMAINS RUNNING.
    # =====================================================

    try:

        result = start_container(
            image_ref=target_build.image_ref,
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

        try:

            stop_container(
                result["container_name"],
            )

        except DeploymentError:
            pass

        candidate.status = "failed"
        candidate.health_status = "stopped"

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


@router.post(
    "/tenants/{tenant_id}/application-versions/{version_id}/deploy",
    status_code=201,
)
def deploy_application(
    tenant_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: InstanceDeployRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    # =====================================================
    # 1. TENANT
    # =====================================================

    tenant = db.get(
        Tenant,
        tenant_id,
    )

    if not tenant:

        raise HTTPException(
            status_code=404,
            detail="Tenant not found",
        )

    if tenant.status != "active":

        raise HTTPException(
            status_code=409,
            detail="Tenant is not active",
        )

    # =====================================================
    # 2. RBAC
    # =====================================================

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=tenant.id,
            permission_code="application.deploy",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 3. APPLICATION VERSION
    # =====================================================

    version = db.get(
        ApplicationVersion,
        version_id,
    )

    if not version:

        raise HTTPException(
            status_code=404,
            detail="Application version not found",
        )

    if version.status != "image_ready":

        raise HTTPException(
            status_code=409,
            detail=(
                "Application version does not "
                "have a ready image."
            ),
        )

    application = db.get(
        Application,
        version.application_id,
    )

    if not application:

        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    # =====================================================
    # 4. SUBSCRIPTION + ENTITLEMENT + VERSION POLICY
    # =====================================================

    try:

        subscription = require_active_subscription(
            db=db,
            tenant_id=tenant.id,
            application_id=application.id,
        )

        entitlement = require_active_entitlement(
            db=db,
            tenant_id=tenant.id,
            application_id=application.id,
            entitlement_code="application.deploy",
        )

        require_subscription_version_allowed(
            db=db,
            subscription=subscription,
            target_version=version,
        )

    except (
        EntitlementError,
        VersionPolicyError,
    ) as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 5. INSTANCE LIMIT
    #
    # MUST happen before ApplicationInstance is created.
    # =====================================================

    try:

        require_instance_capacity(
            db=db,
            tenant_id=tenant.id,
            application_id=application.id,
            entitlement=entitlement,
        )

    except InstanceLimitError as error:

        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error

    # =====================================================
    # 6. READY BUILD
    # =====================================================

    build = db.scalar(
        select(ApplicationBuild)
        .where(
            ApplicationBuild.application_version_id
            == version.id,

            ApplicationBuild.status
            == "ready",
        )
        .order_by(
            ApplicationBuild.created_at.desc(),
        )
    )

    if not build:

        raise HTTPException(
            status_code=409,
            detail="No ready build found",
        )

    if not build.image_ref:

        raise HTTPException(
            status_code=409,
            detail="Build has no image reference",
        )

    # =====================================================
    # 7. CREATE LOGICAL INSTANCE
    # =====================================================

    short_id = uuid.uuid4().hex[:8]

    instance_key = (
        f"{tenant.slug}-"
        f"{application.app_key}-"
        f"{short_id}"
    )

    instance_name = (
        payload.name
        or f"{application.name} - {tenant.name}"
    )

    instance = ApplicationInstance(
        tenant_id=tenant.id,
        application_id=application.id,
        active_version_id=version.id,
        instance_key=instance_key,
        name=instance_name,
        status="provisioning",
    )

    db.add(instance)

    db.flush()

    # =====================================================
    # 8. CREATE DEPLOYMENT RECORD
    # =====================================================

    container_name = safe_name(
        f"augmis-"
        f"{tenant.slug}-"
        f"{application.app_key}-"
        f"{short_id}"
    )

    deployment = ApplicationDeployment(
        instance_id=instance.id,
        application_version_id=version.id,
        build_id=build.id,
        status="deploying",
        container_name=container_name,
        health_status="starting",
    )

    db.add(deployment)

    # This commit releases the advisory transaction lock,
    # but the new instance is already persisted as
    # "provisioning", which is counted as active capacity.
    db.commit()

    db.refresh(instance)
    db.refresh(deployment)

    # =====================================================
    # 9. START CONTAINER
    # =====================================================

    try:

        result = start_container(
            image_ref=build.image_ref,
            manifest=version.manifest,
            container_name=container_name,
            labels={
                "augmis.managed": "true",

                "augmis.instance_id":
                    str(instance.id),

                "augmis.tenant_id":
                    str(tenant.id),

                "augmis.application_id":
                    str(application.id),
            },
        )

    except DeploymentError as error:

        instance.status = "failed"

        deployment.status = "failed"

        deployment.health_status = (
            "unhealthy"
        )

        deployment.error_message = (
            str(error)
        )

        db.commit()

        raise HTTPException(
            status_code=422,
            detail={
                "message":
                    "Application deployment failed",

                "deploymentId":
                    str(deployment.id),

                "error":
                    str(error),
            },
        ) from error

    # =====================================================
    # 10. SUCCESS
    # =====================================================

    deployment.container_id = (
        result["container_id"]
    )

    deployment.container_name = (
        result["container_name"]
    )

    deployment.host_port = (
        result["host_port"]
    )

    deployment.runtime_url = (
        result["runtime_url"]
    )

    deployment.status = "running"

    deployment.health_status = "healthy"

    deployment.deployed_at = datetime.now(
        timezone.utc,
    )

    instance.status = "running"

    db.commit()

    return {
        "status": "RUNNING",

        "tenant": {
            "id": str(tenant.id),
            "name": tenant.name,
        },

        "application": {
            "id": str(application.id),
            "name": application.name,
        },

        "instance": {
            "id": str(instance.id),

            "instanceKey":
                instance.instance_key,

            "name":
                instance.name,

            "status":
                instance.status,
        },

        "deployment": {
            "id":
                str(deployment.id),

            "containerId":
                deployment.container_id,

            "containerName":
                deployment.container_name,

            "hostPort":
                deployment.host_port,

            "url":
                deployment.runtime_url,

            "health":
                deployment.health_status,
        },
    }


@router.get(
    "/tenants/{tenant_id}/instances",
)
def list_tenant_instances(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    tenant = db.get(
        Tenant,
        tenant_id,
    )

    if not tenant:

        raise HTTPException(
            status_code=404,
            detail="Tenant not found",
        )

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=tenant.id,
            permission_code="application.instance.view",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    instances = list(
        db.scalars(
            select(ApplicationInstance)
            .where(
                ApplicationInstance.tenant_id
                == tenant_id,
            )
            .order_by(
                ApplicationInstance
                .created_at
                .desc(),
            )
        )
    )

    return [
        {
            "id":
                str(instance.id),

            "applicationId":
                str(instance.application_id),

            "versionId":
                str(instance.active_version_id),

            "instanceKey":
                instance.instance_key,

            "name":
                instance.name,

            "status":
                instance.status,
        }

        for instance in instances
    ]



@router.get(
    "/instances/{instance_id}",
)
def get_application_instance(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    instance = db.get(
        ApplicationInstance,
        instance_id,
    )

    if not instance:

        raise HTTPException(
            status_code=404,
            detail="Instance not found",
        )

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=instance.tenant_id,
            permission_code="application.instance.view",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    application = db.get(
        Application,
        instance.application_id,
    )

    version = db.get(
        ApplicationVersion,
        instance.active_version_id,
    )

    deployment = db.scalar(
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

    return {
        "id": str(instance.id),

        "instanceKey":
            instance.instance_key,

        "name":
            instance.name,

        "status":
            instance.status,

        "tenantId":
            str(instance.tenant_id),

        "application": {
            "id": str(application.id)
            if application
            else None,

            "name": application.name
            if application
            else None,
        },

        "activeVersion": {
            "id": str(version.id)
            if version
            else None,

            "version": version.version
            if version
            else None,
        },

        "runtime": (
            {
                "deploymentId":
                    str(deployment.id),

                "containerId":
                    deployment.container_id,

                "containerName":
                    deployment.container_name,

                "hostPort":
                    deployment.host_port,

                "url":
                    deployment.runtime_url,

                "health":
                    deployment.health_status,

                "deployedAt":
                    deployment.deployed_at,
            }

            if deployment

            else None
        ),

        "createdAt":
            instance.created_at,
    }


@router.get(
    "/instances/{instance_id}/deployments",
)
def list_instance_deployments(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    # =====================================================
    # 1. LOAD INSTANCE
    # =====================================================

    instance = db.get(
        ApplicationInstance,
        instance_id,
    )

    if not instance:

        raise HTTPException(
            status_code=404,
            detail="Instance not found",
        )

    # =====================================================
    # 2. RBAC
    # =====================================================

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=instance.tenant_id,
            permission_code="application.instance.view",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 3. DEPLOYMENT HISTORY
    # =====================================================

    rows = db.execute(
        select(
            ApplicationDeployment,
            ApplicationVersion,
        )
        .join(
            ApplicationVersion,
            ApplicationVersion.id
            == ApplicationDeployment.application_version_id,
        )
        .where(
            ApplicationDeployment.instance_id
            == instance.id
        )
        .order_by(
            ApplicationDeployment.created_at.desc()
        )
    ).all()

    # =====================================================
    # 4. RESPONSE
    # =====================================================

    return [
        {
            "deploymentId":
                str(deployment.id),

            "version": {
                "id":
                    str(version.id),

                "version":
                    version.version,
            },

            "status":
                deployment.status,

            "health":
                deployment.health_status,

            "containerId":
                deployment.container_id,

            "containerName":
                deployment.container_name,

            "hostPort":
                deployment.host_port,

            "url":
                deployment.runtime_url,

            "error":
                deployment.error_message,

            "deployedAt":
                deployment.deployed_at,

            "stoppedAt":
                deployment.stopped_at,

            "createdAt":
                deployment.created_at,
        }

        for (
            deployment,
            version,
        ) in rows
    ]


# =========================================================
# ROLLBACK APPLICATION INSTANCE
# =========================================================

@router.post(
    "/instances/{instance_id}/rollback",
)
def rollback_application_instance(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    # =====================================================
    # 1. LOAD INSTANCE
    # =====================================================

    instance = db.get(
        ApplicationInstance,
        instance_id,
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
                "can be rolled back."
            ),
        )

    # =====================================================
    # 2. RBAC
    # =====================================================

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=instance.tenant_id,
            permission_code="application.deploy",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 3. CURRENT VERSION
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

    # =====================================================
    # 4. CURRENT RUNNING DEPLOYMENT
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
            ApplicationDeployment.created_at.desc()
        )
    )

    if not current_deployment:

        raise HTTPException(
            status_code=409,
            detail="Instance has no running deployment.",
        )

    if not current_deployment.container_name:

        raise HTTPException(
            status_code=409,
            detail="Current deployment has no container.",
        )

    # =====================================================
    # 5. PREVENT CONCURRENT DEPLOYMENT
    # =====================================================

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
                "A deployment operation is already "
                "in progress for this instance."
            ),
        )

    # =====================================================
    # 6. FIND PREVIOUS SUCCESSFUL VERSION
    # =====================================================

    previous_deployment = db.scalar(
        select(ApplicationDeployment)
        .where(
            ApplicationDeployment.instance_id
            == instance.id,

            ApplicationDeployment.id
            != current_deployment.id,

            ApplicationDeployment.application_version_id
            != current_version.id,

            ApplicationDeployment.deployed_at.is_not(
                None
            ),

            ApplicationDeployment.error_message.is_(
                None
            ),
        )
        .order_by(
            ApplicationDeployment.deployed_at.desc()
        )
    )

    if not previous_deployment:

        raise HTTPException(
            status_code=409,
            detail=(
                "No previous successful deployment "
                "is available for rollback."
            ),
        )

    rollback_version = db.get(
        ApplicationVersion,
        previous_deployment.application_version_id,
    )

    if not rollback_version:

        raise HTTPException(
            status_code=409,
            detail="Rollback version no longer exists.",
        )

    if rollback_version.status != "image_ready":

        raise HTTPException(
            status_code=409,
            detail=(
                "Rollback version is not image_ready."
            ),
        )

    # =====================================================
    # 7. SUBSCRIPTION + ENTITLEMENT + VERSION POLICY
    # =====================================================

    try:

        subscription = require_active_subscription(
            db=db,
            tenant_id=instance.tenant_id,
            application_id=instance.application_id,
        )

        require_active_entitlement(
            db=db,
            tenant_id=instance.tenant_id,
            application_id=instance.application_id,
            entitlement_code="application.deploy",
        )

        require_subscription_version_allowed(
            db=db,
            subscription=subscription,
            target_version=rollback_version,
        )

    except (
        EntitlementError,
        VersionPolicyError,
    ) as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 8. READY BUILD FOR ROLLBACK VERSION
    # =====================================================

    rollback_build = db.scalar(
        select(ApplicationBuild)
        .where(
            ApplicationBuild.application_version_id
            == rollback_version.id,

            ApplicationBuild.status
            == "ready",
        )
        .order_by(
            ApplicationBuild.created_at.desc()
        )
    )

    if not rollback_build:

        raise HTTPException(
            status_code=409,
            detail=(
                "No ready build exists "
                "for rollback version."
            ),
        )

    if not rollback_build.image_ref:

        raise HTTPException(
            status_code=409,
            detail=(
                "Rollback build has no image reference."
            ),
        )

    # =====================================================
    # 9. CREATE FRESH ROLLBACK DEPLOYMENT
    # =====================================================

    short_id = uuid.uuid4().hex[:8]

    candidate_name = safe_name(
        f"augmis-rollback-"
        f"{instance.instance_key}-"
        f"{short_id}"
    )

    candidate = ApplicationDeployment(
        instance_id=instance.id,
        application_version_id=rollback_version.id,
        build_id=rollback_build.id,
        status="deploying",
        container_name=candidate_name,
        health_status="starting",
    )

    db.add(candidate)

    instance.status = "upgrading"

    db.commit()

    db.refresh(candidate)

    # =====================================================
    # 10. START ROLLBACK CANDIDATE
    #
    # Existing runtime remains alive until candidate
    # passes health check.
    # =====================================================

    try:

        result = start_container(
            image_ref=rollback_build.image_ref,
            manifest=rollback_version.manifest,
            container_name=candidate_name,
            labels={
                "augmis.managed": "true",

                "augmis.instance_id":
                    str(instance.id),

                "augmis.tenant_id":
                    str(instance.tenant_id),

                "augmis.application_id":
                    str(instance.application_id),

                "augmis.rollback_candidate":
                    "true",
            },
        )

    except DeploymentError as error:

        candidate.status = "failed"
        candidate.health_status = "unhealthy"
        candidate.error_message = str(error)

        instance.status = "running"

        db.commit()

        raise HTTPException(
            status_code=422,
            detail={
                "message":
                    "Rollback candidate failed health check",

                "candidateDeploymentId":
                    str(candidate.id),

                "error":
                    str(error),

                "rollback":
                    "Current deployment remains running",
            },
        ) from error

    # =====================================================
    # 11. CANDIDATE HEALTHY — RETIRE CURRENT CONTAINER
    # =====================================================

    try:

        stop_container(
            current_deployment.container_name,
        )

    except DeploymentError as error:

        # Remove rollback candidate and preserve current
        # runtime if promotion cannot complete.

        try:

            stop_container(
                result["container_name"],
            )

        except DeploymentError:
            pass

        candidate.status = "failed"
        candidate.health_status = "stopped"

        candidate.error_message = (
            "Rollback candidate was healthy but "
            "current deployment could not be stopped: "
            f"{error}"
        )

        instance.status = "running"

        db.commit()

        raise HTTPException(
            status_code=422,
            detail={
                "message":
                    "Rollback promotion failed",

                "error":
                    str(error),

                "rollback":
                    "Current deployment remains active",
            },
        ) from error

    now = datetime.now(
        timezone.utc
    )

    # =====================================================
    # 12. RETIRE PREVIOUS ACTIVE DEPLOYMENT
    # =====================================================

    current_deployment.status = "stopped"

    current_deployment.health_status = "stopped"

    current_deployment.stopped_at = now

    # =====================================================
    # 13. PROMOTE ROLLBACK DEPLOYMENT
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

    instance.active_version_id = (
        rollback_version.id
    )

    instance.status = "running"

    db.commit()

    db.refresh(instance)
    db.refresh(candidate)

    # =====================================================
    # 14. RESPONSE
    # =====================================================

    return {
        "status": "ROLLED_BACK",

        "instance": {
            "id": str(instance.id),
            "name": instance.name,
            "status": instance.status,
        },

        "fromVersion": {
            "id": str(current_version.id),
            "version": current_version.version,
        },

        "toVersion": {
            "id": str(rollback_version.id),
            "version": rollback_version.version,
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


# =========================================================
# STOP APPLICATION INSTANCE
# =========================================================

@router.post(
    "/instances/{instance_id}/stop",
)
def stop_application_instance(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    # =====================================================
    # 1. LOAD INSTANCE
    # =====================================================

    instance = db.get(
        ApplicationInstance,
        instance_id,
    )

    if not instance:

        raise HTTPException(
            status_code=404,
            detail="Instance not found",
        )

    # =====================================================
    # 2. RBAC
    #
    # Stop must remain possible even when a subscription
    # is suspended/cancelled.
    # =====================================================

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=instance.tenant_id,
            permission_code="application.instance.stop",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 3. FIND RUNNING DEPLOYMENT
    # =====================================================

    deployment = db.scalar(
        select(ApplicationDeployment)
        .where(
            ApplicationDeployment.instance_id
            == instance.id,

            ApplicationDeployment.status
            == "running",
        )
        .order_by(
            ApplicationDeployment.created_at.desc()
        )
    )

    if not deployment:

        # Make stop idempotent for an already stopped
        # logical instance.

        if instance.status == "stopped":

            return {
                "status": "STOPPED",
                "instanceId": str(instance.id),
            }

        raise HTTPException(
            status_code=409,
            detail="No running deployment found.",
        )

    if not deployment.container_name:

        raise HTTPException(
            status_code=409,
            detail="Deployment has no container.",
        )

    # =====================================================
    # 4. STOP CONTAINER
    # =====================================================

    try:

        stop_container(
            deployment.container_name,
        )

    except DeploymentError as error:

        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    now = datetime.now(
        timezone.utc
    )

    # =====================================================
    # 5. UPDATE CONTROL-PLANE STATE
    # =====================================================

    deployment.status = "stopped"

    deployment.health_status = "stopped"

    deployment.stopped_at = now

    instance.status = "stopped"

    db.commit()

    return {
        "status": "STOPPED",

        "instanceId":
            str(instance.id),

        "deploymentId":
            str(deployment.id),

        "stoppedAt":
            deployment.stopped_at,
    }


    # =========================================================
# RESTART APPLICATION INSTANCE
# =========================================================

@router.post(
    "/instances/{instance_id}/restart",
)
def restart_application_instance(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    # =====================================================
    # 1. LOAD + LOCK INSTANCE
    # =====================================================

    instance = db.scalar(
        select(ApplicationInstance)
        .where(
            ApplicationInstance.id
            == instance_id
        )
        .with_for_update()
    )

    if not instance:

        raise HTTPException(
            status_code=404,
            detail="Instance not found",
        )

    if instance.status != "stopped":

        raise HTTPException(
            status_code=409,
            detail=(
                "Only a stopped instance "
                "can be restarted."
            ),
        )

    # =====================================================
    # 2. RBAC
    # =====================================================

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=instance.tenant_id,
            permission_code="application.deploy",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 3. LOAD ACTIVE VERSION
    # =====================================================

    version = db.get(
        ApplicationVersion,
        instance.active_version_id,
    )

    if not version:

        raise HTTPException(
            status_code=409,
            detail=(
                "Instance active version "
                "does not exist."
            ),
        )

    if version.status != "image_ready":

        raise HTTPException(
            status_code=409,
            detail=(
                "Instance active version "
                "is not image_ready."
            ),
        )

    # =====================================================
    # 4. SUBSCRIPTION + ENTITLEMENT + VERSION POLICY
    # =====================================================

    try:

        subscription = require_active_subscription(
            db=db,
            tenant_id=instance.tenant_id,
            application_id=instance.application_id,
        )

        entitlement = require_active_entitlement(
            db=db,
            tenant_id=instance.tenant_id,
            application_id=instance.application_id,
            entitlement_code="application.deploy",
        )

        require_subscription_version_allowed(
            db=db,
            subscription=subscription,
            target_version=version,
        )

    except (
        EntitlementError,
        VersionPolicyError,
    ) as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 5. INSTANCE CAPACITY
    #
    # Restart turns a stopped logical instance back into an
    # active instance, so maxInstances MUST be enforced.
    # =====================================================

    try:

        require_instance_capacity(
            db=db,
            tenant_id=instance.tenant_id,
            application_id=instance.application_id,
            entitlement=entitlement,
        )

    except InstanceLimitError as error:

        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error

    # =====================================================
    # 6. ENSURE NO ACTIVE DEPLOYMENT EXISTS
    # =====================================================

    active_deployment = db.scalar(
        select(ApplicationDeployment)
        .where(
            ApplicationDeployment.instance_id
            == instance.id,

            ApplicationDeployment.status.in_(
                (
                    "deploying",
                    "running",
                )
            ),
        )
    )

    if active_deployment:

        raise HTTPException(
            status_code=409,
            detail=(
                "Instance already has an active "
                "deployment."
            ),
        )

    # =====================================================
    # 7. FIND READY BUILD
    # =====================================================

    build = db.scalar(
        select(ApplicationBuild)
        .where(
            ApplicationBuild.application_version_id
            == version.id,

            ApplicationBuild.status
            == "ready",
        )
        .order_by(
            ApplicationBuild.created_at.desc()
        )
    )

    if not build:

        raise HTTPException(
            status_code=409,
            detail=(
                "No ready build exists for "
                "the active version."
            ),
        )

    if not build.image_ref:

        raise HTTPException(
            status_code=409,
            detail="Build has no image reference.",
        )

    # =====================================================
    # 8. CREATE RESTART DEPLOYMENT
    # =====================================================

    short_id = uuid.uuid4().hex[:8]

    container_name = safe_name(
        f"augmis-restart-"
        f"{instance.instance_key}-"
        f"{short_id}"
    )

    deployment = ApplicationDeployment(
        instance_id=instance.id,
        application_version_id=version.id,
        build_id=build.id,
        status="deploying",
        container_name=container_name,
        health_status="starting",
    )

    db.add(deployment)

    # Provisioning is an active instance status and therefore
    # reserves the maxInstances slot before the advisory lock
    # is released by commit.

    instance.status = "provisioning"

    db.commit()

    db.refresh(instance)
    db.refresh(deployment)

    # =====================================================
    # 9. START CONTAINER
    # =====================================================

    try:

        result = start_container(
            image_ref=build.image_ref,
            manifest=version.manifest,
            container_name=container_name,
            labels={
                "augmis.managed": "true",

                "augmis.instance_id":
                    str(instance.id),

                "augmis.tenant_id":
                    str(instance.tenant_id),

                "augmis.application_id":
                    str(instance.application_id),

                "augmis.restart":
                    "true",
            },
        )

    except DeploymentError as error:

        deployment.status = "failed"
        deployment.health_status = "unhealthy"
        deployment.error_message = str(error)

        # Restart failure leaves the logical instance stopped.
        instance.status = "stopped"

        db.commit()

        raise HTTPException(
            status_code=422,
            detail={
                "message":
                    "Instance restart failed",

                "deploymentId":
                    str(deployment.id),

                "error":
                    str(error),
            },
        ) from error

    # =====================================================
    # 10. PROMOTE RESTART DEPLOYMENT
    # =====================================================

    now = datetime.now(
        timezone.utc
    )

    deployment.container_id = (
        result["container_id"]
    )

    deployment.container_name = (
        result["container_name"]
    )

    deployment.host_port = (
        result["host_port"]
    )

    deployment.runtime_url = (
        result["runtime_url"]
    )

    deployment.status = "running"
    deployment.health_status = "healthy"
    deployment.deployed_at = now

    instance.status = "running"

    db.commit()

    db.refresh(instance)
    db.refresh(deployment)

    # =====================================================
    # 11. RESPONSE
    # =====================================================

    return {
        "status": "RESTARTED",

        "instance": {
            "id": str(instance.id),
            "name": instance.name,
            "status": instance.status,
        },

        "activeVersion": {
            "id": str(version.id),
            "version": version.version,
        },

        "deployment": {
            "id": str(deployment.id),

            "containerId":
                deployment.container_id,

            "containerName":
                deployment.container_name,

            "hostPort":
                deployment.host_port,

            "url":
                deployment.runtime_url,

            "health":
                deployment.health_status,
        },
    }