"""C1-D2/D3 regression tests; no live DB or Docker dependency."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
import uuid
import pytest

from services.api.app.services.deployment_reliability import (
    ReliabilityError, manifest_digest, valid_qualification, record_pending_qualification,
    record_smoke_result, reserve_journal, claim_journal, advance_stage,
    quarantine_expired, record_failure, REQUIRED_SMOKE,
)

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)
ID1, ID2, ID3 = (uuid.uuid4() for _ in range(3))
IMAGE = 'sha256:' + 'a' * 64
MANIFEST = {'metadata': {'id': 'app'}, 'runtime': {'buildType': 'dockerfile'}}


def session(scalar=None, all_rows=()):
    db = MagicMock()
    db.scalar.return_value = scalar
    db.scalars.return_value = all_rows
    return db


def journal(state='queued', stage='reserved', owner=None, lease=None):
    return SimpleNamespace(deployment_id=ID1, tenant_id=ID2, instance_id=ID3,
        state=state, stage=stage, owner=owner, lease_until=lease,
        attempt=0, failure_code=None)


def qualification(**kwargs):
    defaults = dict(status='passed', build_id=ID1, application_version_id=ID2,
        image_id=IMAGE, manifest_sha256=manifest_digest(MANIFEST),
        finished_at=NOW, qualifier_revision='qualifier-v1',
        checks_json={name:True for name in REQUIRED_SMOKE})
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_digest_order_independent():
    assert manifest_digest({'a':1,'b':2}) == manifest_digest({'b':2,'a':1})

@pytest.mark.parametrize('bad', [None, [], {'x': float('nan')}, {'x': object()}])
def test_bad_manifest_rejected(bad):
    with pytest.raises(ReliabilityError): manifest_digest(bad)


def test_large_manifest_fails_closed():
    with pytest.raises(ReliabilityError, match='TOO_LARGE'): manifest_digest({'a':'x'*300000})


def test_no_evidence_cannot_pass():
    assert not valid_qualification(None, build_id=ID1, version_id=ID2, image_id=IMAGE, manifest=MANIFEST)
    assert not valid_qualification(qualification(checks_json={'internal_health': True}), build_id=ID1, version_id=ID2,image_id=IMAGE,manifest=MANIFEST)

@pytest.mark.parametrize('key,value', [
    ('status','pending_smoke'), ('image_id','sha256:'+'b'*64),
    ('manifest_sha256','0'*64), ('qualifier_revision',None),
    ('build_id',ID3), ('application_version_id',ID3),
    ('finished_at',None),
])
def test_qualification_identity_and_evidence_fail_closed(key,value):
    assert not valid_qualification(qualification(**{key:value}), build_id=ID1,
       version_id=ID2,image_id=IMAGE,manifest=MANIFEST)


def test_valid_qualification():
    assert valid_qualification(qualification(),build_id=ID1,
       version_id=ID2,image_id=IMAGE,manifest=MANIFEST)


def test_pending_record_does_not_claim_pass():
    db = session()
    obj = record_pending_qualification(db,build_id=ID1,version_id=ID2,image_id=IMAGE,manifest=MANIFEST)
    assert obj.status == 'pending_smoke'
    db.add.assert_called_once()


def test_recheck_detects_manifest_drift_and_quarantines():
    q=qualification()
    db=session(q)
    row=record_pending_qualification(db,build_id=ID1,version_id=ID2,image_id=IMAGE,manifest={'a':2})
    assert row.status == 'needs_review'
    assert row.checks_json is None
    assert row.failure_code == 'C1D_BUILD_IDENTITY_CHANGED'


def test_bad_image_id_rejected():
    with pytest.raises(ReliabilityError,match='IMAGE_ID'): record_pending_qualification(session(), build_id=ID1,version_id=ID2,image_id='latest',manifest=MANIFEST)


def test_smoke_result_rejects_partial_attestation():
    db=session(qualification(status='pending_smoke'))
    with pytest.raises(ReliabilityError,match='EVIDENCE_INVALID'):
        record_smoke_result(db, build_id=ID1,version_id=ID2,image_id=IMAGE,
            manifest=MANIFEST,qualifier_revision='v1',checks={'internal_health':True})


def test_smoke_failed_result_needs_code():
    db=session(qualification(status='pending_smoke'))
    checks={name:True for name in REQUIRED_SMOKE};checks['internal_health']=False
    with pytest.raises(ReliabilityError,match='FAILURE_CODE_REQUIRED'):
        record_smoke_result(db,build_id=ID1,version_id=ID2,image_id=IMAGE,
          manifest=MANIFEST,qualifier_revision='v1',checks=checks)


def test_smoke_success_needs_exact_attestation():
    db=session(qualification(status='pending_smoke'))
    row=record_smoke_result(db,build_id=ID1,version_id=ID2,image_id=IMAGE,
        manifest=MANIFEST,qualifier_revision='v1',checks={name:True for name in REQUIRED_SMOKE},at=NOW)
    assert row.status=='passed' and row.finished_at==NOW and row.failure_code is None


def test_smoke_cannot_requalify_passed_without_review():
    db=session(qualification())
    with pytest.raises(ReliabilityError,match='NOT_PENDING'):
        record_smoke_result(db,build_id=ID1,version_id=ID2,image_id=IMAGE,
           manifest=MANIFEST,qualifier_revision='v1',checks={name:True for name in REQUIRED_SMOKE})


def test_reserve_journal_is_idempotent_and_tenant_safe():
    db=session()
    r=reserve_journal(db,deployment_id=ID1,tenant_id=ID2,instance_id=ID3)
    assert r.stage=='reserved' and r.state=='queued'
    db.scalar.return_value=r
    assert reserve_journal(db,deployment_id=ID1,tenant_id=ID2,instance_id=ID3) is r
    with pytest.raises(ReliabilityError,match='OWNERSHIP_CONFLICT'):
       reserve_journal(db,deployment_id=ID1,tenant_id=ID3,instance_id=ID3)


def test_claim_and_forward_transitions():
    r=journal()
    db=session(r)
    claim_journal(db,deployment_id=ID1,worker='node1',at=NOW)
    assert r.state=='running' and r.attempt==1
    advance_stage(db,deployment_id=ID1,worker='node1',stage='database_ready',at=NOW)
    assert r.stage=='database_ready'
    advance_stage(db,deployment_id=ID1,worker='node1',stage='runtime_starting',at=NOW)
    advance_stage(db,deployment_id=ID1,worker='node1',stage='health_checking',at=NOW)
    advance_stage(db,deployment_id=ID1,worker='node1',stage='gateway_verifying',at=NOW)
    advance_stage(db,deployment_id=ID1,worker='node1',stage='active',at=NOW)
    assert r.state=='active' and r.owner is None


def test_no_reclaim_active():
    db=session(journal(state='active'))
    with pytest.raises(ReliabilityError,match='NOT_QUEUED'):claim_journal(db,deployment_id=ID1,worker='node1')


def test_wrong_worker_cannot_advance():
    db=session(journal(state='running',owner='node1',lease=NOW+timedelta(minutes=5)))
    with pytest.raises(ReliabilityError,match='NOT_OWNED'):advance_stage(db,deployment_id=ID1,worker='node2',stage='active',at=NOW)


def test_expired_lease_cannot_advance():
    db=session(journal(state='running',owner='node1',lease=NOW))
    with pytest.raises(ReliabilityError,match='LEASE_EXPIRED'):advance_stage(db,deployment_id=ID1,worker='node1',stage='active',at=NOW)


def test_stage_regression_denied():
    db=session(journal(state='running',stage='health_checking',owner='node1',lease=NOW+timedelta(minutes=5)))
    with pytest.raises(ReliabilityError,match='REGRESSION'):advance_stage(db,deployment_id=ID1,worker='node1',stage='database_ready',at=NOW)


def test_unknown_stage_denied():
    with pytest.raises(ReliabilityError,match='STAGE_INVALID'):
        advance_stage(session(),deployment_id=ID1,worker='node1',stage='delete_database')


def test_expired_journal_quarantined_never_retried():
    r=journal(state='running',owner='node1',lease=NOW-timedelta(seconds=1))
    db=session(all_rows=[r])
    assert quarantine_expired(db,at=NOW)==1
    assert r.state=='needs_reconciliation' and r.owner is None
    assert r.attempt == 0  # no implicit retries
    db.commit.assert_not_called() # caller decides transaction scope


def test_failure_code_validated():
    db=session(journal(state='running',owner='node1'))
    with pytest.raises(ReliabilityError,match='FAILURE_CODE_INVALID'):
        record_failure(db,deployment_id=ID1,worker='node1',failure_code='secret: a')
    row=record_failure(db,deployment_id=ID1,worker='node1',failure_code='C1D_HEALTH_CHECK_FAILED')
    assert row.state=='failed'


def test_migration_parent_expected():
    import importlib.util
    from pathlib import Path
    p=Path(__file__).resolve().parents[1] / 'services/api/alembic/versions/c1d23_20261018_qualification_and_journal.py'
    s=importlib.util.spec_from_file_location('c1d23_migration',p)
    mod=importlib.util.module_from_spec(s);s.loader.exec_module(mod)
    assert mod.down_revision=='c1b2_20261017'


def test_cannot_mark_active_without_gateway_verification():
    r=journal(state='running',stage='health_checking',owner='node1',lease=NOW+timedelta(minutes=5))
    db=session(r)
    with pytest.raises(ReliabilityError,match='GATEWAY_VERIFICATION_REQUIRED'):
        advance_stage(db,deployment_id=ID1,worker='node1',stage='active',at=NOW)


def test_cannot_skip_health_verification_for_gateway():
    r=journal(state='running',stage='database_ready',owner='node1',lease=NOW+timedelta(minutes=5))
    with pytest.raises(ReliabilityError,match='HEALTH_VERIFICATION_REQUIRED'):
        advance_stage(session(r),deployment_id=ID1,worker='node1',stage='gateway_verifying',at=NOW)
