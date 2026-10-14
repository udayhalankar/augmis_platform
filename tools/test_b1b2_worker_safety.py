"""Tests actual worker function behavior, with all external systems mocked."""
import ast
import sys
import types
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi import HTTPException

class RuntimeUpgradeJob: pass
class ApplicationInstance: pass


def load_executor(monkeypatch, *, effect=None, eligibility=True):
    source=Path('services/api/app/services/runtime_automation_service.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    fn=next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'execute_one')
    module=ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    fake_executor=types.ModuleType('services.api.app.services.runtime_upgrade_executor')
    upgrade=Mock(side_effect=effect) if effect else Mock(return_value={'status':'running'})
    fake_executor.perform_instance_upgrade=upgrade
    monkeypatch.setitem(sys.modules,'services.api.app.services.runtime_upgrade_executor',fake_executor)
    ns={'Session':object, 'uuid':uuid, 'RuntimeUpgradeJob':RuntimeUpgradeJob,
        'ApplicationInstance':ApplicationInstance, 'record_audit_event':Mock(),
        'utcnow':lambda: 'fake_date', 'eligible_upgrade':lambda db, inst: None}
    exec(compile(module,'runtime_automation_service.py','exec'),ns)
    return ns,upgrade


def make_case():
    tid,sid,iid,from_id,to_id=(uuid.uuid4() for _ in range(5))
    job=SimpleNamespace(id=uuid.uuid4(),tenant_id=tid,instance_id=iid,
        subscription_id=sid,source_version_id=from_id,target_version_id=to_id,
        status='running',last_error_code=None,completed_at=None,lease_until='original')
    instance=SimpleNamespace(id=iid,tenant_id=tid,status='running',active_version_id=from_id)
    db=Mock()
    db.get.side_effect=lambda cls,object_id: job if cls is RuntimeUpgradeJob else instance if cls is ApplicationInstance else None
    choice=(SimpleNamespace(id=sid),SimpleNamespace(id=to_id))
    return job,instance,db,choice


@pytest.mark.parametrize('effect,status,result',[
    (HTTPException(status_code=422,detail='candidate failed'), 'failed','FAILED'),
    (HTTPException(status_code=503,detail='unknown result'), 'needs_reconciliation','NEEDS_RECONCILIATION'),
    (RuntimeError('unconfirmed Docker promotion'), 'needs_reconciliation','NEEDS_RECONCILIATION'),
])
def test_unknown_docker_outcome_is_not_safe_failure(monkeypatch,effect,status,result):
    job,_,db,choice=make_case()
    ns,_=load_executor(monkeypatch,effect=effect)
    ns['eligible_upgrade']=lambda db,inst: choice
    assert ns['execute_one'](db,job.id)==result
    assert job.status==status
    assert db.commit.called
    assert job.last_error_code==('HTTP_422' if status=='failed' else 'UNKNOWN_DOCKER_OUTCOME_REVIEW_REQUIRED')
    if status=='needs_reconciliation':
        assert job.lease_until=='original'
        assert job.completed_at is None


def test_consent_or_target_change_defers_without_container_calls(monkeypatch):
    job,_,db,choice=make_case()
    ns,upgrade=load_executor(monkeypatch)
    assert ns['execute_one'](db,job.id)=='DEFERRED'
    assert job.status=='deferred'
    upgrade.assert_not_called()


def test_upgrade_is_succeeded_only_after_executor_return(monkeypatch):
    job,_,db,choice=make_case()
    ns,upgrade=load_executor(monkeypatch)
    ns['eligible_upgrade']=lambda db,inst:choice
    assert ns['execute_one'](db,job.id)=='SUCCEEDED'
    assert job.status=='succeeded'
    upgrade.assert_called_once()


def test_quota_update_uses_tenant_lock_with_deploy_reservation():
    source=Path('services/api/app/routes/runtime_control.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    fn=next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name=='put_quota')
    function_text=ast.get_source_segment(source, fn)
    assert 'with_for_update()' in function_text
    assert 'select(Tenant)' in function_text
    assert 'platform.settings.manage' in function_text
