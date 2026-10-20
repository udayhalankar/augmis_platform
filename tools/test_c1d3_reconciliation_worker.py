"""C1-D3 bounded worker tests. No Docker, DB, network or app writes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import MagicMock
from pathlib import Path
import uuid
import pytest

from services.api.app.services.c1d3_reconciliation_worker import (
    stale_reason, observe_operation, reconcile_once,
)
from services.api.app.services.c1d3_recovery_audit import DockerState, DockerInspectionError

NOW = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)


def sample(*, status='running', state='queued', seconds_old=7200, stage='reserved'):
    ins = NS(id=uuid.uuid4(), tenant_id=uuid.uuid4(), application_id=uuid.uuid4())
    dep = NS(id=uuid.uuid4(), instance_id=ins.id, container_name='augmis-test',
             container_id=None, status=status)
    journal = NS(id=uuid.uuid4(), deployment_id=dep.id,
        instance_id=ins.id, tenant_id=ins.tenant_id, state=state, stage=stage,
        owner=None, lease_until=None, updated_at=NOW-timedelta(seconds=seconds_old),
        created_at=NOW-timedelta(seconds=seconds_old))
    return journal,dep,ins


def state_for(ins, *, state='running', cid='a'*64):
    return DockerState(state, {'augmis.managed':'true',
         'augmis.instance_id':str(ins.id), 'augmis.tenant_id':str(ins.tenant_id),
         'augmis.application_id':str(ins.application_id)}, cid)


@pytest.mark.parametrize('state', ['active','failed','needs_reconciliation','arbitrary'])
def test_terminal_journals_never_stale(state):
    j,_,_=sample(state=state)
    assert stale_reason(j,now=NOW) is None


def test_recent_queued_never_stale():
    j,_,_=sample(seconds_old=300)
    assert stale_reason(j,now=NOW) is None


def test_abandoned_queued_can_be_flagged_without_replay():
    j,_,_=sample()
    assert stale_reason(j,now=NOW)=='C1D3_QUEUED_ABANDONED'


def test_exact_queued_boundary():
    j,_,_=sample(seconds_old=3600)
    assert stale_reason(j,now=NOW)=='C1D3_QUEUED_ABANDONED'


def test_running_lease_requires_extra_grace():
    j,_,_=sample(state='running')
    j.lease_until=NOW-timedelta(seconds=800)
    assert stale_reason(j,now=NOW) is None
    j.lease_until=NOW-timedelta(seconds=901)
    assert stale_reason(j,now=NOW)=='C1D3_LEASE_EXPIRED'


def test_missing_lease_recent_state_not_quarantined():
    j,_,_=sample(state='running',seconds_old=300)
    assert stale_reason(j,now=NOW) is None


def test_missing_lease_old_state_detected():
    j,_,_=sample(state='running')
    assert stale_reason(j,now=NOW)=='C1D3_LEASE_MISSING'


def test_naive_sql_datetime_normalized_utc():
    j,_,_=sample(state='running')
    j.lease_until=(NOW-timedelta(seconds=3600)).replace(tzinfo=None)
    assert stale_reason(j,now=NOW)=='C1D3_LEASE_EXPIRED'


@pytest.mark.parametrize('grace,queued',[(59,3600),(86401,3600),(900,299),(900,604801)])
def test_invalid_windows_rejected(grace,queued):
    j,_,_=sample()
    with pytest.raises(ValueError,match='WINDOW_INVALID'):
        stale_reason(j,now=NOW,grace_seconds=grace,queued_seconds=queued)


def test_no_stale_on_old_active_stage_even_running():
    j,d,i=sample(state='running',stage='active')
    result=observe_operation(instance=i,deployment=d,journal=j,docker_state=state_for(i))
    assert result.decision=='NO_ACTION'


def test_missing_container_quarantined_never_replayed():
    j,d,i=sample()
    o=observe_operation(instance=i,deployment=d,journal=j,
                        docker_state=DockerState('missing',{}))
    assert (o.code,o.decision)==('C1D3_CONTAINER_MISSING','QUARANTINE')


def test_running_container_unresolved_not_adopted():
    j,d,i=sample()
    o=observe_operation(instance=i,deployment=d,journal=j,
                        docker_state=state_for(i))
    assert o.code=='C1D3_RUNNING_UNRESOLVED' and o.decision=='QUARANTINE'


def test_security_label_mismatch_never_adopted():
    j,d,i=sample()
    docker=state_for(i)
    docker.labels['augmis.tenant_id']='wrong'
    o=observe_operation(instance=i,deployment=d,journal=j,docker_state=docker)
    assert o.decision=='SECURITY_REVIEW'


def test_persisted_id_mismatch_never_adopted():
    j,d,i=sample();d.container_id='b'*64
    o=observe_operation(instance=i,deployment=d,journal=j,docker_state=state_for(i))
    assert o.code=='C1D3_CONTAINER_ID_MISMATCH' and o.decision=='SECURITY_REVIEW'


@pytest.mark.parametrize('conflict', ['deployment','journal_instance','journal_tenant','journal_deployment'])
def test_ownership_mismatch_security_stop(conflict):
    j,d,i=sample()
    if conflict=='deployment':d.instance_id=uuid.uuid4()
    elif conflict=='journal_instance':j.instance_id=uuid.uuid4()
    elif conflict=='journal_tenant':j.tenant_id=uuid.uuid4()
    else:j.deployment_id=uuid.uuid4()
    o=observe_operation(instance=i,deployment=d,journal=j,docker_state=state_for(i))
    assert o.decision=='SECURITY_REVIEW'


def test_docker_outage_flagged_without_dumping_secrets():
    j,d,i=sample()
    o=observe_operation(instance=i,deployment=d,journal=j,
                        docker_state=None,docker_error='C1D3_DOCKER_UNAVAILABLE')
    assert o.code=='C1D3_DOCKER_INSPECT_UNAVAILABLE'
    assert 'password' not in str(o).lower()


def fake_db(j,d,i, *, concurrent=False):
    db=MagicMock()
    db.execute.return_value=[(j,d,i)]
    if concurrent:
        new=NS(**vars(j))
        new.state='active'
        db.scalar.return_value=new
    else:
        db.scalar.return_value=j
    return db


def test_dry_run_never_mutates_even_when_stale():
    j,d,i=sample()
    db=fake_db(j,d,i)
    r=reconcile_once(db,tenant_id=i.tenant_id,now=NOW,
                     inspector=lambda _:state_for(i))
    assert r['stale']==1 and r['quarantined']==0
    assert j.state=='queued'
    db.commit.assert_not_called()
    assert db.rollback.call_count==1


def test_apply_only_updates_journal_metadata():
    j,d,i=sample()
    db=fake_db(j,d,i)
    r=reconcile_once(db,tenant_id=i.tenant_id,now=NOW,apply=True,
                     inspector=lambda _:DockerState('missing',{}))
    assert r['quarantined']==1
    assert j.state=='needs_reconciliation'
    assert j.failure_code=='C1D3_CONTAINER_MISSING'
    assert d.status=='running' # deliberately unchanged
    assert j.lease_until is None and j.owner is None
    db.commit.assert_called_once()


def test_concurrent_operation_wins_and_stays_untouched():
    j,d,i=sample()
    db=fake_db(j,d,i,concurrent=True)
    r=reconcile_once(db,tenant_id=i.tenant_id,now=NOW,apply=True,
                     inspector=lambda _:state_for(i))
    assert r['records'][0]['code']=='C1D3_CONCURRENT_CHANGE'
    assert r['quarantined']==0
    db.commit.assert_not_called()


def test_docker_down_never_blocks_metadata_quarantine():
    j,d,i=sample()
    db=fake_db(j,d,i)
    def down(_):raise DockerInspectionError('C1D3_DOCKER_UNAVAILABLE')
    r=reconcile_once(db,tenant_id=i.tenant_id,now=NOW,apply=True,inspector=down)
    assert r['quarantined']==1
    assert j.failure_code=='C1D3_DOCKER_INSPECT_UNAVAILABLE'


def test_new_job_is_ignored():
    j,d,i=sample(seconds_old=60)
    db=fake_db(j,d,i)
    r=reconcile_once(db,tenant_id=i.tenant_id,now=NOW,apply=True,
                     inspector=lambda _:(_ for _ in ()).throw(AssertionError('unexpected Docker')))
    assert r['stale']==0
    db.commit.assert_not_called()


def test_no_tenant_means_no_query():
    with pytest.raises(ValueError,match='TENANT_REQUIRED'):
        reconcile_once(MagicMock(),tenant_id=None)


@pytest.mark.parametrize('limit', [0,101,-1])
def test_limit_enforced(limit):
    with pytest.raises(ValueError,match='LIMIT_INVALID'):
        reconcile_once(MagicMock(),tenant_id=uuid.uuid4(),limit=limit)


def test_scope_is_enforced_in_statement():
    j,d,i=sample()
    db=fake_db(j,d,i)
    reconcile_once(db,tenant_id=i.tenant_id,now=NOW,inspector=lambda _:state_for(i))
    compiled=str(db.execute.call_args.args[0]);assert 'tenant_id' in compiled
    assert 'deployment_operation_journals.state' in compiled


def test_no_runtime_docker_or_database_write_functions():
    root=Path(__file__).resolve().parents[1]
    service=(root/'services/api/app/services/c1d3_reconciliation_worker.py').read_text()
    for forbidden in ('subprocess.run(', 'stop_container(', 'start_container(', 'docker rm',
                     'docker run', 'drop_database(', 'db.delete(', 'baseline_version_id =',
                     'active_version_id ='):
        assert forbidden not in service


def test_cli_requires_tenant_and_explicit_mutation_flag():
    source=(Path(__file__).resolve().parents[1]/'tools/c1d3_reconciliation_worker.py').read_text()
    assert 'required=True' in source and "'--apply'" in source
    assert "'--watch'" in source and "'--once'" in source
