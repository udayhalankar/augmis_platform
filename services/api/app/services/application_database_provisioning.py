"""C1-A: safe, idempotent APPLICATION DATABASE RESERVATION (no Docker I/O).

This is deliberately the database-resource foundation, not a live provisioner.
The next C1-B module will provision resources using the reserved identity.

Never trust a requested tenant, application, or instance identity from a browser.
Call only after the existing AUGMIS membership, subscription, entitlement, and
application.deploy authorization checks have succeeded.

NO passwords, URLs containing passwords, or private keys belong in model rows.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.models.platform import ApplicationInstance
from services.api.app.models.runtime_control import ApplicationDatabaseResource


class ApplicationDatabaseError(ValueError):
    """Non-sensitive, expected provisioning-contract failure."""


@dataclass(frozen=True)
class DatabaseRequirement:
    engine: str
    version: str
    storage: str


@dataclass(frozen=True)
class DatabaseResourcePlan:
    tenant_id: uuid.UUID
    instance_id: uuid.UUID
    requirement: DatabaseRequirement
    database_name: str
    database_host_alias: str
    network_name: str
    container_name: str
    data_volume: str
    bootstrap_secret_volume: str
    runtime_secret_volume: str


# Explicitly bounded first supported engine. Do not imply that schema-advertised
# MySQL is already provisionable; it requires a separate adapter.
_ALLOWED_STORAGE = re.compile(r"^([1-9][0-9]?)Gi$")
_READY = "ready"


def read_database_requirement(manifest: dict[str, Any]) -> DatabaseRequirement | None:
    """Read AAPS addon requirements without trusting arbitrary manifest keys."""
    if not isinstance(manifest, dict):
        raise ApplicationDatabaseError("Invalid application manifest")
    addons = manifest.get("addons") or {}
    if not isinstance(addons, dict):
        raise ApplicationDatabaseError("Invalid application addons")
    database = addons.get("database")
    if database is None:
        return None
    if not isinstance(database, dict):
        raise ApplicationDatabaseError("Invalid database addon declaration")
    if database.get("type") != "postgresql":
        raise ApplicationDatabaseError("Database engine is not supported by C1")
    version = str(database.get("version", "15"))
    if version != "15":
        raise ApplicationDatabaseError("Only PostgreSQL 15 is supported by C1")
    storage = str(database.get("storage", "1Gi"))
    match = _ALLOWED_STORAGE.fullmatch(storage)
    if match is None or not 1 <= int(match.group(1)) <= 50:
        raise ApplicationDatabaseError("C1 storage request must be 1Gi through 50Gi")
    # Storage is a request/limit, not a statement that Docker named volumes
    # themselves enforce a 50 GiB quota. Provisioning must implement that policy.
    return DatabaseRequirement(engine="postgresql", version=version, storage=storage)


def database_resource_plan(
    *, tenant_id: uuid.UUID, instance_id: uuid.UUID,
    requirement: DatabaseRequirement,
) -> DatabaseResourcePlan:
    """Deterministically derive unique names from the entire instance UUID.

    The names remain stable across retries, restarts, upgrades and rollbacks.
    Short aliases never cross private-network boundaries.
    """
    if not isinstance(tenant_id, uuid.UUID) or not isinstance(instance_id, uuid.UUID):
        raise ApplicationDatabaseError("Trusted tenant and instance UUIDs are required")
    if requirement.engine != "postgresql" or requirement.version != "15":
        raise ApplicationDatabaseError("Unsupported database requirement")
    suffix = instance_id.hex  # full 128-bit identifier; collision-resistant names
    return DatabaseResourcePlan(
        tenant_id=tenant_id, instance_id=instance_id, requirement=requirement,
        database_name="augmis_app", database_host_alias="augmis-db",
        network_name=f"augmis-prv-{suffix}",
        container_name=f"augmis-pg-{suffix}",
        data_volume=f"augmis-pgdata-{suffix}",
        bootstrap_secret_volume=f"augmis-pgbootstrap-{suffix}",
        runtime_secret_volume=f"augmis-pgruntime-{suffix}",
    )


def reserve_application_database(
    *, db: Session, instance_id: uuid.UUID, manifest: dict[str, Any],
) -> ApplicationDatabaseResource | None:
    """Reserve unique resource names in the Control Plane transaction.

    - No Docker, SQL initialization or credential generation occurs here.
    - Serializes competing attempts by locking the EXISTING instance row.
    - Adds the resource row and flushes; CALLER owns commit/rollback.
    - Existing rows are never overwritten, including FAILED/RETAINED rows.
    - Rejects database removal in subsequent versions until an audited
      explicit data-retention/decommission procedure is implemented.
    """
    if not isinstance(instance_id, uuid.UUID):
        raise ApplicationDatabaseError("Trusted instance UUID is required")

    # Lock parent first so two worker/API processes cannot reserve twice.
    instance = db.scalar(
        select(ApplicationInstance)
        .where(ApplicationInstance.id == instance_id)
        .with_for_update()
    )
    if instance is None:
        raise ApplicationDatabaseError("Application instance does not exist")

    existing = db.scalar(
        select(ApplicationDatabaseResource)
        .where(ApplicationDatabaseResource.instance_id == instance.id)
        .with_for_update()
    )
    requirement = read_database_requirement(manifest)
    if requirement is None:
        if existing is not None:
            raise ApplicationDatabaseError("Application cannot drop its allocated database implicitly")
        return None

    plan = database_resource_plan(
        tenant_id=instance.tenant_id, instance_id=instance.id,
        requirement=requirement,
    )

    if existing is not None:
        if (
            existing.tenant_id != instance.tenant_id
            or existing.engine != requirement.engine
            or existing.engine_version != requirement.version
            or existing.database_name != plan.database_name
            or existing.database_host_alias != plan.database_host_alias
            or existing.network_name != plan.network_name
            or existing.container_name != plan.container_name
            or existing.data_volume != plan.data_volume
            or existing.bootstrap_secret_volume != plan.bootstrap_secret_volume
            or existing.runtime_secret_volume != plan.runtime_secret_volume
            or existing.storage_request != requirement.storage
        ):
            raise ApplicationDatabaseError("Existing database reservation conflicts with application requirements")
        return existing

    resource = ApplicationDatabaseResource(
        tenant_id=instance.tenant_id,
        instance_id=instance.id,
        engine=requirement.engine,
        engine_version=requirement.version,
        storage_request=requirement.storage,
        database_name=plan.database_name,
        database_host_alias=plan.database_host_alias,
        network_name=plan.network_name,
        container_name=plan.container_name,
        data_volume=plan.data_volume,
        bootstrap_secret_volume=plan.bootstrap_secret_volume,
        runtime_secret_volume=plan.runtime_secret_volume,
        status="reserved",
        attempts=0,
    )
    db.add(resource)
    db.flush()
    return resource


def require_ready_application_database(
    *, db: Session, instance: ApplicationInstance, manifest: dict[str, Any],
) -> ApplicationDatabaseResource | None:
    """Fail closed if a DB-backed app is not yet provisioned.

    C1-B must first allocate the Docker/secret resources and record `ready`.
    This function is intended for the future launch integration point.
    """
    requirement = read_database_requirement(manifest)
    existing = db.scalar(
        select(ApplicationDatabaseResource)
        .where(ApplicationDatabaseResource.instance_id == instance.id)
    )
    if requirement is None:
        if existing is not None:
            raise ApplicationDatabaseError("Application cannot drop its allocated database implicitly")
        return None
    if existing is None or existing.tenant_id != instance.tenant_id:
        raise ApplicationDatabaseError("Application database has not been reserved")
    if existing.status != _READY:
        raise ApplicationDatabaseError("Application database has not completed provisioning")
    if existing.engine != requirement.engine or existing.engine_version != requirement.version:
        raise ApplicationDatabaseError("Application database engine does not match the manifest")
    if existing.storage_request != requirement.storage:
        raise ApplicationDatabaseError("Application database storage request changed; explicit migration required")
    return existing
