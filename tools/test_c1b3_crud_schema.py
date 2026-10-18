"""Offline only: does not contact PostgreSQL/Docker, intentionally no live writes."""
from types import SimpleNamespace
from pathlib import Path
import uuid
import pytest

from tools.test_c1b2_database_credentials import CredentialDocker
from tools.test_c1b1_private_postgres import settings
from services.api.app.models.platform import ApplicationVersion
from services.api.app.services.application_database_docker import DatabaseInfrastructureError
from services.api.app.services.application_database_credentials import provision_restricted_database_login
from services.api.app.services.application_database_schema import (
    install_reference_schema, reference_schema_sql, SCHEMA_REVISION,
)


class SchemaDocker(CredentialDocker):
    def __init__(self):
        super().__init__()
        self.applied = 0
        self.verify_calls = 0

    def __call__(self, cmd, payload=None):
        if cmd[1:3] == ['exec', '-i'] and payload:
            sql = payload.decode()
            if 'CREATE TABLE IF NOT EXISTS public.sample_records' in sql:
                self.commands.append((cmd, payload))
                self.applied += 1
                return ''
            if 'FROM pg_policies' in sql:
                self.commands.append((cmd, payload))
                self.verify_calls += 1
                return '1'
        return super().__call__(cmd, payload)


def prepare(monkeypatch):
    db, row = __import__('tools.test_c1b1_private_postgres', fromlist=['reserved']).reserved()
    # Simulates an existing, already-provisioned C1-B2 state.
    docker = SchemaDocker()
    from services.api.app.services.application_database_docker import provision_private_postgres
    provision_private_postgres(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    provision_restricted_database_login(db=db, instance_id=db.instance.id, settings=settings(), call=docker)
    db.instance.application_id = uuid.uuid4()
    db.instance.active_version_id = uuid.uuid4()
    db.version = SimpleNamespace(manifest={
        'metadata': {'id': 'augmis-crud-reference'},
        'addons': {'database': {'type': 'postgresql', 'version': '15'}}})
    db.get = lambda model, uid: db.version if model is ApplicationVersion else None
    monkeypatch.setenv('AUGMIS_C1B_DEV_SCHEMA_ENABLED', '1')
    monkeypatch.setenv('AUGMIS_C1B_CRUD_APPLICATION_ID', str(db.instance.application_id))
    return db, row, docker


def test_schema_creates_crud_rls_least_privilege(monkeypatch):
    db,row,docker=prepare(monkeypatch)
    result=install_reference_schema(db=db,instance_id=db.instance.id,settings=settings(),call=docker)
    assert result is row and row.status == 'ready'
    assert row.migration_revision == SCHEMA_REVISION and row.ready_at is not None
    assert docker.applied == 1 and docker.verify_calls >= 1
    sql=reference_schema_sql(db.instance)
    for phrase in ('FORCE ROW LEVEL SECURITY', 'c1b3_insert', 'c1b3_update',
                   'WITH CHECK', 'REVOKE ALL', 'GRANT UPDATE (', 'CREATE TABLE IF NOT EXISTS'):
        assert phrase in sql
    assert 'GRANT DELETE' not in sql
    assert 'GRANT CREATE' not in sql
    assert 'RETURNING id' not in sql
    # Approval data is trusted model identity, never user JSON.
    assert str(db.instance.id.hex) in sql


def test_ready_retry_is_only_read_only_verification(monkeypatch):
    db,row,docker=prepare(monkeypatch)
    install_reference_schema(db=db,instance_id=db.instance.id,settings=settings(),call=docker)
    applied=docker.applied
    install_reference_schema(db=db,instance_id=db.instance.id,settings=settings(),call=docker)
    assert docker.applied == applied and docker.verify_calls >= 2


def test_wrong_app_denied_before_ddl(monkeypatch):
    db,row,docker=prepare(monkeypatch)
    monkeypatch.setenv('AUGMIS_C1B_CRUD_APPLICATION_ID',str(uuid.uuid4()))
    with pytest.raises(DatabaseInfrastructureError,match='C1B3_APPLICATION_NOT_APPROVED'):
        install_reference_schema(db=db,instance_id=db.instance.id,settings=settings(),call=docker)
    assert docker.applied == 0


def test_prod_or_missing_flag_denied(monkeypatch):
    db,row,docker=prepare(monkeypatch)
    with pytest.raises(DatabaseInfrastructureError):
        install_reference_schema(db=db,instance_id=db.instance.id,
                                 settings=settings(environment='production'),call=docker)
    monkeypatch.delenv('AUGMIS_C1B_DEV_SCHEMA_ENABLED')
    with pytest.raises(DatabaseInfrastructureError,match='C1B3_SCHEMA_INSTALL_DISABLED'):
        install_reference_schema(db=db,instance_id=db.instance.id,settings=settings(),call=docker)
    assert docker.applied == 0


def test_unready_db_denied(monkeypatch):
    db,row,docker=prepare(monkeypatch)
    row.status='reserved'
    with pytest.raises(DatabaseInfrastructureError,match='C1B3_CREDENTIALS_NOT_READY'):
        install_reference_schema(db=db,instance_id=db.instance.id,settings=settings(),call=docker)
    assert docker.applied == 0


def test_staged_app_never_creates_tables_in_runtime():
    root=Path(__file__).resolve().parents[1]
    app_source=(root/'examples/augmis-crud-reference-v1.1.0/app/main.py').read_text()
    assert 'CREATE TABLE' not in app_source
    assert 'set_config' in app_source
    assert 'PGPASSWORD_FILE' in app_source
    assert 'jwt.decode' in app_source
    assert 'bodySha256' in app_source
    html=(root/'examples/augmis-crud-reference-v1.1.0/app/static/index.html').read_text()
    assert "request('/api/" not in html
