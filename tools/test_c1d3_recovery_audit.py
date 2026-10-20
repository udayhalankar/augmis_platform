"""Offline negative/positive C1-D3 reconciliation tests. No Docker needed."""
import uuid
from types import SimpleNamespace as NS
from unittest.mock import patch
import pytest

from services.api.app.services.c1d3_recovery_audit import (
    DockerState, DockerInspectionError, classify_deployment, inspect_exact_container, inventory,
)


def fixture():
    iid,tid,aid,did = [uuid.uuid4() for i in range(4)]
    instance = NS(id=iid,tenant_id=tid,application_id=aid)
    deployment = NS(id=did,instance_id=iid,status='running',container_name='augmis-test123')
    journal = NS(deployment_id=did,instance_id=iid,tenant_id=tid,state='active',stage='active',lease_until=None)
    labels = {'augmis.managed':'true','augmis.instance_id':str(iid),
              'augmis.tenant_id':str(tid),'augmis.application_id':str(aid)}
    return instance,deployment,journal,labels


def classify(*, status='running', container_state='running', journal_state='active', wrong_label=False):
    i,d,j,labels=fixture()
    d.status=status;j.state=journal_state
    if wrong_label:labels['augmis.tenant_id']=str(uuid.uuid4())
    return classify_deployment(instance=i,deployment=d,journal=j,state=DockerState(container_state,labels))


def test_happy_runtime_is_not_claimed_gateway_healthy():
    row=classify()
    assert row['code']=='RUNTIME_PRESENT'
    assert row['nextAction']=='NO_ACTION'

def test_expired_running_journal_demands_signed_verification():
    row=classify(journal_state='needs_reconciliation')
    assert row['code']=='RUNNING_NEEDS_VERIFICATION'
    assert row['nextAction']=='VERIFY_HEALTH_AND_GATEWAY'

def test_crashed_start_not_auto_promoted():
    row=classify(status='deploying')
    assert row['code']=='RUNNING_WITH_INCOMPLETE_METADATA'
    assert row['nextAction']=='OPERATOR_RECONCILE'

def test_failed_deployment_with_running_container_never_deleted():
    row=classify(status='failed')
    assert row['code']=='RUNNING_WITH_INCOMPLETE_METADATA'

def test_not_running_current_instance_is_not_automatically_restarted():
    row=classify(container_state='exited')
    assert row['code']=='RUNTIME_NOT_RUNNING'
    assert row['nextAction']=='OPERATOR_RECONCILE'

def test_missing_current_container_needs_reconciliation():
    i,d,j,_=fixture()
    row=classify_deployment(instance=i,deployment=d,journal=j,state=DockerState('missing',{}))
    assert row['code']=='CONTAINER_MISSING'

def test_missing_historical_container_normal():
    i,d,j,_=fixture(); d.status='stopped'
    row=classify_deployment(instance=i,deployment=d,journal=j,state=DockerState('missing',{}))
    assert row['code']=='HISTORICAL_CONTAINER_MISSING'

def test_label_mismatch_is_security_stop():
    row=classify(wrong_label=True)
    assert row['code']=='OWNERSHIP_LABEL_MISMATCH'
    assert row['nextAction']=='STOP_SECURITY_REVIEW'

def test_wrong_journal_tenant_quarantined():
    i,d,j,labels=fixture(); j.tenant_id=uuid.uuid4()
    row=classify_deployment(instance=i,deployment=d,journal=j,state=DockerState('running',labels))
    assert row['code']=='OWNERSHIP_CONFLICT'

def test_wrong_deployment_instance_raises():
    i,d,j,labels=fixture(); d.instance_id=uuid.uuid4()
    with pytest.raises(ValueError,match='C1D3_DEPLOYMENT_INSTANCE_MISMATCH'):
        classify_deployment(instance=i,deployment=d,journal=j,state=DockerState('running',labels))

def test_missing_journal_reported_as_legacy():
    i,d,j,labels=fixture()
    row=classify_deployment(instance=i,deployment=d,journal=None,state=DockerState('running',labels))
    assert row['journalState']=='not_journaled'

def test_inspect_failure_is_coded_not_exposed():
    i,d,j,_=fixture()
    row=classify_deployment(instance=i,deployment=d,journal=j,inspect_error='C1D3_DOCKER_UNAVAILABLE')
    assert row['nextAction']=='RECHECK_DOCKER_HOST'
    assert 'password' not in str(row).lower()

@pytest.mark.parametrize('name', ['bad name', '../../bad', '', 'x'*201, 'shell;inject'])
def test_no_unsafe_docker_names(name):
    with pytest.raises(DockerInspectionError,match='C1D3_CONTAINER_NAME_INVALID'):
        inspect_exact_container(name)

def test_only_selected_container_is_passed_without_shell():
    name='augmis-abc-test'
    obj=[{'Name':'/'+name,'Id':'a'*64,'State':{'Status':'running'},'Config':{'Labels':{'augmis.managed':'true'}}}]
    with patch('services.api.app.services.c1d3_recovery_audit.subprocess.run') as run:
        run.return_value=NS(returncode=0,stdout=__import__('json').dumps(obj),stderr='')
        result=inspect_exact_container(name)
        assert result.state=='running'
        args=run.call_args.args[0]
        assert args == ['docker','container','inspect',name]
        assert run.call_args.kwargs['capture_output'] is True

def test_mismatched_inspect_name_rejected():
    obj=[{'Name':'/other','State':{'Status':'running'},'Config':{'Labels':{}}}]
    with patch('services.api.app.services.c1d3_recovery_audit.subprocess.run') as run:
        run.return_value=NS(returncode=0,stdout=__import__('json').dumps(obj),stderr='')
        with pytest.raises(DockerInspectionError,match='C1D3_INSPECT_INVALID'):
            inspect_exact_container('expected')

def test_docker_timeout_fail_closed():
    import subprocess
    with patch('services.api.app.services.c1d3_recovery_audit.subprocess.run',side_effect=subprocess.TimeoutExpired(['docker'],12)):
        with pytest.raises(DockerInspectionError,match='C1D3_DOCKER_UNAVAILABLE'):
            inspect_exact_container('expected')

def test_docker_absent_requires_explicit_daemon_check():
    with patch('services.api.app.services.c1d3_recovery_audit.subprocess.run') as run:
        run.side_effect=[NS(returncode=1,stderr='No such object: expected',stdout=''),
                         NS(returncode=1,stderr='daemon unreachable',stdout='')]
        with pytest.raises(DockerInspectionError,match='C1D3_DOCKER_UNAVAILABLE'):
            inspect_exact_container('expected')

def test_no_secrets_from_docker_inspect_payload():
    i,d,j,labels=fixture()
    labels['SECRET_PASSWORD']='never-print-me'
    r=classify_deployment(instance=i,deployment=d,journal=j,state=DockerState('running',labels))
    assert 'never-print-me' not in str(r)

def test_invalid_scan_bounds_fail_before_database():
    with pytest.raises(ValueError,match='C1D3_LIMIT_INVALID'):
        inventory(object(),limit=501)


def test_expired_lease_is_visible_without_metadata_mutation():
    from datetime import datetime, timedelta, timezone
    i,d,j,labels=fixture()
    j.state='running';j.lease_until=datetime.now(timezone.utc)-timedelta(minutes=10)
    row=classify_deployment(instance=i,deployment=d,journal=j,state=DockerState('running',labels))
    assert row['code']=='LEASE_EXPIRED_RECONCILE'
    assert row['nextAction']=='OPERATOR_RECONCILE'
