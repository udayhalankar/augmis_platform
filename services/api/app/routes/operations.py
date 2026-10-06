import urllib.error
import urllib.request
import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.api.app.core.auth import (
    get_current_user,
)

from services.api.app.db.session import (
    SessionLocal,
    get_db,
)

from services.api.app.models.iam import (
    User,
)

from services.api.app.models.platform import (
    ApplicationDeployment,
    ApplicationInstance,
    ApplicationVersion,
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_tenant_permission,
)

from services.api.app.services.build_engine import (
    docker_available,
)

from services.api.app.services.deployment_engine import (
    DeploymentError,
    find_public_service,
    get_container_logs,
    run_docker,
)


router = APIRouter(
    prefix="/api/v1",
    tags=["Operations"],
)


# =========================================================
# PLATFORM READINESS
# =========================================================

@router.get(
    "/readiness",
)
def platform_readiness():

    database_ready = False
    docker_ready = False

    database_error = None
    docker_error = None

    # -----------------------------------------------------
    # DATABASE
    # -----------------------------------------------------

    db = SessionLocal()

    try:

        db.execute(
            text("SELECT 1")
        )

        database_ready = True

    except Exception:

        database_error = (
            "Database readiness check failed."
        )

    finally:

        db.close()

    # -----------------------------------------------------
    # DOCKER
    # -----------------------------------------------------

    try:

        docker_ready = docker_available()

        if not docker_ready:

            docker_error = (
                "Docker runtime is unavailable."
            )

    except Exception:

        docker_error = (
            "Docker readiness check failed."
        )

    ready = (
        database_ready
        and docker_ready
    )

    return {
        "status": (
            "ready"
            if ready
            else "not_ready"
        ),

        "checks": {

            "database": {
                "ready":
                    database_ready,

                "error":
                    database_error,
            },

            "docker": {
                "ready":
                    docker_ready,

                "error":
                    docker_error,
            },
        },
    }


# =========================================================
# DEPLOYMENT HEALTH
# =========================================================

@router.get(
    "/deployments/{deployment_id}/health",
)
def deployment_health(
    deployment_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    # =====================================================
    # 1. LOAD DEPLOYMENT
    # =====================================================

    deployment = db.get(
        ApplicationDeployment,
        deployment_id,
    )

    if not deployment:

        raise HTTPException(
            status_code=404,
            detail="Deployment not found",
        )

    # =====================================================
    # 2. LOAD INSTANCE
    # =====================================================

    instance = db.get(
        ApplicationInstance,
        deployment.instance_id,
    )

    if not instance:

        raise HTTPException(
            status_code=409,
            detail=(
                "Deployment references a missing instance."
            ),
        )

    # =====================================================
    # 3. RBAC
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
    # 4. LOAD VERSION
    # =====================================================

    version = db.get(
        ApplicationVersion,
        deployment.application_version_id,
    )

    if not version:

        raise HTTPException(
            status_code=409,
            detail=(
                "Deployment references a missing "
                "application version."
            ),
        )

    # =====================================================
    # 5. DETERMINE HEALTH URL
    # =====================================================

    health_url = None
    health_path = None
    service_name = None

    try:

        service_name, service = (
            find_public_service(
                version.manifest
            )
        )

        health_config = (
            service.get("health")
            or {}
        )

        health_path = health_config.get(
            "path",
            "/",
        )

        if deployment.runtime_url:

            health_url = (
                deployment.runtime_url.rstrip("/")
                + "/"
                + health_path.lstrip("/")
            )

    except DeploymentError:

        pass

    # =====================================================
    # 6. CHECK ACTUAL DOCKER CONTAINER
    # =====================================================

    container_running = False
    container_error = None

    if deployment.container_name:

        try:

            output = run_docker(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{.State.Running}}",
                    deployment.container_name,
                ],
                timeout=10,
            )

            container_running = (
                output.strip().lower()
                == "true"
            )

        except DeploymentError as error:

            container_error = str(error)

    # =====================================================
    # 7. HTTP HEALTH PROBE
    # =====================================================

    http_reachable = False
    http_status = None
    http_error = None

    if (
        deployment.status == "running"
        and container_running
        and health_url
    ):

        try:

            request = urllib.request.Request(
                health_url,
                method="GET",
            )

            with urllib.request.urlopen(
                request,
                timeout=5,
            ) as response:

                http_status = response.status

                http_reachable = (
                    200
                    <= response.status
                    < 300
                )

        except urllib.error.HTTPError as error:

            http_status = error.code
            http_error = str(error)

        except Exception as error:

            http_error = str(error)

    # =====================================================
    # 8. EFFECTIVE HEALTH
    # =====================================================

    if deployment.status != "running":

        effective_health = "not_running"

    elif (
        container_running
        and http_reachable
    ):

        effective_health = "healthy"

    else:

        effective_health = "unhealthy"

    # =====================================================
    # 9. RESPONSE
    # =====================================================

    return {
        "deploymentId":
            str(deployment.id),

        "instanceId":
            str(instance.id),

        "version": {
            "id":
                str(version.id),

            "version":
                version.version,
        },

        "deploymentStatus":
            deployment.status,

        "recordedHealth":
            deployment.health_status,

        "effectiveHealth":
            effective_health,

        "container": {
            "id":
                deployment.container_id,

            "name":
                deployment.container_name,

            "running":
                container_running,

            "error":
                container_error,
        },

        "runtime": {
            "url":
                deployment.runtime_url,

            "service":
                service_name,

            "healthPath":
                health_path,

            "healthUrl":
                health_url,

            "reachable":
                http_reachable,

            "httpStatus":
                http_status,

            "error":
                http_error,
        },

        "deployedAt":
            deployment.deployed_at,

        "stoppedAt":
            deployment.stopped_at,
    }

# =========================================================
# DEPLOYMENT LOGS
# =========================================================

@router.get(
    "/deployments/{deployment_id}/logs",
)
def deployment_logs(
    deployment_id: uuid.UUID,

    tail: int = Query(
        default=200,
        ge=1,
        le=2000,
    ),

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    ),
):

    # =====================================================
    # 1. LOAD DEPLOYMENT
    # =====================================================

    deployment = db.get(
        ApplicationDeployment,
        deployment_id,
    )

    if not deployment:

        raise HTTPException(
            status_code=404,
            detail="Deployment not found",
        )

    # =====================================================
    # 2. LOAD INSTANCE
    # =====================================================

    instance = db.get(
        ApplicationInstance,
        deployment.instance_id,
    )

    if not instance:

        raise HTTPException(
            status_code=409,
            detail=(
                "Deployment references "
                "a missing instance."
            ),
        )

    # =====================================================
    # 3. RBAC
    # =====================================================

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=instance.tenant_id,
            permission_code=(
                "application.instance.view"
            ),
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 4. CONTAINER REFERENCE
    # =====================================================

    if not deployment.container_name:

        raise HTTPException(
            status_code=409,
            detail=(
                "Deployment has no "
                "container reference."
            ),
        )

    # =====================================================
    # 5. RETRIEVE DOCKER LOGS
    # =====================================================

    try:

        logs = get_container_logs(
            container_name=(
                deployment.container_name
            ),
            tail=tail,
        )

    except DeploymentError as error:

        error_text = str(error)

        # Stopped deployments are currently removed using
        # `docker rm -f`, so Docker can no longer provide
        # historical logs.

        if (
            "no such container"
            in error_text.lower()
            or "no such object"
            in error_text.lower()
        ):

            raise HTTPException(
                status_code=410,
                detail={
                    "message": (
                        "Deployment container "
                        "no longer exists."
                    ),

                    "reason": (
                        "Historical runtime logs "
                        "were not persisted before "
                        "the container was removed."
                    ),

                    "deploymentId":
                        str(deployment.id),
                },
            ) from error

        raise HTTPException(
            status_code=502,
            detail={
                "message":
                    "Could not retrieve deployment logs",

                "error":
                    error_text,
            },
        ) from error

    # =====================================================
    # 6. RESPONSE
    # =====================================================

    return {
        "deploymentId":
            str(deployment.id),

        "instanceId":
            str(instance.id),

        "deploymentStatus":
            deployment.status,

        "containerName":
            deployment.container_name,

        "tail":
            tail,

        "logs":
            logs,
    }