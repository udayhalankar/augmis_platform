"""Tests for explicit stop gate persistence and old gateway ticket invalidation epoch."""
import uuid
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from services.api.app.models.iam import User  # register IAM table in SQLAlchemy metadata
from services.api.app.models.platform import TenantApplicationRuntimeControl
from services.api.app.services.tenant_application_runtime_control import (
    get_runtime_launch_epoch, get_runtime_desired_state,
    require_runtime_launch_allowed, set_runtime_desired_state,
)


def test_persistent_stop_and_admin_start():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    TenantApplicationRuntimeControl.__table__.create(engine)
    tenant, application, admin = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with Session(engine) as db:
        assert get_runtime_desired_state(db, tenant, application) == "running"
        require_runtime_launch_allowed(db, tenant, application)
        assert get_runtime_launch_epoch(db, tenant, application) == 0
        set_runtime_desired_state(db, tenant, application, "stopped", admin)
        db.commit()
    with Session(engine) as db:
        assert get_runtime_desired_state(db, tenant, application) == "stopped"
        with pytest.raises(HTTPException) as captured:
            require_runtime_launch_allowed(db, tenant, application)
        assert captured.value.status_code == 409
        assert captured.value.detail["code"] == "APPLICATION_STOPPED"
        assert get_runtime_launch_epoch(db, tenant, application) == 1
        set_runtime_desired_state(db, tenant, application, "running", admin)
        db.commit()
    with Session(engine) as db:
        require_runtime_launch_allowed(db, tenant, application)
        assert get_runtime_launch_epoch(db, tenant, application) == 1
        set_runtime_desired_state(db, tenant, application, "stopped", admin)
        db.commit()
        assert get_runtime_launch_epoch(db, tenant, application) == 2
    engine.dispose()


def test_routes_and_catalog_enforce_gate():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    instances = (root / "services/api/app/routes/instances.py").read_text()
    subs = (root / "services/api/app/routes/subscriptions.py").read_text()
    catalog = (root / "apps/web/src/app/tenant-applications/page.tsx").read_text()
    assert instances.count("require_runtime_launch_allowed(") >= 5
    assert '"launch_epoch"' in instances
    assert '"instance_id"' in instances
    assert "set_runtime_desired_state(db, instance.tenant_id, instance.application_id," in instances
    assert '"runtimeState": (' in subs
    assert 'item.runtimeState === "stopped"' in catalog
    assert 'Contact your administrator to start the application.' in catalog
