"""Tenant-scoped non-secret runtime settings, image identity and quota controls."""
from __future__ import annotations
import re
import uuid
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from services.api.app.models.platform import ApplicationBuild, ApplicationDeployment, ApplicationInstance, Tenant
from services.api.app.models.runtime_control import RuntimeInstanceConfig, TenantRuntimeQuota
from services.api.app.services.deployment_engine import DeploymentError, run_docker
from services.api.app.services.private_crud_runtime import (
    CrudRuntimeError, enabled_for, prepare_private_crud_runtime,
)
from services.api.app.models.runtime_control import ApplicationDatabaseResource
from services.api.app.services.dashboard_runtime_mounts import (
    build_dashboard_pilot_launch, PilotLaunchError,
)

_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_DENIED_PREFIXES = ("AUGMIS_", "DOCKER_", "LD_", "PYTHONPATH")

class RuntimeControlError(ValueError):
    pass


def validate_runtime_variables(data: dict) -> dict[str, str]:
    if not isinstance(data, dict) or len(data) > 64:
        raise RuntimeControlError("Variables must be a map with at most 64 keys")
    output = {}
    for key, value in data.items():
        if not isinstance(key, str) or not _NAME.fullmatch(key) or key.startswith(_DENIED_PREFIXES):
            raise RuntimeControlError("Invalid or reserved variable name")
        if not isinstance(value, str) or len(value.encode("utf-8")) > 2048 or "\x00" in value:
            raise RuntimeControlError("Invalid variable value")
        output[key] = value
    if sum(len(k.encode()) + len(v.encode()) for k,v in output.items()) > 16384:
        raise RuntimeControlError("Configuration exceeds 16KiB")
    return output


def get_runtime_config(db: Session, instance: ApplicationInstance) -> tuple[int | None, dict]:
    cfg = db.scalar(select(RuntimeInstanceConfig).where(
        RuntimeInstanceConfig.instance_id == instance.id,
        RuntimeInstanceConfig.tenant_id == instance.tenant_id,
    ))
    if cfg and cfg.secret_refs_json:
        # Never silently start with missing secrets; no provider configured yet.
        raise RuntimeControlError("Secret references require a configured provider")
    return (cfg.revision, dict(cfg.variables_json or {})) if cfg else (None, {})


def require_capacity(db: Session, tenant_id: uuid.UUID, *, add_containers: int = 1,
                     upgrade_instance_id: uuid.UUID | None = None):
    # Lock tenant row as a serialization point for quota reservations.
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if not tenant or tenant.status != "active":
        raise RuntimeControlError("Tenant is not active")
    quota = db.get(TenantRuntimeQuota, tenant_id)
    if not quota:
        return  # Existing installations unchanged until an explicit quota is set.
    usage = db.scalar(select(func.count(ApplicationDeployment.id))
        .join(ApplicationInstance, ApplicationInstance.id == ApplicationDeployment.instance_id)
        .where(ApplicationInstance.tenant_id == tenant_id,
               ApplicationDeployment.status.in_(("deploying", "running")))) or 0
    # One temporary surplus container is permitted only for an instance with
    # a currently running old deployment. This makes max=1 compatible with
    # health-gated in-place upgrades while limiting surge to one per tenant.
    surge = 0
    if upgrade_instance_id is not None:
        old_running = db.scalar(select(ApplicationDeployment.id).where(
            ApplicationDeployment.instance_id == upgrade_instance_id,
            ApplicationDeployment.status == "running",
        ).limit(1))
        surge = 1 if old_running else 0
    if usage + add_containers > quota.max_running_containers + surge:
        raise RuntimeControlError("Tenant runtime container quota exceeded")


def pinned_image_identity(db: Session, build: ApplicationBuild) -> str:
    """Use immutable Docker local image ID, never a mutable image tag for run."""
    if not build.image_ref:
        raise RuntimeControlError("Ready build has no image reference")
    try:
        identity = run_docker(["docker", "image", "inspect", "--format", "{{.Id}}", build.image_ref], timeout=30).strip()
    except DeploymentError as exc:
        raise RuntimeControlError("Image not present on runtime host") from exc
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", identity):
        raise RuntimeControlError("Docker returned an invalid immutable image ID")
    if build.immutable_image_id and build.immutable_image_id != identity:
        raise RuntimeControlError("Mutable image tag changed since first deployment")
    if not build.immutable_image_id:
        build.immutable_image_id = identity
        db.flush()
    return identity


def start_scoped_container(*, db: Session, instance: ApplicationInstance,
                           deployment: ApplicationDeployment, build: ApplicationBuild,
                           manifest: dict, container_name: str, labels: dict[str, str]):
    """Enforce tenant quota, config snapshot and immutable image identity."""
    from services.api.app.services.deployment_engine import start_container
    try:
        # C1-C: fail closed *before* allocation/launch. Unsupported database
        # manifests must never enter the ordinary published-port Docker path.
        # The existing C1-B4 CRUD runtime stays on its proven private path.
        if (manifest.get("addons") or {}).get("database") is not None:
            from services.api.app.services.aaps_deployment_contract import (
                DeploymentContractError, fail_closed_if_unimplemented,
            )
            try:
                fail_closed_if_unimplemented(
                    manifest,
                    legacy_crud=((manifest.get("metadata") or {}).get("id")
                                 == "augmis-crud-reference"),
                )
            except DeploymentContractError as exc:
                raise RuntimeControlError(str(exc)) from exc
        # Candidate's deployment row is already present. It reserves a quota
        # slot; do not add another slot in the count.
        surge_id = instance.id if (
            labels.get("augmis.upgrade_candidate") == "true"
            or labels.get("augmis.rollback_candidate") == "true"
        ) else None
        require_capacity(db, instance.tenant_id, add_containers=0,
                         upgrade_instance_id=surge_id)
        revision, variables = get_runtime_config(db, instance)
        identity = pinned_image_identity(db, build)
        # Existing instance-owned DBs may never silently fall back to a
        # direct-host-published container during upgrade or rollback.
        resource = db.scalar(select(ApplicationDatabaseResource).where(
            ApplicationDatabaseResource.instance_id == instance.id))
        protected_manifest = (manifest.get("metadata") or {}).get("id") == "augmis-crud-reference"
        if resource is not None and not protected_manifest and not (manifest.get("addons") or {}).get("database", {}).get("schema"):
            raise RuntimeControlError("Instance database requires private runtime")
        if protected_manifest:
            # Private runtime preparation includes reservation and trusted
            # DB/role/schema checks; exceptions are converted to safe codes.
            crud_runtime = prepare_private_crud_runtime(
                db=db, instance=instance, manifest=manifest)
            if crud_runtime is None:
                raise RuntimeControlError("Private CRUD runtime unavailable")
            protected = set(crud_runtime.environment)
            if protected.intersection(variables):
                raise RuntimeControlError("Runtime configuration overrides trusted identity")
        elif (manifest.get("addons") or {}).get("database") is not None:
            from services.api.app.services.aaps_generic_runtime import prepare_generic_private_runtime
            crud_runtime = prepare_generic_private_runtime(db=db, instance=instance, manifest=manifest)
            if set(crud_runtime.environment).intersection(variables):
                raise RuntimeControlError("Runtime configuration overrides trusted identity")
        else:
            crud_runtime = None
        pilot_runtime = build_dashboard_pilot_launch(
            tenant_id=instance.tenant_id,
            application_id=instance.application_id,
            instance_id=instance.id,
            image_id=identity,
        )
        deployment.config_revision = revision
        deployment.config_snapshot_json = variables  # Never secret values.
        deployment.deployed_image_id = identity
        db.commit()  # Recovery data is durable before starting Docker.
    except (RuntimeControlError, PilotLaunchError, CrudRuntimeError) as exc:
        raise DeploymentError(str(exc)) from exc
    return start_container(image_ref=identity, manifest=manifest,
                           container_name=container_name, labels=labels,
                            environment=variables, pilot_runtime=pilot_runtime,
                            crud_runtime=crud_runtime)
