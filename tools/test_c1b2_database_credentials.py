"""C1-B2 offline tests: no PostgreSQL, Docker daemon or network activity."""
import re
from datetime import datetime, timedelta, timezone

import pytest

from tools.test_c1b1_private_postgres import FakeDocker, reserved, settings, IMAGE
from services.api.app.services.application_database_docker import (
    DatabaseInfrastructureError, provision_private_postgres,
)
from services.api.app.services.application_database_credentials import (
    provision_restricted_database_login, runtime_role,
)


class CredentialDocker(FakeDocker):
    def __init__(self):
        super().__init__()
        self.runtime_password = None
        self.roles = {}

    def __call__(self, cmd, payload=None):
        tail = cmd[1:]
        if tail[:2] == ["exec", "-i"]:
            self.commands.append((list(cmd), payload))
            assert b"PASSWORD" in payload or b"SELECT" in payload or b"GRANT" in payload
            sql = payload.decode()
            role_match = re.search(r"augmis_rw_[a-f0-9]{32}", sql)
            role = role_match.group() if role_match else None
            if "CREATE ROLE " in sql:
                password = re.search(r"PASSWORD '([A-Za-z0-9_-]+)'", sql).group(1)
                assert password not in " ".join(cmd)
                assert role not in self.roles
                self.roles[role] = password
                return ""
            if "NOT rolbypassrls" in sql:
                return "1" if role in self.roles else "0"
            if "GRANT CONNECT" in sql:
                return ""
            if "SELECT CASE WHEN EXISTS" in sql:
                return "1" if role in self.roles else "0"
            raise AssertionError(sql)
        if tail and tail[0] == "run" and "--mount" in tail:
            mount = tail[tail.index("--mount") + 1]
            if "target=/run/secrets" in mount:
                self.commands.append((list(cmd), payload))
                if self.runtime_password is None:
                    raise DatabaseInfrastructureError("C1B_DOCKER_OPERATION_FAILED")
                if "PGUSER=" in " ".join(tail):
                    role = next(x[7:] for x in tail if x.startswith("PGUSER="))
                    if self.roles.get(role) != self.runtime_password:
                        raise DatabaseInfrastructureError("C1B_DOCKER_OPERATION_FAILED")
                    return role
                return self.runtime_password
            if payload is not None and "target=/bootstrap" in mount and b"/bootstrap/db_password" in " ".join(tail).encode():
                self.runtime_password = payload.decode()
        return super().__call__(cmd, payload)


def init():
    db, row = reserved()
    docker = CredentialDocker()
    provision_private_postgres(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    return db, row, docker


def test_new_role_and_separate_secret_volume():
    db, row, docker = init()
    assert row.status == "database_ready"
    provision_restricted_database_login(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    assert row.status == "credentials_ready"
    assert row.ready_at is None
    assert row.runtime_secret_volume in docker.volumes
    assert row.runtime_secret_volume != row.bootstrap_secret_volume
    assert docker.roles[runtime_role(row.instance_id)] == docker.runtime_password
    assert len(docker.runtime_password) >= 40
    assert "postgres_password" not in " ".join(" ".join(c) for c, _ in docker.commands if "target=/run/secrets" in " ".join(c))
    assert not any(docker.runtime_password in " ".join(c) for c, _ in docker.commands)
    assert not any(docker.runtime_password == repr(x) for x in [row.error_code, row.status])


def test_idempotent_credential_retry_without_rotation():
    db, row, docker = init()
    provision_restricted_database_login(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    first = docker.runtime_password
    provision_restricted_database_login(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    assert row.status == "credentials_ready"
    assert docker.runtime_password == first
    assert len(docker.roles) == 1


def test_failed_password_or_login_never_marks_ready():
    db, row, docker = init()
    docker.roles[runtime_role(row.instance_id)] = "different-password"
    with pytest.raises(DatabaseInfrastructureError):
        provision_restricted_database_login(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    assert row.status == "failed"
    assert row.ready_at is None
    assert row.error_code


def test_no_credentials_before_infrastructure():
    db, row = reserved()
    docker = CredentialDocker()
    with pytest.raises(DatabaseInfrastructureError, match="C1B2_DATABASE_INFRASTRUCTURE_NOT_READY"):
        provision_restricted_database_login(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    assert not docker.commands


def test_tampering_prevents_docker_execution():
    db, row, docker = init()
    initial = len(docker.commands)
    row.runtime_secret_volume = "foreign-volume"
    with pytest.raises(DatabaseInfrastructureError, match="C1B2_IDENTITY_DRIFT"):
        provision_restricted_database_login(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    assert len(docker.commands) == initial


def test_stale_recovery_requires_explicit_opt_in():
    db, row = reserved()
    docker = CredentialDocker()
    row.status = "provisioning"
    row.updated_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    with pytest.raises(DatabaseInfrastructureError, match="C1B_PROVISIONING_ALREADY_IN_PROGRESS"):
        provision_private_postgres(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    assert not docker.commands
    provision_private_postgres(db=db, instance_id=db.instance.id, settings=settings(), call=docker, recover_stale=True)
    assert row.status == "database_ready"


def test_ready_state_not_revalidated_as_infrastructure_only():
    db, row = reserved()
    docker = CredentialDocker()
    row.status = "ready"
    with pytest.raises(DatabaseInfrastructureError, match="C1B_READY_REQUIRES_SECURITY_PREFLIGHT"):
        provision_private_postgres(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    assert row.status == "ready"
    assert not docker.commands


def test_migration_has_matching_parent_and_non_destructive_downgrade():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    text = (root / "services/api/alembic/versions/c1b2_20261017_app_database_runtime_secret.py").read_text()
    assert 'down_revision = "c1a_appdb_20261016"' in text
    assert "instance_id::text" in text
    assert "raise RuntimeError" in text


def test_interrupted_credential_setup_requires_explicit_stale_recovery():
    db, row, docker = init()
    row.status = "credential_setup"
    row.updated_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    with pytest.raises(DatabaseInfrastructureError, match="C1B2_SETUP_ALREADY_IN_PROGRESS"):
        provision_restricted_database_login(db=db, instance_id=db.instance.id,
                                             settings=settings(), call=docker)
    provision_restricted_database_login(db=db, instance_id=db.instance.id,
                                         settings=settings(), call=docker, recover_stale=True)
    assert row.status == "credentials_ready" and row.ready_at is None


def test_recent_credential_setup_cannot_be_stolen():
    db, row, docker = init()
    row.status = "credential_setup"
    row.updated_at = datetime.now(timezone.utc)
    before = len(docker.commands)
    with pytest.raises(DatabaseInfrastructureError, match="C1B2_SETUP_ALREADY_IN_PROGRESS"):
        provision_restricted_database_login(db=db, instance_id=db.instance.id,
                                             settings=settings(), call=docker, recover_stale=True)
    assert len(docker.commands) == before
