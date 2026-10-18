"""C1-B2 (development-only): instance-scoped restricted PostgreSQL login.

Uses C1-A's trusted resource row and C1-B1's private database. No publisher
input or browser identity may reach role/volume names. The application login
password is stored in its own Docker volume, NEVER the postgres admin volume.

This stage intentionally DOES NOT make an instance application-ready. Schema
migrations, enforced RLS and private authenticated app ingress remain separate
prerequisites. Do not invoke this from Open Application until they are ready.
"""
from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.models.platform import ApplicationInstance
from services.api.app.models.runtime_control import ApplicationDatabaseResource
from services.api.app.services.application_database_docker import (
    DatabaseInfrastructureError, DockerDatabaseSettings, PostgreSQLInfrastructure,
    docker_call, DockerCall,
)
from services.api.app.services.application_database_provisioning import (
    DatabaseRequirement, database_resource_plan, ApplicationDatabaseError,
)

PASSWORD_FILE = "/run/secrets/db_password"
_PASSWORD_RE = re.compile(r"[A-Za-z0-9_-]{40,128}\Z")


def runtime_role(instance_id: uuid.UUID) -> str:
    if not isinstance(instance_id, uuid.UUID):
        raise DatabaseInfrastructureError("C1B2_INVALID_INSTANCE_ID")
    return "augmis_rw_" + instance_id.hex


def _validate_resource(instance: ApplicationInstance, row: ApplicationDatabaseResource) -> None:
    if row is None or row.tenant_id != instance.tenant_id or row.instance_id != instance.id:
        raise DatabaseInfrastructureError("C1B2_RESERVATION_MISMATCH")
    try:
        plan = database_resource_plan(
            tenant_id=instance.tenant_id, instance_id=instance.id,
            requirement=DatabaseRequirement(row.engine, row.engine_version, row.storage_request),
        )
    except ApplicationDatabaseError as exc:
        raise DatabaseInfrastructureError("C1B2_REQUIREMENT_UNSUPPORTED") from exc
    for key in ("database_name", "database_host_alias", "network_name", "container_name",
                "data_volume", "bootstrap_secret_volume", "runtime_secret_volume"):
        if getattr(row, key) != getattr(plan, key):
            raise DatabaseInfrastructureError("C1B2_IDENTITY_DRIFT")


class RestrictedPostgresCredentials:
    def __init__(self, driver: PostgreSQLInfrastructure):
        self.driver = driver

    def _volume_read(self, row: ApplicationDatabaseResource) -> str:
        # Docker stdout passes only to this trusted control-plane process.
        # Callers MUST NOT log or return the secret to an API response.
        result = self.driver._docker(
            "run", "--rm", "--network", "none", "--read-only",
            "--user", "10001:10001", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "--mount", f"type=volume,source={row.runtime_secret_volume},target=/run/secrets,readonly",
            "--entrypoint", "/bin/sh", self.driver.settings.image_id,
            "-c", "set -eu; test -f /run/secrets/db_password; test ! -L /run/secrets/db_password; "
                  "test \"$(stat -c %a /run/secrets/db_password)\" = 400; "
                  "test \"$(stat -c %u /run/secrets/db_password)\" = 10001; "
                  "cat /run/secrets/db_password",
        )
        if not _PASSWORD_RE.fullmatch(result):
            raise DatabaseInfrastructureError("C1B2_RUNTIME_SECRET_INVALID")
        return result

    def ensure_password(self, row: ApplicationDatabaseResource) -> str:
        was_new = self.driver.ensure_volume(row.runtime_secret_volume, row.instance_id)
        if was_new:
            password = secrets.token_urlsafe(48)
            if not _PASSWORD_RE.fullmatch(password):
                raise DatabaseInfrastructureError("C1B2_SECRET_GENERATION_ERROR")
            # Never use chmod 0444: only the runtime UID may read this file.
            # The PostgreSQL superuser password is in a DIFFERENT volume.
            self.driver._secret_helper(
                row.runtime_secret_volume,
                "set -eu; umask 077; test ! -e /bootstrap/db_password; "
                "cat > /bootstrap/db_password; chown 10001:10001 /bootstrap/db_password; "
                "chmod 0400 /bootstrap/db_password", readonly=False,
                payload=password.encode("ascii"),
            )
        return self._volume_read(row)

    def _admin_sql(self, row: ApplicationDatabaseResource, sql: str) -> str:
        return self.driver._docker(
            "exec", "-i", "--user", "postgres", row.container_name,
            "psql", "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1",
            "-U", "postgres", "-d", row.database_name,
            payload=sql.encode("utf-8"),
        ).strip()

    def _role_exists(self, row: ApplicationDatabaseResource, role: str) -> bool:
        result = self._admin_sql(row, f"SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN '1' ELSE '0' END;\n")
        if result not in {"0", "1"}:
            raise DatabaseInfrastructureError("C1B2_ROLE_INSPECTION_INVALID")
        return result == "1"

    def _assert_restricted_role(self, row: ApplicationDatabaseResource, role: str) -> None:
        result = self._admin_sql(row, (
            "SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_roles "
            f"WHERE rolname='{role}' AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb "
            "AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls) "
            "THEN '1' ELSE '0' END;\n"
        ))
        if result != "1":
            raise DatabaseInfrastructureError("C1B2_ROLE_PERMISSIONS_INVALID")

    def ensure_role(self, row: ApplicationDatabaseResource, password: str) -> str:
        if not _PASSWORD_RE.fullmatch(password):
            raise DatabaseInfrastructureError("C1B2_RUNTIME_SECRET_INVALID")
        role = runtime_role(row.instance_id)
        if not self._role_exists(row, role):
            # Password travels over stdin, never Docker command arguments.
            self._admin_sql(row, (
                f"CREATE ROLE {role} WITH LOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                f"NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '{password}';\n"
            ))
        self._assert_restricted_role(row, role)
        # Idempotent grants repair an interrupted setup after CREATE ROLE.
        # They give NO table DML and NO schema creation privileges.
        self._admin_sql(row, (
            f"REVOKE ALL ON DATABASE {row.database_name} FROM PUBLIC;\n"
            f"REVOKE CREATE ON SCHEMA public FROM PUBLIC;\n"
            f"GRANT CONNECT ON DATABASE {row.database_name} TO {role};\n"
            f"GRANT USAGE ON SCHEMA public TO {role};\n"
        ))
        return role

    def verify_runtime_login(self, row: ApplicationDatabaseResource, role: str) -> None:
        result = self.driver._docker(
            "run", "--rm", "--network", row.network_name,
            "--read-only", "--user", "10001:10001", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "--mount", f"type=volume,source={row.runtime_secret_volume},target=/run/secrets,readonly",
            "--env", f"PGHOST={row.database_host_alias}",
            "--env", f"PGDATABASE={row.database_name}",
            "--env", f"PGUSER={role}",
            "--entrypoint", "/bin/sh", self.driver.settings.image_id,
            "-c", "set -eu; export PGPASSWORD=\"$(cat /run/secrets/db_password)\"; "
                  "exec psql -X -q -t -A -w -v ON_ERROR_STOP=1 -c 'SELECT current_user'",
        ).strip()
        if result != role:
            raise DatabaseInfrastructureError("C1B2_RUNTIME_LOGIN_MISMATCH")


def provision_restricted_database_login(
    *, db: Session, instance_id: uuid.UUID,
    settings: DockerDatabaseSettings, call: DockerCall = docker_call,
    recover_stale: bool = False,
) -> ApplicationDatabaseResource:
    """Requires already-provisioned and healthy C1-B1 database.

    Never create a runtime role until DB infrastructure is explicitly ready.
    Retains the resource and secret volume on failure for authorized recovery.
    """
    settings.validate()
    instance = db.scalar(select(ApplicationInstance).where(
        ApplicationInstance.id == instance_id).with_for_update())
    if instance is None:
        raise DatabaseInfrastructureError("C1B2_INSTANCE_NOT_FOUND")
    row = db.scalar(select(ApplicationDatabaseResource).where(
        ApplicationDatabaseResource.instance_id == instance_id).with_for_update())
    _validate_resource(instance, row)
    if row.status == "credential_setup":
        updated = getattr(row, "updated_at", None)
        stale = (updated is not None and updated.tzinfo is not None and
                 datetime.now(timezone.utc) - updated >= timedelta(minutes=15))
        if not (recover_stale and stale):
            raise DatabaseInfrastructureError("C1B2_SETUP_ALREADY_IN_PROGRESS")
    elif row.status not in {"database_ready", "credentials_ready"}:
        raise DatabaseInfrastructureError("C1B2_DATABASE_INFRASTRUCTURE_NOT_READY")
    if row.database_image_id != settings.image_id:
        raise DatabaseInfrastructureError("C1B2_IMAGE_ID_MISMATCH")
    # Do not let two separate control-plane workers create different passwords.
    row.status = "credential_setup"
    row.error_code = None
    db.commit()
    driver = PostgreSQLInfrastructure(settings, call=call)
    try:
        driver.ensure_network(row)
        driver.ensure_postgres(row)
        driver.assert_database_ready(row)
        credentials = RestrictedPostgresCredentials(driver)
        password = credentials.ensure_password(row)
        role = credentials.ensure_role(row, password)
        credentials.verify_runtime_login(row, role)
    except DatabaseInfrastructureError as exc:
        row.status = "failed"
        row.error_code = exc.code
        db.commit()
        raise
    except Exception as exc:
        row.status = "failed"
        row.error_code = "C1B2_CREDENTIAL_SETUP_FAILED"
        db.commit()
        raise DatabaseInfrastructureError("C1B2_CREDENTIAL_SETUP_FAILED") from exc
    row.status = "credentials_ready"
    row.error_code = None
    # Do not set ready_at: application schema and RLS have not been validated.
    db.commit()
    return row
