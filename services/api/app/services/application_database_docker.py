"""C1-B1 — DEVELOPMENT-ONLY per-instance PostgreSQL Docker foundation.

IMPORTANT: This is an opt-in infrastructure phase, NOT full application readiness.
It creates a private network, independent data and bootstrap-secret volumes,
and a dedicated PostgreSQL 15 container. It does NOT provision application roles,
run app migrations, or start application containers. C1-A `ready` is RESERVED
for the later C1-B2 migration/role/connection phase.

Only call after backend authorization, subscription/version/entitlement checks,
logical-instance reservation, and C1-A reserve_application_database().
No Docker or DB operations occur from importing this module.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.models.platform import ApplicationInstance
from services.api.app.models.runtime_control import ApplicationDatabaseResource
from services.api.app.services.application_database_provisioning import (
    ApplicationDatabaseError, DatabaseRequirement, database_resource_plan,
)

_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ALLOWED_STATES = frozenset({"reserved", "failed", "database_ready", "ready"})
_SECRET_PATH = "/run/bootstrap/postgres_password"
_LABEL = "augmis.database_instance_id"


class DatabaseInfrastructureError(ValueError):
    """Fixed, non-sensitive error code for operator diagnostics."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DockerDatabaseSettings:
    image_id: str
    enabled: bool
    environment: str
    accept_unenforced_storage_request: bool

    @classmethod
    def from_platform(cls, *, platform_environment: str) -> "DockerDatabaseSettings":
        return cls(
            image_id=os.environ.get("AUGMIS_C1B_POSTGRES_IMAGE_ID", "").strip(),
            enabled=os.environ.get("AUGMIS_C1B_DEV_DB_ENABLED") == "1",
            environment=platform_environment,
            accept_unenforced_storage_request=(
                os.environ.get("AUGMIS_C1B_DEV_UNQUOTED_VOLUME_OK") == "1"
            ),
        )

    def validate(self) -> None:
        if self.environment.lower() not in {"dev", "development"} or not self.enabled:
            raise DatabaseInfrastructureError("C1B_DEVELOPMENT_ONLY")
        if not self.accept_unenforced_storage_request:
            raise DatabaseInfrastructureError("C1B_STORAGE_QUOTA_NOT_ENFORCED")
        if not _IMAGE_ID.fullmatch(self.image_id):
            raise DatabaseInfrastructureError("C1B_PINNED_POSTGRES_IMAGE_REQUIRED")


# Never include secret bytes in command argv, Docker -e, model rows, logs or errors.
DockerCall = Callable[[list[str], bytes | None], str]


def docker_call(command: list[str], input_bytes: bytes | None = None) -> str:
    try:
        io_arg = {"input": input_bytes} if input_bytes is not None else {"stdin": subprocess.DEVNULL}
        result = subprocess.run(
            command, capture_output=True, timeout=90, check=False, **io_arg
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DatabaseInfrastructureError("C1B_DOCKER_UNAVAILABLE") from exc
    if result.returncode != 0:
        # Docker/psql output may contain credentials, host paths, or DB errors.
        # Never return raw stdout/stderr to a public API response or audit log.
        raise DatabaseInfrastructureError("C1B_DOCKER_OPERATION_FAILED")
    return result.stdout.decode("utf-8", errors="replace").strip()


class PostgreSQLInfrastructure:
    """Adapter: all operations use a trusted immutable image and a Docker CLI."""

    def __init__(self, settings: DockerDatabaseSettings, call: DockerCall = docker_call):
        self.settings = settings
        self.call = call
        settings.validate()

    def _docker(self, *args: str, payload: bytes | None = None) -> str:
        return self.call(["docker", *args], payload)

    def verify_image(self) -> None:
        image_id = self._docker("image", "inspect", "--format", "{{.Id}}", self.settings.image_id)
        if image_id != self.settings.image_id:
            raise DatabaseInfrastructureError("C1B_POSTGRES_IMAGE_ID_MISMATCH")
        # Check the binary of the pinned image rather than trusting a mutable tag.
        version = self._docker("run", "--rm", "--network", "none", "--entrypoint", "postgres",
                               self.settings.image_id, "--version")
        if not re.search(r"PostgreSQL\) 15(?:\.|\s|$)", version):
            raise DatabaseInfrastructureError("C1B_POSTGRES_15_REQUIRED")

    def _names(self, object_type: str) -> set[str]:
        if object_type == "network":
            output = self._docker("network", "ls", "--format", "{{.Name}}")
        elif object_type == "volume":
            output = self._docker("volume", "ls", "--format", "{{.Name}}")
        elif object_type == "container":
            output = self._docker("container", "ls", "--all", "--format", "{{.Names}}")
        else:
            raise AssertionError(object_type)
        return set(output.splitlines())

    def _inspect(self, object_type: str, name: str) -> dict:
        data = json.loads(self._docker(object_type, "inspect", name))
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise DatabaseInfrastructureError("C1B_INVALID_DOCKER_INSPECTION")
        return data[0]

    @staticmethod
    def _required_labels(instance_id: uuid.UUID) -> dict[str, str]:
        return {"augmis.managed": "true", _LABEL: str(instance_id)}

    @staticmethod
    def _ownership(actual: dict, expected: dict) -> None:
        if not isinstance(actual, dict) or any(actual.get(k) != v for k, v in expected.items()):
            raise DatabaseInfrastructureError("C1B_FOREIGN_DOCKER_RESOURCE")

    def ensure_network(self, row: ApplicationDatabaseResource) -> None:
        labels = self._required_labels(row.instance_id)
        if row.network_name not in self._names("network"):
            self._docker("network", "create", "--driver", "bridge", "--internal",
                         "--label", "augmis.managed=true", "--label", f"{_LABEL}={row.instance_id}",
                         row.network_name)
        network = self._inspect("network", row.network_name)
        self._ownership(network.get("Labels") or {}, labels)
        if network.get("Internal") is not True or network.get("Driver") != "bridge":
            raise DatabaseInfrastructureError("C1B_NETWORK_NOT_PRIVATE")

    def ensure_volume(self, name: str, instance_id: uuid.UUID) -> bool:
        was_new = name not in self._names("volume")
        if was_new:
            self._docker("volume", "create", "--label", "augmis.managed=true",
                         "--label", f"{_LABEL}={instance_id}", name)
        volume = self._inspect("volume", name)
        self._ownership(volume.get("Labels") or {}, self._required_labels(instance_id))
        if volume.get("Driver") != "local":
            raise DatabaseInfrastructureError("C1B_UNSUPPORTED_VOLUME_DRIVER")
        return was_new

    def _secret_helper(self, volume: str, script: str, *, readonly: bool,
                       payload: bytes | None = None) -> None:
        mount = f"type=volume,source={volume},target=/bootstrap"
        if readonly:
            mount += ",readonly"
        self._docker("run", "--rm", "-i", "--network", "none", "--read-only",
                     "--security-opt", "no-new-privileges:true", "--user", "0:0",
                     "--mount", mount, "--entrypoint", "/bin/sh",
                     self.settings.image_id, "-c", script, payload=payload)

    def ensure_bootstrap_password(self, row: ApplicationDatabaseResource, *, fresh: bool) -> None:
        if fresh:
            password = secrets.token_urlsafe(48).encode("ascii")
            script = (
                "set -eu; umask 077; "
                "test ! -e /bootstrap/postgres_password; "
                "cat > /bootstrap/postgres_password; "
                "chown postgres:postgres /bootstrap/postgres_password; "
                "chmod 0400 /bootstrap/postgres_password"
            )
            self._secret_helper(row.bootstrap_secret_volume, script, readonly=False, payload=password)
        # On re-entry, NEVER replace an existing bootstrap password: the named
        # PostgreSQL data volume may already have been initialized with it.
        verify = (
            "set -eu; test -f /bootstrap/postgres_password; "
            "test ! -L /bootstrap/postgres_password; "
            "test -s /bootstrap/postgres_password; "
            'test "$(stat -c %a /bootstrap/postgres_password)" = 400; '
            'test "$(stat -c %U /bootstrap/postgres_password)" = postgres'
        )
        self._secret_helper(row.bootstrap_secret_volume, verify, readonly=True)

    def ensure_postgres(self, row: ApplicationDatabaseResource) -> None:
        labels = self._required_labels(row.instance_id)
        if row.container_name not in self._names("container"):
            self._docker(
                "run", "-d", "--name", row.container_name,
                "--network", row.network_name, "--network-alias", row.database_host_alias,
                "--label", "augmis.managed=true", "--label", f"{_LABEL}={row.instance_id}",
                "--mount", f"type=volume,source={row.data_volume},target=/var/lib/postgresql/data",
                "--mount", f"type=volume,source={row.bootstrap_secret_volume},target=/run/bootstrap,readonly",
                "--env", "POSTGRES_PASSWORD_FILE=" + _SECRET_PATH,
                "--env", "POSTGRES_DB=" + row.database_name,
                "--env", "POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256",
                "--pids-limit", "128", "--memory", "768m", "--cpus", "1",
                "--security-opt", "no-new-privileges:true",
                "--restart", "unless-stopped", self.settings.image_id,
            )
        container = self._inspect("container", row.container_name)
        self._ownership((container.get("Config") or {}).get("Labels") or {}, labels)
        if container.get("Image") != self.settings.image_id:
            raise DatabaseInfrastructureError("C1B_DATABASE_IMAGE_DRIFT")
        host = container.get("HostConfig") or {}
        if host.get("PortBindings") not in (None, {}):
            raise DatabaseInfrastructureError("C1B_DATABASE_PORT_PUBLISHED")
        networks = (container.get("NetworkSettings") or {}).get("Networks") or {}
        if set(networks) != {row.network_name}:
            raise DatabaseInfrastructureError("C1B_DATABASE_NETWORK_DRIFT")
        mounted = {m.get("Destination"): (m.get("Name"), bool(m.get("RW")))
                   for m in container.get("Mounts") or []}
        if mounted.get("/var/lib/postgresql/data") != (row.data_volume, True):
            raise DatabaseInfrastructureError("C1B_DATABASE_VOLUME_DRIFT")
        if mounted.get("/run/bootstrap") != (row.bootstrap_secret_volume, False):
            raise DatabaseInfrastructureError("C1B_BOOTSTRAP_SECRET_MOUNT_DRIFT")
        # Treat stopped resources as a recovery case; don't silently restart or
        # rebuild a data-bearing container as part of a new deployment request.
        if (container.get("State") or {}).get("Running") is not True:
            raise DatabaseInfrastructureError("C1B_DATABASE_NOT_RUNNING")

    def assert_database_ready(self, row: ApplicationDatabaseResource) -> None:
        # The initial data volume may require initdb; wait for it instead of
        # failing immediately after Docker reports that the container launched.
        # Does not expose a DB host port and does not perform any writes.
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                self._docker("exec", row.container_name, "pg_isready", "-q", "-U", "postgres",
                             "-d", row.database_name)
                response = self._docker("exec", row.container_name, "psql", "-X", "-q", "-t", "-A",
                                        "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", row.database_name,
                                        "-c", "SELECT 1")
                if response.strip() != "1":
                    raise DatabaseInfrastructureError("C1B_DATABASE_QUERY_UNEXPECTED")
                return
            except DatabaseInfrastructureError as exc:
                if exc.code not in {"C1B_DOCKER_OPERATION_FAILED", "C1B_DATABASE_QUERY_UNEXPECTED"}:
                    raise
                time.sleep(2)
        raise DatabaseInfrastructureError("C1B_DATABASE_READY_TIMEOUT")


def provision_private_postgres(
    *, db: Session, instance_id: uuid.UUID,
    settings: DockerDatabaseSettings, call: DockerCall = docker_call,
) -> ApplicationDatabaseResource:
    """Provision Docker resources for a pre-reserved C1-A DB instance.

    Explicit opt-in only; this function is NOT wired into Open Application.
    Never destroys or prunes containers, networks or volumes on error.
    Reservation must already exist; no caller-provided resource names allowed.
    """
    settings.validate()
    instance = db.scalar(select(ApplicationInstance).where(
        ApplicationInstance.id == instance_id).with_for_update())
    if instance is None:
        raise DatabaseInfrastructureError("C1B_INSTANCE_NOT_FOUND")
    row = db.scalar(select(ApplicationDatabaseResource).where(
        ApplicationDatabaseResource.instance_id == instance_id).with_for_update())
    if row is None or row.tenant_id != instance.tenant_id:
        raise DatabaseInfrastructureError("C1B_RESERVATION_REQUIRED")
    requirement = DatabaseRequirement(engine=row.engine, version=row.engine_version,
                                      storage=row.storage_request)
    try:
        plan = database_resource_plan(tenant_id=instance.tenant_id,
                                      instance_id=instance.id, requirement=requirement)
    except ApplicationDatabaseError as exc:
        raise DatabaseInfrastructureError("C1B_UNSUPPORTED_RESERVED_DATABASE") from exc
    for attr in ("database_name", "database_host_alias", "network_name", "container_name",
                 "data_volume", "bootstrap_secret_volume"):
        if getattr(row, attr) != getattr(plan, attr):
            raise DatabaseInfrastructureError("C1B_RESOURCE_IDENTITY_DRIFT")

    if row.status == "provisioning":
        raise DatabaseInfrastructureError("C1B_PROVISIONING_ALREADY_IN_PROGRESS")
    if row.status not in _ALLOWED_STATES:
        raise DatabaseInfrastructureError("C1B_UNEXPECTED_RESOURCE_STATE")

    # Only mark C1-A 'ready' in the future after restricted roles, migrations,
    # policies and credential delivery have been verified (C1-B2/C1-C).
    old_status = row.status
    row.status = "provisioning"
    row.error_code = None
    row.attempts = int(row.attempts or 0) + 1
    db.commit()  # other workers see the reservation; no lock held during Docker

    driver = PostgreSQLInfrastructure(settings, call=call)
    try:
        driver.verify_image()
        driver.ensure_network(row)
        driver.ensure_volume(row.data_volume, row.instance_id)
        fresh_secret = driver.ensure_volume(row.bootstrap_secret_volume, row.instance_id)
        driver.ensure_bootstrap_password(row, fresh=fresh_secret)
        driver.ensure_postgres(row)
        driver.assert_database_ready(row)
    except DatabaseInfrastructureError as exc:
        row.status = "failed"
        row.error_code = exc.code
        db.commit()
        raise
    except Exception as exc:
        row.status = "failed"
        row.error_code = "C1B_UNEXPECTED_PROVISIONING_FAILURE"
        db.commit()
        raise DatabaseInfrastructureError("C1B_UNEXPECTED_PROVISIONING_FAILURE") from exc

    row.database_image_id = settings.image_id
    row.status = old_status if old_status == "ready" else "database_ready"
    # ready_at stays NULL. Database role/schema security has not been validated.
    db.commit()
    return row
