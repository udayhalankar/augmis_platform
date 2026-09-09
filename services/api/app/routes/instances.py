from __future__ import annotations

import re
import uuid

from datetime import (
    datetime,
    timezone
)

from fastapi import (
    APIRouter,
    Depends,
    HTTPException
)

from services.api.app.core.auth import (
    get_current_user
)

from services.api.app.models.iam import (
    User
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_tenant_permission
)

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.db.session import (
    get_db
)

from services.api.app.models.platform import (
    Application,
    ApplicationBuild,
    ApplicationDeployment,
    ApplicationInstance,
    ApplicationVersion,
    Tenant
)

from services.api.app.schemas.instance import (
    InstanceDeployRequest
)

from services.api.app.services.deployment_engine import (
    DeploymentError,
    start_container,
    stop_container
)


router = APIRouter(
    prefix="/api/v1",
    tags=["Runtime"]
)


def safe_name(
    value: str
) -> str:

    value = value.lower()

    value = re.sub(
        r"[^a-z0-9-]",
        "-",
        value
    )

    value = re.sub(
        r"-+",
        "-",
        value
    )

    return value.strip("-")


@router.post(
    "/tenants/{tenant_id}/application-versions/{version_id}/deploy",
    status_code=201
)
def deploy_application(
    tenant_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: InstanceDeployRequest,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    )
):

    tenant = db.get(
        Tenant,
        tenant_id
    )

    if not tenant:

        raise HTTPException(
            status_code=404,
            detail="Tenant not found"
        )

    if tenant.status != "active":

        raise HTTPException(
            status_code=409,
            detail="Tenant is not active"
        )

    version = db.get(
        ApplicationVersion,
        version_id
    )

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=tenant.id,
            permission_code="application.deploy"
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error)
        )

    if not version:

        raise HTTPException(
            status_code=404,
            detail="Application version not found"
        )

    if version.status != "image_ready":

        raise HTTPException(
            status_code=409,
            detail=(
                "Application version does not "
                "have a ready image."
            )
        )

    application = db.get(
        Application,
        version.application_id
    )

    if not application:

        raise HTTPException(
            status_code=404,
            detail="Application not found"
        )

    build = db.scalar(
        select(ApplicationBuild)
        .where(
            ApplicationBuild.application_version_id
            == version.id,

            ApplicationBuild.status
            == "ready"
        )
        .order_by(
            ApplicationBuild.created_at.desc()
        )
    )

    if not build:

        raise HTTPException(
            status_code=409,
            detail="No ready build found"
        )

    if not build.image_ref:

        raise HTTPException(
            status_code=409,
            detail="Build has no image reference"
        )

    short_id = (
        uuid.uuid4().hex[:8]
    )

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
        status="provisioning"
    )

    db.add(instance)

    db.flush()

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
        health_status="starting"
    )

    db.add(deployment)

    db.commit()

    db.refresh(instance)
    db.refresh(deployment)

    try:

        result = start_container(
            image_ref=build.image_ref,
            manifest=version.manifest,
            container_name=container_name,
            labels={
                "augmis.managed":
                    "true",

                "augmis.instance_id":
                    str(instance.id),

                "augmis.tenant_id":
                    str(tenant.id),

                "augmis.application_id":
                    str(application.id)
            }
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
                    str(error)
            }
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

    deployment.health_status = (
        "healthy"
    )

    deployment.deployed_at = (
        datetime.now(
            timezone.utc
        )
    )

    instance.status = "running"

    db.commit()

    return {

        "status":
            "RUNNING",

        "tenant": {
            "id":
                str(tenant.id),

            "name":
                tenant.name
        },

        "application": {
            "id":
                str(application.id),

            "name":
                application.name
        },

        "instance": {
            "id":
                str(instance.id),

            "instanceKey":
                instance.instance_key,

            "name":
                instance.name,

            "status":
                instance.status
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
                deployment.health_status
        }
    }


@router.get(
    "/tenants/{tenant_id}/instances"
)

def list_tenant_instances(
    tenant_id: uuid.UUID,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    )
):

    tenant = db.get(
        Tenant,
        tenant_id
    )

    if not tenant:

        raise HTTPException(
            status_code=404,
            detail="Tenant not found"
        )

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=tenant.id,
            permission_code="application.instance.view"
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error)
        )

    instances = list(
        db.scalars(
            select(ApplicationInstance)
            .where(
                ApplicationInstance.tenant_id
                == tenant_id
            )
            .order_by(
                ApplicationInstance.created_at.desc()
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
                instance.status
        }

        for instance in instances
    ]

@router.post(
    "/instances/{instance_id}/stop"
)


def stop_application_instance(
    instance_id: uuid.UUID,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    )
):

    instance = db.get(
        ApplicationInstance,
        instance_id
    )

    if not instance:

        raise HTTPException(
            status_code=404,
            detail="Instance not found"
        )

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=instance.tenant_id,
            permission_code="application.instance.stop"
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error)
        )

    deployment = db.scalar(
        select(ApplicationDeployment)
        .where(
            ApplicationDeployment.instance_id
            == instance.id,

            ApplicationDeployment.status
            == "running"
        )
        .order_by(
            ApplicationDeployment.created_at.desc()
        )
    )

    if not deployment:

        raise HTTPException(
            status_code=409,
            detail="No running deployment found"
        )

    if not deployment.container_name:

        raise HTTPException(
            status_code=409,
            detail="Deployment has no container"
        )

    try:

        stop_container(
            deployment.container_name
        )

    except DeploymentError as error:

        raise HTTPException(
            status_code=422,
            detail=str(error)
        )

    deployment.status = "stopped"

    deployment.health_status = (
        "stopped"
    )

    deployment.stopped_at = (
        datetime.now(
            timezone.utc
        )
    )

    instance.status = "stopped"

    db.commit()

    return {
        "status":
            "STOPPED",

        "instanceId":
            str(instance.id)
    }