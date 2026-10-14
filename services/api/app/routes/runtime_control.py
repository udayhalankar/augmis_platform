"""B1B tenant configuration and platform quota administration."""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from services.api.app.core.auth import get_current_user
from services.api.app.db.session import get_db
from services.api.app.models.iam import User
from services.api.app.models.platform import ApplicationInstance, ApplicationDeployment, Tenant
from services.api.app.models.runtime_control import RuntimeInstanceConfig, TenantRuntimeQuota, RuntimeUpgradeJob
from services.api.app.services.authorization_service import (AuthorizationError, require_platform_permission, require_tenant_permission)
from services.api.app.services.audit_service import record_audit_event
from services.api.app.services.runtime_controls_service import RuntimeControlError, validate_runtime_variables

router = APIRouter(prefix="/api/v1", tags=["Runtime Governance"])

class ConfigUpdate(BaseModel):
    expected_revision: int | None = Field(default=None, ge=1)
    variables: dict[str,str]

class QuotaUpdate(BaseModel):
    max_running_containers: int = Field(ge=1, le=1000)


def _instance(db, user, instance_id, permission):
    instance = db.get(ApplicationInstance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    try:
        require_tenant_permission(db=db, user=user, tenant_id=instance.tenant_id, permission_code=permission)
    except AuthorizationError:
        raise HTTPException(403, "Tenant runtime permission denied")
    return instance

@router.get("/instances/{instance_id}/configuration")
def get_config(instance_id: uuid.UUID, db: Session=Depends(get_db), user: User=Depends(get_current_user)):
    instance = _instance(db,user,instance_id,"application.instance.view")
    cfg = db.scalar(select(RuntimeInstanceConfig).where(RuntimeInstanceConfig.instance_id == instance.id))
    return {"instanceId":str(instance.id), "revision":cfg.revision if cfg else None,
            "variables":dict(cfg.variables_json or {}) if cfg else {},
            "secretReferenceNames":sorted((cfg.secret_refs_json or {}).keys()) if cfg else [],
            "appliesOnNextStart":True}

@router.put("/instances/{instance_id}/configuration")
def put_config(instance_id: uuid.UUID, payload: ConfigUpdate, db: Session=Depends(get_db), user: User=Depends(get_current_user)):
    instance = _instance(db,user,instance_id,"application.deploy")
    try:
        variables = validate_runtime_variables(payload.variables)
    except RuntimeControlError as exc:
        raise HTTPException(422, str(exc)) from exc
    cfg = db.scalar(select(RuntimeInstanceConfig).where(RuntimeInstanceConfig.instance_id == instance.id).with_for_update())
    old_revision = cfg.revision if cfg else None
    if old_revision != payload.expected_revision:
        raise HTTPException(409, "Configuration revision mismatch. Refresh before updating.")
    if cfg:
        cfg.revision += 1
        cfg.variables_json = variables
    else:
        cfg = RuntimeInstanceConfig(tenant_id=instance.tenant_id,instance_id=instance.id,
                                    revision=1,variables_json=variables, secret_refs_json={})
        db.add(cfg)
    record_audit_event(db,action="runtime.configuration.updated",resource_type="application_instance",
                       resource_id=instance.id,tenant_id=instance.tenant_id,actor_user_id=user.id,
                       outcome="success", message="Non-secret runtime settings changed.",
                       metadata={"revision":cfg.revision,"keys":sorted(variables)})
    db.commit()
    return {"instanceId":str(instance.id),"revision":cfg.revision,"appliesOnNextStart":True}

@router.get("/tenants/{tenant_id}/runtime-quota")
def get_quota(tenant_id: uuid.UUID, db: Session=Depends(get_db), user: User=Depends(get_current_user)):
    try:
        require_tenant_permission(db=db,user=user,tenant_id=tenant_id,permission_code="application.instance.view")
    except AuthorizationError:
        raise HTTPException(403,"Tenant access denied")
    quota = db.get(TenantRuntimeQuota,tenant_id)
    # Inform the UI only. PUT remains platform-authorized on the backend.
    can_manage_quota = False
    try:
        require_platform_permission(db=db, user=user, permission_code="platform.settings.manage")
        can_manage_quota = True
    except AuthorizationError:
        pass
    return {"tenantId":str(tenant_id),"maxRunningContainers":quota.max_running_containers if quota else None,
            "canManageQuota": can_manage_quota}

@router.put("/tenants/{tenant_id}/runtime-quota")
def put_quota(tenant_id: uuid.UUID,payload: QuotaUpdate,db: Session=Depends(get_db),user: User=Depends(get_current_user)):
    try:
        require_platform_permission(db=db,user=user,permission_code="platform.settings.manage")
    except AuthorizationError:
        raise HTTPException(403,"Platform runtime quota management denied")
    # Same tenant-row serialization lock used by require_capacity() when
    # reserving a Docker container. Prevent quota edits racing with deploy.
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if not tenant: raise HTTPException(404,"Tenant not found")
    # Do not reduce a quota below containers already reserved/running.
    usage = db.scalar(select(func.count(ApplicationDeployment.id))
        .join(ApplicationInstance, ApplicationInstance.id == ApplicationDeployment.instance_id)
        .where(ApplicationInstance.tenant_id == tenant_id,
               ApplicationDeployment.status.in_(("running", "deploying")))) or 0
    if payload.max_running_containers < usage:
        raise HTTPException(409,"Requested quota is below active/reserved container usage")
    quota = db.get(TenantRuntimeQuota,tenant_id)
    if quota: quota.max_running_containers=payload.max_running_containers
    else: db.add(TenantRuntimeQuota(tenant_id=tenant_id,max_running_containers=payload.max_running_containers))
    record_audit_event(db,action="runtime.quota.updated",resource_type="tenant",resource_id=tenant_id,
                       tenant_id=tenant_id,actor_user_id=user.id,outcome="success",
                       metadata={"maxRunningContainers":payload.max_running_containers})
    db.commit()
    return {"tenantId":str(tenant_id),"maxRunningContainers":payload.max_running_containers}

@router.get("/tenants/{tenant_id}/upgrade-jobs")
def list_jobs(tenant_id: uuid.UUID,db: Session=Depends(get_db),user: User=Depends(get_current_user)):
    try:
        require_tenant_permission(db=db,user=user,tenant_id=tenant_id,permission_code="application.instance.view")
    except AuthorizationError: raise HTTPException(403,"Tenant access denied")
    jobs=list(db.scalars(select(RuntimeUpgradeJob).where(RuntimeUpgradeJob.tenant_id==tenant_id).order_by(RuntimeUpgradeJob.created_at.desc()).limit(100)))
    return [{"id":str(x.id),"instanceId":str(x.instance_id),"targetVersionId":str(x.target_version_id),
             "status":x.status,"attempts":x.attempts,"errorCode":x.last_error_code} for x in jobs]

# ─────────────────────────────────────────────────────────────────────────────
# B1+B2 acceptance — explicit subscription-level auto-upgrade consent.
# No worker start, no direct Docker action, no implicit user elevation.
# ─────────────────────────────────────────────────────────────────────────────
class AutoUpgradeConsentUpdate(BaseModel):
    expected_auto_upgrade: bool
    auto_upgrade: bool


def _active_runtime_contracts(db: Session, instance: ApplicationInstance, *, locked: bool = False):
    """Find matching active contracts; never choose arbitrarily among duplicates."""
    from services.api.app.models.commerce import ApplicationOffer, TenantSubscription
    query = (
        select(TenantSubscription)
        .join(ApplicationOffer, ApplicationOffer.id == TenantSubscription.offer_id)
        .where(
            TenantSubscription.tenant_id == instance.tenant_id,
            ApplicationOffer.application_id == instance.application_id,
            TenantSubscription.status == "active",
            ApplicationOffer.status == "active",
        )
        .order_by(TenantSubscription.created_at.asc())
    )
    if locked:
        query = query.with_for_update(of=TenantSubscription)
    return list(db.scalars(query))


@router.get("/instances/{instance_id}/upgrade-readiness")
def get_upgrade_readiness(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    instance = _instance(db, user, instance_id, "application.instance.view")
    try:
        require_tenant_permission(
            db=db, user=user, tenant_id=instance.tenant_id,
            permission_code="subscription.view",
        )
    except AuthorizationError as exc:
        raise HTTPException(403, "Subscription visibility denied") from exc

    from datetime import datetime, timezone
    from services.api.app.models.platform import ApplicationVersion
    from services.api.app.services.runtime_automation_service import (
        eligible_upgrade, _has_deploy_entitlement,
    )
    contracts = _active_runtime_contracts(db, instance)
    base = {
        "instanceId": str(instance.id),
        "instanceStatus": instance.status,
        "currentVersion": None,
        "subscriptionId": None,
        "autoUpgrade": False,
        "versionPolicy": None,
        "status": "blocked",
        "reason": "NO_ACTIVE_CONTRACT",
        "candidateVersionId": None,
        "candidateVersion": None,
    }
    current_version = db.get(ApplicationVersion, instance.active_version_id) if instance.active_version_id else None
    base["currentVersion"] = current_version.version if current_version else None
    if not contracts:
        return base
    if len(contracts) != 1:
        base["reason"] = "MULTIPLE_ACTIVE_CONTRACTS"
        return base

    contract = contracts[0]
    base.update(subscriptionId=str(contract.id), autoUpgrade=bool(contract.auto_upgrade),
                versionPolicy=contract.version_policy)
    now = datetime.now(timezone.utc)
    if contract.starts_at and contract.starts_at > now:
        base["reason"] = "SUBSCRIPTION_NOT_STARTED"
    elif contract.ends_at and contract.ends_at <= now:
        base["reason"] = "SUBSCRIPTION_EXPIRED"
    elif instance.status != "running":
        base["reason"] = "INSTANCE_NOT_RUNNING"
    elif not _has_deploy_entitlement(db, contract):
        base["reason"] = "DEPLOY_ENTITLEMENT_MISSING"
    elif not contract.auto_upgrade:
        base["reason"] = "AUTO_UPGRADE_DISABLED"
    else:
        choice = eligible_upgrade(db, instance)
        if choice and choice[0].id == contract.id:
            base.update(status="eligible", reason="ELIGIBLE",
                        candidateVersionId=str(choice[1].id), candidateVersion=choice[1].version)
        else:
            base["reason"] = "NO_ELIGIBLE_PUBLISHED_TARGET"
    return base


@router.put("/instances/{instance_id}/auto-upgrade")
def update_instance_auto_upgrade_consent(
    instance_id: uuid.UUID,
    payload: AutoUpgradeConsentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Explicit commercial-owner consent; does NOT enqueue/execute any upgrade."""
    instance = _instance(db, user, instance_id, "application.instance.view")
    try:
        require_tenant_permission(
            db=db, user=user, tenant_id=instance.tenant_id,
            permission_code="subscription.manage",
        )
    except AuthorizationError as exc:
        raise HTTPException(403, "Subscription management permission denied") from exc

    from services.api.app.services.runtime_automation_service import _has_deploy_entitlement
    from datetime import datetime, timezone
    contracts = _active_runtime_contracts(db, instance, locked=True)
    if len(contracts) != 1:
        raise HTTPException(409, "Exactly one active subscription for this tenant/application is required")
    contract = contracts[0]
    if contract.auto_upgrade is not payload.expected_auto_upgrade:
        raise HTTPException(409, "Subscription setting changed; refresh and retry")
    now = datetime.now(timezone.utc)
    if ((contract.starts_at and contract.starts_at > now)
            or (contract.ends_at and contract.ends_at <= now)):
        raise HTTPException(409, "Subscription is outside its active term")
    if payload.auto_upgrade and not _has_deploy_entitlement(db, contract):
        raise HTTPException(409, "Cannot enable upgrades without deployment entitlement")
    busy = db.scalar(select(RuntimeUpgradeJob.id).where(
        RuntimeUpgradeJob.instance_id == instance.id,
        RuntimeUpgradeJob.status.in_(("running", "needs_reconciliation")),
    ).limit(1))
    if busy:
        raise HTTPException(409, "Upgrade is running or requires reconciliation")
    if contract.auto_upgrade == payload.auto_upgrade:
        return {"subscriptionId": str(contract.id), "autoUpgrade": contract.auto_upgrade,
                "changed": False, "note": "Consent applies to the subscription, not only this instance."}
    contract.auto_upgrade = payload.auto_upgrade
    record_audit_event(
        db, action="subscription.auto_upgrade.updated", resource_type="tenant_subscription",
        resource_id=contract.id, tenant_id=instance.tenant_id, actor_user_id=user.id,
        outcome="success", message="Tenant subscription auto-upgrade consent changed.",
        metadata={"applicationId": str(instance.application_id),
                  "autoUpgrade": payload.auto_upgrade, "instanceId": str(instance.id)},
    )
    db.commit()
    return {"subscriptionId": str(contract.id), "autoUpgrade": contract.auto_upgrade,
            "changed": True, "note": "Consent applies to the subscription, not only this instance."}
