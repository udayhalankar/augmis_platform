"""Offline C1-B1 contract tests. Never contacts Docker or a live database.

From AUGMIS repository root:
    python -m pytest -q tools/test_c1b1_private_postgres.py
"""
from __future__ import annotations

import json
import uuid

import pytest

from services.api.app.models.platform import ApplicationInstance
from services.api.app.models.runtime_control import ApplicationDatabaseResource
from services.api.app.services.application_database_provisioning import (
    reserve_application_database, require_ready_application_database,
    ApplicationDatabaseError,
)
from services.api.app.services.application_database_docker import (
    DatabaseInfrastructureError, DockerDatabaseSettings, provision_private_postgres,
)


IMAGE = "sha256:" + "a" * 64


def settings(**overrides):
    options = dict(image_id=IMAGE, enabled=True, environment="development",
                   accept_unenforced_storage_request=True)
    options.update(overrides)
    return DockerDatabaseSettings(**options)


class FakeSession:
    def __init__(self):
        self.instance = ApplicationInstance(id=uuid.uuid4(), tenant_id=uuid.uuid4())
        self.row = None
        self.commits = 0

    def scalar(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is ApplicationInstance:
            return self.instance
        if entity is ApplicationDatabaseResource:
            return self.row
        raise AssertionError(entity)

    def add(self, resource):
        assert self.row is None
        self.row = resource

    def flush(self):
        pass

    def commit(self):
        self.commits += 1


def reserved():
    session = FakeSession()
    row = reserve_application_database(
        db=session, instance_id=session.instance.id,
        manifest={"addons": {"database": {"type": "postgresql", "version": "15", "storage": "1Gi"}}},
    )
    return session, row


class FakeDocker:
    def __init__(self):
        self.networks = {}
        self.volumes = {}
        self.containers = {}
        self.seeded = set()
        self.commands = []
        self.bootstrap_payloads = []
        self.pg_error = False

    def __call__(self, cmd, payload=None):
        assert cmd[0] == "docker"
        self.commands.append((list(cmd), payload))
        tail = cmd[1:]
        if tail[:2] == ["image", "inspect"]:
            return IMAGE
        if tail[:2] == ["run", "--rm"] and "--entrypoint" in tail and tail[tail.index("--entrypoint")+1] == "postgres":
            return "postgres (PostgreSQL) 15.17"
        if tail[:2] == ["network", "ls"]:
            return "\n".join(self.networks)
        if tail[:2] == ["volume", "ls"]:
            return "\n".join(self.volumes)
        if tail[:3] == ["container", "ls", "--all"]:
            return "\n".join(self.containers)
        if tail[:2] == ["network", "create"]:
            name = tail[-1]
            self.networks[name] = dict(Internal="--internal" in tail, Driver="bridge",
                                       Labels=self._labels(tail))
            return name
        if tail[:2] == ["volume", "create"]:
            name = tail[-1]
            self.volumes[name] = dict(Driver="local", Labels=self._labels(tail))
            return name
        if tail[:2] == ["network", "inspect"]:
            return json.dumps([self.networks[tail[-1]]])
        if tail[:2] == ["volume", "inspect"]:
            return json.dumps([self.volumes[tail[-1]]])
        if tail[:2] == ["container", "inspect"]:
            return json.dumps([self.containers[tail[-1]]])
        if tail[0] == "run" and "-i" in tail:
            mount = tail[tail.index("--mount") + 1]
            volume = next(field.split("=",1)[1] for field in mount.split(",") if field.startswith("source="))
            if payload is not None:
                assert volume not in self.seeded
                self.bootstrap_payloads.append(payload)
                self.seeded.add(volume)
            else:
                if volume not in self.seeded:
                    raise DatabaseInfrastructureError("C1B_DOCKER_OPERATION_FAILED")
            return ""
        if tail[:2] == ["run", "-d"]:
            name = tail[tail.index("--name") + 1]
            network = tail[tail.index("--network") + 1]
            mounts = [tail[i+1] for i, x in enumerate(tail[:-1]) if x == "--mount"]
            normalized = []
            for mount in mounts:
                parts = {a.split("=",1)[0]:a.split("=",1)[1] for a in mount.split(",") if "=" in a}
                normalized.append(dict(Name=parts["source"], Destination=parts["target"], RW="readonly" not in mount))
            self.containers[name] = dict(
                Image=tail[-1], Config=dict(Labels=self._labels(tail)),
                HostConfig=dict(PortBindings={}),
                NetworkSettings=dict(Networks={network: {}}),
                Mounts=normalized, State=dict(Running=True),
            )
            return "container-id"
        if tail[0] == "exec":
            if self.pg_error:
                raise DatabaseInfrastructureError("C1B_DOCKER_OPERATION_FAILED")
            return "1" if "psql" in tail else ""
        raise AssertionError(cmd)

    @staticmethod
    def _labels(arguments):
        labels = {}
        for i, arg in enumerate(arguments[:-1]):
            if arg == "--label":
                k, v = arguments[i+1].split("=", 1)
                labels[k] = v
        return labels


def test_postgres_bootstrap_private_and_idempotent():
    db, row = reserved()
    docker = FakeDocker()
    provision_private_postgres(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    assert row.status == "database_ready" and row.ready_at is None
    assert row.database_image_id == IMAGE
    assert row.network_name in docker.networks and docker.networks[row.network_name]["Internal"]
    assert row.data_volume in docker.volumes
    assert row.bootstrap_secret_volume in docker.volumes
    assert row.container_name in docker.containers
    assert docker.bootstrap_payloads and len(docker.bootstrap_payloads) == 1
    assert len(docker.bootstrap_payloads[0]) >= 20
    # Ensure no password, credentials or published port occurs in any command.
    all_args = " ".join(" ".join(cmd) for cmd, _ in docker.commands)
    assert docker.bootstrap_payloads[0].decode() not in all_args
    assert "-p 5432" not in all_args and "--publish" not in all_args
    assert "POSTGRES_PASSWORD=" not in all_args
    assert "POSTGRES_PASSWORD_FILE=" in all_args
    first_count = len(docker.bootstrap_payloads)
    provision_private_postgres(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    assert len(docker.bootstrap_payloads) == first_count
    assert row.status == "database_ready"
    with pytest.raises(ApplicationDatabaseError, match="not completed"):
        require_ready_application_database(db=db, instance=db.instance,
            manifest={"addons":{"database":{"type":"postgresql","version":"15","storage":"1Gi"}}})


@pytest.mark.parametrize("bad", [
    {"enabled": False}, {"environment": "production"},
    {"accept_unenforced_storage_request": False},
    {"image_id": "postgres:15"},
])
def test_provisioning_gates_are_enforced(bad):
    db, row = reserved()
    docker = FakeDocker()
    with pytest.raises(DatabaseInfrastructureError):
        provision_private_postgres(db=db, instance_id=db.instance.id, settings=settings(**bad), call=docker)
    assert docker.commands == [] and row.status == "reserved"


def test_foreign_existing_resources_are_never_overwritten():
    db, row = reserved()
    docker = FakeDocker()
    docker.networks[row.network_name] = dict(Internal=True, Driver="bridge", Labels={"augmis.managed": "true"})
    with pytest.raises(DatabaseInfrastructureError, match="C1B_FOREIGN_DOCKER_RESOURCE"):
        provision_private_postgres(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    assert row.status == "failed" and row.error_code == "C1B_FOREIGN_DOCKER_RESOURCE"
    assert not any("rm" in cmd for cmd, _ in docker.commands)


def test_existing_secret_volume_does_not_get_replaced():
    db, row = reserved()
    docker = FakeDocker()
    docker.volumes[row.bootstrap_secret_volume] = dict(
        Driver="local", Labels={"augmis.managed":"true", "augmis.database_instance_id":str(row.instance_id)})
    with pytest.raises(DatabaseInfrastructureError):
        provision_private_postgres(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    assert row.status == "failed"
    assert not docker.bootstrap_payloads


def test_provisioning_in_progress_is_rejected():
    db, row = reserved()
    row.status = "provisioning"
    docker = FakeDocker()
    with pytest.raises(DatabaseInfrastructureError, match="C1B_PROVISIONING_ALREADY_IN_PROGRESS"):
        provision_private_postgres(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    assert not docker.commands


def test_tenant_identity_tampering_denied():
    db, row = reserved()
    row.tenant_id = uuid.uuid4()
    docker = FakeDocker()
    with pytest.raises(DatabaseInfrastructureError, match="C1B_RESERVATION_REQUIRED"):
        provision_private_postgres(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    assert not docker.commands


def test_no_existing_reservation_means_no_provisioning():
    db = FakeSession()
    docker = FakeDocker()
    with pytest.raises(DatabaseInfrastructureError, match="C1B_RESERVATION_REQUIRED"):
        provision_private_postgres(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    assert not docker.commands


def test_ready_state_never_autogranted_by_infrastructure():
    db, row = reserved()
    docker = FakeDocker()
    provision_private_postgres(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    assert row.ready_at is None and row.migration_revision is None
    assert row.status != "ready"
