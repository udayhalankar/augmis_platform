"""C1-C2: controlled schema install for supported declarative AAPS contracts.

Dev-only; called after authorized instance reservation, dedicated PostgreSQL and
restricted role provisioning. AAPS SQL files are NEVER executed. SQL is solely
compiler-generated with isolated, deterministic table/column grants and forced
RLS. Revisions are immutable: schema-changing upgrades require a later audited
migration mechanism. This is NOT a general SQL execution interface.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.core.config import settings as platform_settings
from services.api.app.models.platform import ApplicationInstance, ApplicationVersion
from services.api.app.models.runtime_control import ApplicationDatabaseResource
from services.api.app.services.aaps_declarative_schema import (
    SchemaContractError, read_declarative_schema, schema_sql, verification_sql,
)
from services.api.app.services.application_database_credentials import (
    RestrictedPostgresCredentials, runtime_role, _validate_resource,
)
from services.api.app.services.application_database_docker import (
    DatabaseInfrastructureError, DockerDatabaseSettings, DockerCall,
    PostgreSQLInfrastructure, docker_call,
)


class DeclaredSchemaError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def install_declared_schema(*, db: Session, instance_id: uuid.UUID,
                            settings: DockerDatabaseSettings,
                            call: DockerCall = docker_call) -> ApplicationDatabaseResource:
    settings.validate()
    if str(platform_settings.app_env).lower() not in {"dev", "development"} or \
            os.environ.get("AUGMIS_C1C_DECLARED_SCHEMA_ENABLED") != "1":
        raise DeclaredSchemaError("C1C_SCHEMA_DISABLED")
    instance = db.scalar(select(ApplicationInstance).where(
        ApplicationInstance.id == instance_id).with_for_update())
    if instance is None:
        raise DeclaredSchemaError("C1C_INSTANCE_NOT_FOUND")
    version = db.get(ApplicationVersion, instance.active_version_id)
    if version is None or version.application_id != instance.application_id:
        raise DeclaredSchemaError("C1C_APPLICATION_VERSION_MISMATCH")
    manifest = version.manifest
    try:
        plan = read_declarative_schema(manifest)
    except SchemaContractError as exc:
        raise DeclaredSchemaError(exc.code) from exc
    if plan is None:
        raise DeclaredSchemaError("C1C_SCHEMA_CONTRACT_REQUIRED")
    row = db.scalar(select(ApplicationDatabaseResource).where(
        ApplicationDatabaseResource.instance_id == instance.id).with_for_update())
    _validate_resource(instance, row)
    if row.status not in {"credentials_ready", "ready"}:
        raise DeclaredSchemaError("C1C_CREDENTIALS_NOT_READY")
    if row.migration_revision not in {None, plan.revision}:
        raise DeclaredSchemaError("C1C_SCHEMA_REVISION_CHANGE_REQUIRES_MIGRATION")
    driver = PostgreSQLInfrastructure(settings, call=call)
    driver.ensure_network(row)
    driver.ensure_postgres(row)
    driver.assert_database_ready(row)
    creds = RestrictedPostgresCredentials(driver)
    role = runtime_role(instance.id)
    creds._volume_read(row)
    creds.verify_runtime_login(row, role)

    def admin(sql: str) -> str:
        return driver._docker("exec", "-i", "--user", "postgres", row.container_name,
                             "psql", "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1",
                             "-U", "postgres", "-d", row.database_name,
                             payload=sql.encode("utf-8")).strip()

    if row.status != "ready":
        row.status = "schema_setup"
        row.error_code = None
        db.commit()
        try:
            admin(schema_sql(plan, runtime_role=role))
            if admin(verification_sql(plan, runtime_role=role)) != "1":
                raise DeclaredSchemaError("C1C_SCHEMA_RLS_VERIFICATION_FAILED")
        except Exception as exc:
            row.status = "credentials_ready"
            row.error_code = (exc.code if isinstance(exc, (DatabaseInfrastructureError, DeclaredSchemaError))
                              else "C1C_SCHEMA_INSTALL_FAILED")
            db.commit()
            raise DeclaredSchemaError(row.error_code) from exc
        row.migration_revision = plan.revision
        row.status = "ready"
        row.ready_at = datetime.now(timezone.utc)
        row.error_code = None
        db.commit()
    elif admin(verification_sql(plan, runtime_role=role)) != "1":
        raise DeclaredSchemaError("C1C_SCHEMA_READY_STATE_DRIFT")
    return row
