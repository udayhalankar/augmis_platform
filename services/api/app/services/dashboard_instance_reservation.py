"""B4 Pass 3H-5F: opt-in, development-only dashboard two-phase provisioning.

Never publishes an application, creates subscriptions or bypasses tenant RBAC.
Reservation stores no secrets and does not launch Docker. Activation requires
host-provisioned per-instance secret files and existing platform entitlements.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.core.config import settings
from services.api.app.models.platform import (
    Application, ApplicationBuild, ApplicationDeployment, ApplicationInstance,
    ApplicationVersion, Tenant,
)
from services.api.app.services.audit_service import record_audit_event
from services.api.app.services.authorization_service import (
    AuthorizationError, require_tenant_permission,
)
from services.api.app.services.dashboard_runtime_mounts import (
    PilotLaunchError, build_dashboard_pilot_launch,
)
from services.api.app.services.dev_dashboard_ingress import (
    DevIngressError, require_dev_relay,
)
from services.api.app.services.deployment_engine import (
    DeploymentError, stop_container,
)
from services.api.app.services.entitlement_service import (
    EntitlementError, require_active_subscription, require_active_entitlement,
)
from services.api.app.services.instance_limit_service import (
    InstanceLimitError, acquire_instance_limit_lock, require_instance_capacity,
)
from services.api.app.services.runtime_controls_service import (
    RuntimeControlError, pinned_image_identity, start_scoped_container,
)
from services.api.app.services.tenant_application_runtime_control import (
    get_runtime_launch_epoch, require_runtime_launch_allowed,
)
from services.api.app.services.version_policy_service import (
    VersionPolicyError, require_subscription_version_allowed,
)

FLAG = "AUGMIS_DASHBOARD_TWO_PHASE_ENABLED"
APP_ENV = "AUGMIS_DASHBOARD_ASSERTION_APPLICATION_ID"
TENANT_ENV = "AUGMIS_DASHBOARD_ASSERTION_TENANT_ID"


def _parse_exact_uuid(name: str) -> uuid.UUID:
    raw = os.environ.get(name, "").strip()
    try:
        value = uuid.UUID(raw)
    except (TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(status_code=503, detail="Dashboard pilot identity is not configured") from exc
    if str(value) != raw:
        raise HTTPException(status_code=503, detail="Dashboard pilot identity must be canonical")
    return value


def is_two_phase_app(app_id: uuid.UUID) -> bool:
    """Used ONLY to intercept the legacy immediate deploy for this pilot."""
    if os.environ.get(FLAG) != "1":
        return False
    if not os.environ.get(APP_ENV, "").strip():
        return False  # Partial configuration must not block unrelated apps.
    configured = _parse_exact_uuid(APP_ENV)
    return configured == app_id


def require_pilot_scope(tenant_id: uuid.UUID, app_id: uuid.UUID) -> None:
    if os.environ.get(FLAG) != "1" or str(settings.app_env).lower() not in {"development", "dev"}:
        raise HTTPException(status_code=409, detail="Two-phase dashboard pilot is disabled")
    if _parse_exact_uuid(APP_ENV) != app_id or _parse_exact_uuid(TENANT_ENV) != tenant_id:
        raise HTTPException(status_code=403, detail="Dashboard pilot scope mismatch")


def _authorized_access(db: Session, *, user, tenant: Tenant,
                       application: Application, version: ApplicationVersion):
    if tenant.status != "active":
        raise HTTPException(status_code=409, detail="Tenant is not active")
    try:
        require_tenant_permission(db=db, user=user, tenant_id=tenant.id,
                                  permission_code="application.deploy")
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    require_pilot_scope(tenant.id, application.id)
    if version.application_id != application.id:
        raise HTTPException(status_code=409, detail="Application and version mismatch")
    if application.status != "published" or version.publication_status != "published":
        raise HTTPException(status_code=409, detail="Application version must be published")
    if version.status != "image_ready":
        raise HTTPException(status_code=409, detail="Application version is not image_ready")
    try:
        subscription = require_active_subscription(db=db, tenant_id=tenant.id,
                                                   application_id=application.id)
        entitlement = require_active_entitlement(db=db, tenant_id=tenant.id,
                                                  application_id=application.id,
                                                  entitlement_code="application.deploy")
        require_subscription_version_allowed(db=db, subscription=subscription,
                                             target_version=version)
    except (EntitlementError, VersionPolicyError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    require_runtime_launch_allowed(db, tenant.id, application.id)
    return entitlement


def _ready_build(db: Session, version: ApplicationVersion) -> ApplicationBuild:
    build = db.scalar(select(ApplicationBuild).where(
        ApplicationBuild.application_version_id == version.id,
        ApplicationBuild.status == "ready",
    ).order_by(ApplicationBuild.created_at.desc()))
    if build is None or not build.image_ref:
        raise HTTPException(status_code=409, detail="No ready image build available")
    return build


def reserve_dashboard_instance(*, db: Session, tenant_id: uuid.UUID,
                               version_id: uuid.UUID, name: str | None,
                               user) -> dict:
    tenant = db.get(Tenant, tenant_id)
    version = db.get(ApplicationVersion, version_id)
    if tenant is None or version is None:
        raise HTTPException(status_code=404, detail="Tenant or version not found")
    application = db.get(Application, version.application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    entitlement = _authorized_access(db, user=user, tenant=tenant,
                                      application=application, version=version)
    # Same advisory lock and capacity checks as the existing deployment path.
    acquire_instance_limit_lock(db=db, tenant_id=tenant.id, application_id=application.id)
    require_runtime_launch_allowed(db, tenant.id, application.id)
    try:
        require_instance_capacity(db=db, tenant_id=tenant.id,
                                  application_id=application.id, entitlement=entitlement)
    except InstanceLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    build = _ready_build(db, version)
    # Only the intended pilot may reserve; never create for unrelated apps.
    require_pilot_scope(tenant.id, application.id)
    short_id = uuid.uuid4().hex[:8]
    # Preserve container naming convention used by existing deployment path.
    from services.api.app.routes.instances import safe_name
    instance = ApplicationInstance(
        tenant_id=tenant.id, application_id=application.id,
        active_version_id=version.id,
        instance_key=f"{tenant.slug}-{application.app_key}-{short_id}",
        name=(name or f"{application.name} - {tenant.name}"),
        status="provisioning",
    )
    db.add(instance)
    db.flush()
    deployment = ApplicationDeployment(
        instance_id=instance.id, application_version_id=version.id,
        build_id=build.id, status="reserved", health_status="pending_secrets",
        container_name=safe_name(f"augmis-{tenant.slug}-{application.app_key}-{short_id}"),
    )
    db.add(deployment)
    db.flush()
    record_audit_event(
        db, action="application.instance.reserved", resource_type="application_instance",
        resource_id=instance.id, actor_user_id=user.id, tenant_id=tenant.id,
        metadata={"applicationId": str(application.id), "versionId": str(version.id),
                  "deploymentId": str(deployment.id)},
        message="Dashboard instance reserved without starting Docker.",
    )
    db.commit()
    return {"status": "PENDING_SECRETS", "tenantId": str(tenant.id),
            "applicationId": str(application.id), "versionId": str(version.id),
            "instanceId": str(instance.id), "deploymentId": str(deployment.id),
            "runtimeStarted": False}


def activate_reserved_dashboard(*, db: Session, instance_id: uuid.UUID, user) -> dict:
    initial = db.get(ApplicationInstance, instance_id)
    if initial is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    # Lock serializes activation with other tenant/application mutations.
    acquire_instance_limit_lock(db=db, tenant_id=initial.tenant_id,
                                application_id=initial.application_id)
    instance = db.scalar(select(ApplicationInstance).where(
        ApplicationInstance.id == instance_id).with_for_update())
    if instance is None or instance.status != "provisioning":
        raise HTTPException(status_code=409, detail="Instance is not awaiting activation")
    tenant = db.get(Tenant, instance.tenant_id)
    application = db.get(Application, instance.application_id)
    version = db.get(ApplicationVersion, instance.active_version_id)
    if not tenant or not application or not version:
        raise HTTPException(status_code=409, detail="Reserved instance references missing resources")
    _authorized_access(db, user=user, tenant=tenant,
                       application=application, version=version)
    deployment = db.scalar(select(ApplicationDeployment).where(
        ApplicationDeployment.instance_id == instance.id,
        ApplicationDeployment.status == "reserved",
    ).with_for_update())
    if deployment is None or not deployment.container_name:
        raise HTTPException(status_code=409, detail="Reserved deployment is unavailable")
    build = _ready_build(db, version)
    if deployment.build_id != build.id:
        raise HTTPException(status_code=409, detail="Reserved build has changed")
    # Preflight before transitioning to deploying; missing secrets do not consume
    # the reserved instance or start a Docker container.
    try:
        image_id = pinned_image_identity(db, build)
        pilot = build_dashboard_pilot_launch(
            tenant_id=tenant.id, application_id=application.id,
            instance_id=instance.id, image_id=image_id,
        )
        if pilot is None:
            raise PilotLaunchError("Dashboard pilot secrets are not enabled")
        from services.api.app.services.deployment_engine import run_docker
        require_dev_relay(pilot, run_docker=run_docker)
    except (PilotLaunchError, DevIngressError, RuntimeControlError, DeploymentError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Dashboard runtime preflight is incomplete") from exc

    launch_epoch = get_runtime_launch_epoch(db, tenant.id, application.id)
    deployment.status = "deploying"
    deployment.health_status = "starting"
    db.commit()
    try:
        result = start_scoped_container(
            db=db, instance=instance, deployment=deployment, build=build,
            manifest=version.manifest, container_name=deployment.container_name,
            labels={"augmis.managed": "true", "augmis.instance_id": str(instance.id),
                    "augmis.tenant_id": str(tenant.id),
                    "augmis.application_id": str(application.id)},
        )
        # Detect an operator STOP during the Docker startup window.
        db.expire_all()
        if get_runtime_launch_epoch(db, tenant.id, application.id) != launch_epoch:
            raise DeploymentError("Application launch was revoked during startup")
        require_runtime_launch_allowed(db, tenant.id, application.id)
    except Exception as exc:
        # The launcher usually cleans failed starts. If startup succeeded before
        # the STOP gate changed, attempt to remove its managed containers too.
        try:
            stop_container(deployment.container_name)
        except Exception:
            pass
        db.rollback()
        deployment.status = "failed"
        deployment.health_status = "unhealthy"
        deployment.error_message = "Reserved dashboard activation failed"
        instance.status = "failed"
        record_audit_event(
            db, action="application.deploy", resource_type="application_instance",
            resource_id=instance.id, actor_user_id=user.id, tenant_id=tenant.id,
            outcome="failed", metadata={"deploymentId": str(deployment.id)},
            message="Reserved dashboard activation failed.",
        )
        db.commit()
        raise HTTPException(status_code=422, detail="Dashboard activation failed; inspect authorized runtime diagnostics") from exc

    deployment.container_id = result["container_id"]
    deployment.container_name = result["container_name"]
    deployment.host_port = result["host_port"]
    deployment.runtime_url = result["runtime_url"]
    deployment.status = "running"
    deployment.health_status = "healthy"
    deployment.deployed_at = datetime.now(timezone.utc)
    instance.status = "running"
    record_audit_event(
        db, action="application.deploy", resource_type="application_instance",
        resource_id=instance.id, actor_user_id=user.id, tenant_id=tenant.id,
        metadata={"applicationId": str(application.id), "versionId": str(version.id),
                  "deploymentId": str(deployment.id)},
        message="Reserved dashboard activated using managed private ingress.",
    )
    db.commit()
    return {"status": "RUNNING", "instanceId": str(instance.id),
            "deploymentId": str(deployment.id), "runtimeStarted": True}


def cancel_reserved_dashboard(*, db: Session, instance_id: uuid.UUID, user) -> dict:
    """Release reserved capacity without requiring a still-active subscription.

    Allowed only while Docker has not started; no destructive Docker command.
    """
    initial = db.get(ApplicationInstance, instance_id)
    if initial is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    acquire_instance_limit_lock(db=db, tenant_id=initial.tenant_id,
                                application_id=initial.application_id)
    instance = db.scalar(select(ApplicationInstance).where(
        ApplicationInstance.id == instance_id).with_for_update())
    if instance is None or instance.status != "provisioning":
        raise HTTPException(status_code=409, detail="Instance is not reserved")
    try:
        require_tenant_permission(db=db, user=user, tenant_id=instance.tenant_id,
                                  permission_code="application.deploy")
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    require_pilot_scope(instance.tenant_id, instance.application_id)
    deployment = db.scalar(select(ApplicationDeployment).where(
        ApplicationDeployment.instance_id == instance.id,
        ApplicationDeployment.status == "reserved",
    ).with_for_update())
    if deployment is None or deployment.container_id or deployment.runtime_url:
        raise HTTPException(status_code=409, detail="Reserved deployment cannot be cancelled")
    # Do not mark a cancelled reservation as `stopped`: the generic Restart
    # endpoint accepts stopped instances and would bypass the reserve workflow.
    deployment.status = "cancelled"
    deployment.health_status = "cancelled"
    deployment.stopped_at = datetime.now(timezone.utc)
    instance.status = "cancelled"
    record_audit_event(
        db, action="application.instance.reservation.cancelled",
        resource_type="application_instance", resource_id=instance.id,
        actor_user_id=user.id, tenant_id=instance.tenant_id,
        metadata={"deploymentId": str(deployment.id)},
        message="Unstarted dashboard reservation cancelled.",
    )
    db.commit()
    return {"status": "CANCELLED", "instanceId": str(instance.id),
            "deploymentId": str(deployment.id), "runtimeStarted": False}
