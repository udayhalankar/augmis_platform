"""C1-A contract tests: pure checks and fake-session metadata reservation.

Run from AUGMIS repository root:
    python -m pytest -q tools/test_c1a_application_database_reservation.py
No network, Docker, actual database or application startup required.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql

from services.api.app.models.platform import ApplicationInstance
from services.api.app.models.runtime_control import ApplicationDatabaseResource
from services.api.app.services.application_database_provisioning import (
    ApplicationDatabaseError,
    database_resource_plan,
    read_database_requirement,
    reserve_application_database,
    require_ready_application_database,
)


def _manifest(storage="1Gi"):
    return {"addons": {"database": {"type": "postgresql", "version": "15", "storage": storage}}}


class FakeSession:
    """No DB or network: deterministic test double for model-row reservation."""
    def __init__(self, instance):
        self.instance = instance
        self.rows = []
        self.flush_count = 0

    def scalar(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is ApplicationInstance:
            return self.instance
        if entity is ApplicationDatabaseResource:
            return self.rows[0] if self.rows else None
        raise AssertionError(f"unexpected query: {entity}")

    def add(self, value):
        assert isinstance(value, ApplicationDatabaseResource)
        self.rows.append(value)

    def flush(self):
        self.flush_count += 1


def _test_instance():
    return ApplicationInstance(id=uuid.uuid4(), tenant_id=uuid.uuid4())


def test_aaps_declared_database_is_accepted():
    req = read_database_requirement(_manifest())
    assert req.engine == "postgresql" and req.version == "15" and req.storage == "1Gi"
    assert read_database_requirement({}) is None


@pytest.mark.parametrize("bad", [
    {"addons": {"database": {"type": "mysql", "version": "8"}}},
    {"addons": {"database": {"type": "postgresql", "version": "16"}}},
    _manifest("0Gi"), _manifest("51Gi"), _manifest("10GB"),
])
def test_unsupported_database_contract_fails_closed(bad):
    with pytest.raises(ApplicationDatabaseError):
        read_database_requirement(bad)


def test_instance_names_are_stable_and_unique():
    instance = _test_instance()
    req = read_database_requirement(_manifest())
    a = database_resource_plan(tenant_id=instance.tenant_id, instance_id=instance.id, requirement=req)
    b = database_resource_plan(tenant_id=instance.tenant_id, instance_id=instance.id, requirement=req)
    assert a == b
    assert str(instance.id.hex) in a.data_volume
    assert a.network_name != database_resource_plan(
        tenant_id=instance.tenant_id, instance_id=uuid.uuid4(), requirement=req
    ).network_name
    assert len(a.network_name) < 64


def test_reservation_is_idempotent_and_does_not_call_docker():
    instance = _test_instance()
    db = FakeSession(instance)
    first = reserve_application_database(db=db, instance_id=instance.id, manifest=_manifest())
    second = reserve_application_database(db=db, instance_id=instance.id, manifest=_manifest())
    assert first is second
    assert len(db.rows) == 1 and db.flush_count == 1
    assert first.status == "reserved"
    assert first.tenant_id == instance.tenant_id


def test_reject_reservation_drift_and_implicit_database_drop():
    instance = _test_instance()
    db = FakeSession(instance)
    reserve_application_database(db=db, instance_id=instance.id, manifest=_manifest())
    with pytest.raises(ApplicationDatabaseError, match="conflicts"):
        reserve_application_database(db=db, instance_id=instance.id, manifest=_manifest("2Gi"))
    with pytest.raises(ApplicationDatabaseError, match="cannot drop"):
        reserve_application_database(db=db, instance_id=instance.id, manifest={})


def test_wrong_tenant_mapping_is_rejected():
    instance = _test_instance()
    db = FakeSession(instance)
    row = reserve_application_database(db=db, instance_id=instance.id, manifest=_manifest())
    row.tenant_id = uuid.uuid4()
    with pytest.raises(ApplicationDatabaseError, match="conflicts"):
        reserve_application_database(db=db, instance_id=instance.id, manifest=_manifest())


def test_readiness_is_required_before_container_launch():
    instance = _test_instance()
    db = FakeSession(instance)
    row = reserve_application_database(db=db, instance_id=instance.id, manifest=_manifest())
    with pytest.raises(ApplicationDatabaseError, match="not completed"):
        require_ready_application_database(db=db, instance=instance, manifest=_manifest())
    row.status = "ready"
    assert require_ready_application_database(db=db, instance=instance, manifest=_manifest()) is row


def test_foreign_keys_retain_database_resource_metadata():
    ddl = str(CreateTable(ApplicationDatabaseResource.__table__).compile(dialect=postgresql.dialect()))
    assert "ON DELETE RESTRICT" in ddl
    assert "uq_application_database_instance" in ddl
    assert "application_database_resources" in ddl
    assert "PASSWORD" not in ddl
