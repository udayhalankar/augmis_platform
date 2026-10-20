"""Offline lifecycle tracking tests: no Docker or database connectivity."""
from __future__ import annotations
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import MagicMock
import uuid
import pytest
from services.api.app.services import c1d3_operation_tracking as track
from services.api.app.services.deployment_reliability import (
    quarantine_expired, ReliabilityError,
)
ROOT = Path(__file__).resolve().parents[1]


def sample():
    dep=Obj(id=uuid.uuid4(),status='deploying',health_status='starting',
            container_id=None, container_name=None, runtime_url=None)
    ins=Obj(tenant_id=uuid.uuid4(),id=uuid.uuid4())
    journal=Obj(deployment_id=dep.id, tenant_id=ins.tenant_id, instance_id=ins.id,
                stage='reserved', state='queued', owner=None, lease_until=None,
                attempt=0, failure_code=None)
    db=MagicMock(); db.scalar.return_value=journal
    return db,ins,dep,journal


def test_reservation_is_within_existing_transaction(monkeypatch):
    db,ins,dep,_=sample();db.scalar.return_value=None
    track.journal_reserved(db,instance=ins,deployment=dep)
    db.flush.assert_called_once()
    db.commit.assert_not_called()
    db.add.assert_called_once()
    row=db.add.call_args.args[0]
    assert row.tenant_id==ins.tenant_id and row.deployment_id==dep.id


def test_journal_start_durable_before_launch():
    db,ins,dep,row=sample()
    owner=track.journal_launch_started(db,deployment=dep)
    assert owner.startswith('sync-')
    assert row.state=='running' and row.stage=='runtime_starting'
    assert row.attempt==1 and row.owner==owner
    assert row.lease_until>datetime.now(timezone.utc)
    db.commit.assert_called_once()


def test_runtime_handoff_and_promotion_atomic_with_final_metadata_commit():
    db,ins,dep,row=sample()
    owner=track.journal_launch_started(db,deployment=dep)
    result={'container_id':'a'*64,'container_name':'augmis-x',
            'runtime_url':'http://127.0.0.1:1234',
            'health_url':'http://127.0.0.1:1234/health'}
    track.journal_runtime_ready(db,deployment=dep,owner=owner,result=result)
    assert row.stage=='gateway_verifying' and row.state=='running'
    assert dep.container_id=='a'*64 and dep.runtime_url==result['runtime_url']
    assert db.commit.call_count==2
    dep.status='running';dep.health_status='healthy'
    track.journal_promoted(db,deployment=dep,owner=owner)
    assert row.stage=='active' and row.state=='active'
    # Final transaction is owned by caller, so metadata and journal commit together.
    assert db.commit.call_count==2


def test_no_early_or_unhealthy_promotion():
    db,ins,dep,row=sample()
    owner=track.journal_launch_started(db,deployment=dep)
    with pytest.raises(ValueError,match='C1D3_PROMOTION_NOT_HEALTHY'):
        track.journal_promoted(db,deployment=dep,owner=owner)
    dep.status='running';dep.health_status='healthy'
    with pytest.raises(ReliabilityError,match='GATEWAY_VERIFICATION_REQUIRED'):
        track.journal_promoted(db,deployment=dep,owner=owner)
    assert row.state=='running'


def test_missing_or_unhealthy_result_rejected_before_handoff():
    db,ins,dep,row=sample();owner=track.journal_launch_started(db,deployment=dep)
    with pytest.raises(ValueError,match='C1D3_RUNTIME_RESULT_INCOMPLETE'):
        track.journal_runtime_ready(db,deployment=dep,owner=owner,
                                    result={'container_name':'x'})
    assert row.stage=='runtime_starting'
    assert db.commit.call_count==1


def test_tenant_owner_and_lease_enforced():
    db,ins,dep,row=sample();owner=track.journal_launch_started(db,deployment=dep)
    with pytest.raises(ReliabilityError,match='STAGE_NOT_OWNED'):
        track.journal_runtime_ready(db,deployment=dep,owner='wrong',
             result={'container_id':'a','container_name':'b','runtime_url':'c','health_url':'d'})
    row.lease_until=datetime.now(timezone.utc)-timedelta(seconds=1)
    with pytest.raises(ReliabilityError,match='STAGE_LEASE_EXPIRED'):
        track.journal_runtime_ready(db,deployment=dep,owner=owner,
             result={'container_id':'a','container_name':'b','runtime_url':'c','health_url':'d'})


def test_failed_launch_records_safe_code_without_replay():
    db,ins,dep,row=sample();owner=track.journal_launch_started(db,deployment=dep)
    track.journal_failed(db,deployment=dep,owner=owner,code='C1D3_RESTART_LAUNCH_FAILED')
    assert row.state=='failed' and row.failure_code=='C1D3_RESTART_LAUNCH_FAILED'
    assert row.attempt==1
    assert db.commit.call_count==1 # caller persists same transaction as failed deployment


def test_expired_quarantine_can_be_tenant_scoped():
    db=MagicMock();db.scalars.return_value=[]
    tenant=uuid.uuid4()
    assert quarantine_expired(db,tenant_id=tenant)==0
    stmt=db.scalars.call_args.args[0]
    compiled=str(stmt)
    assert 'deployment_operation_journals.tenant_id' in compiled
    assert 'deployment_operation_journals.state' in compiled


def test_recovery_cli_blocks_unscoped_metadata_changes():
    source=(ROOT/'tools/c1d3_recovery_audit.py').read_text()
    assert "if args.tenant_id is None:" in source
    assert "tenant_id=args.tenant_id" in source


def _names(path, function):
    root=ast.parse((ROOT/path).read_text())
    f=next(n for n in ast.walk(root) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==function)
    found=[]
    for call in (x for x in ast.walk(f) if isinstance(x,ast.Call)):
        if isinstance(call.func,ast.Name):found.append((call.lineno,call.func.id))
    return sorted(found)


@pytest.mark.parametrize('path,func',[
    ('services/api/app/routes/instances.py','deploy_application'),
    ('services/api/app/routes/instances.py','restart_application_instance'),
    ('services/api/app/routes/instances.py','rollback_application_instance'),
    ('services/api/app/services/runtime_upgrade_executor.py','perform_instance_upgrade'),
])
def test_all_four_lifecycles_journaled(path,func):
    calls=_names(path,func)
    names=[n for _,n in calls]
    for name in ('journal_reserved','journal_launch_started','start_scoped_container',
                 'journal_runtime_ready','journal_promoted','journal_failed'):
        expected = 2 if name == 'journal_failed' and func in ('rollback_application_instance','perform_instance_upgrade') else 1
        assert names.count(name)==expected,(func,name,names)
    positions={name:next(line for line,n in calls if n==name) for name in names}
    assert positions['journal_reserved']<positions['journal_launch_started']<positions['start_scoped_container']
    assert positions['start_scoped_container']<positions['journal_runtime_ready']<positions['journal_promoted']
    assert positions['start_scoped_container']<positions['journal_failed']


def test_operation_tracker_never_runs_docker_or_deletes_resources():
    source=(ROOT/'services/api/app/services/c1d3_operation_tracking.py').read_text()
    for banned in ('subprocess.', 'docker run', 'docker rm', 'delete(', 'drop_database', 'stop_container('):
        assert banned not in source
