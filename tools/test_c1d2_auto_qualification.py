"""No Docker/PG writes. C1-D2 pre-publication queue and gate regression."""
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from services.api.app.services import c1d2_automatic_qualification as q

APP_ID = uuid.uuid4()
VERSION_ID = uuid.uuid4()
BUILD_ID = uuid.uuid4()
IMAGE = 'sha256:' + 'a'*64
MANIFEST = {
    'metadata': {'id':'augmis-asset-checkout-lab'},
    'runtime': {'deploymentMode':'dedicated','buildType':'dockerfile'},
    'services': {'web':{'type':'web','public':True,'port':8080,'health':{'path':'/health'}}},
    'authentication': {'type':'augmis_oidc','required':True},
    'addons': {'database': {'type':'postgresql','version':'15','schema':{'tables':[
        {'name':'asset_checkouts','columns':[{'name':'asset_tag','type':'text','maxLength':60}]}
    ]}}},
    'gateway': {'routes':[{'path':'/api/checkouts','methods':['GET','POST']}]} ,
}

def build():
    return SimpleNamespace(id=BUILD_ID, application_version_id=VERSION_ID,
        status='ready', image_ref='augmis.local/app:1', immutable_image_id=IMAGE)

def version():
    return SimpleNamespace(id=VERSION_ID, status='image_ready', version='1.0.0',
        build_type='dockerfile', publication_status='draft', manifest=MANIFEST)


def test_supported_contract_and_reject_incomplete():
    assert q.supported_manifest(MANIFEST)
    assert not q.supported_manifest({})
    assert not q.supported_manifest({**MANIFEST, 'gateway': {}})


def test_enqueue_exact_immutable_build():
    db=Mock(); b=build();v=version(); row=object()
    with patch.object(q,'pinned_image_identity',return_value=IMAGE),patch.object(q,'record_pending_qualification',return_value=row) as pending:
        assert q.enqueue_ready_build(db,build=b,version=v) is row
    assert pending.call_args.kwargs['image_id']==IMAGE
    assert pending.call_args.kwargs['version_id']==VERSION_ID


def test_enqueue_fails_closed_on_wrong_contract():
    v=version();v.manifest={}
    with pytest.raises(q.QualificationGateError,match='C1D2_CONTRACT_NOT_QUALIFIABLE'):
        q.enqueue_ready_build(Mock(),build=build(),version=v)


def test_queue_image_failure_does_not_mark_passed():
    with patch.object(q,'pinned_image_identity',side_effect=q.RuntimeControlError('missing')):
        with pytest.raises(q.QualificationGateError,match='C1D2_BUILD_IDENTITY_NOT_PINNED'):
            q.enqueue_ready_build(Mock(),build=build(),version=version())


def test_static_web_publication_exempt():
    v=version();v.build_type='static_web'
    assert q.require_passing_build(Mock(),version=v) is None


def test_publish_requires_passed_exact_build():
    db=Mock();b=build();v=version(); db.scalar.side_effect=[b,object()]
    with patch.object(q,'pinned_image_identity',return_value=IMAGE),patch.object(q,'valid_qualification',return_value=True):
        assert q.require_passing_build(db,version=v) is not None


def test_publish_rejects_stale_or_missing_evidence():
    db=Mock();b=build();v=version();db.scalar.side_effect=[b,object()]
    with patch.object(q,'pinned_image_identity',return_value=IMAGE),patch.object(q,'valid_qualification',return_value=False):
        with pytest.raises(q.QualificationGateError,match='C1D2_QUALIFICATION_REQUIRED'):
            q.require_passing_build(db,version=v)


def test_publish_rejects_unsupported_contract():
    v=version();v.manifest={}
    with pytest.raises(q.QualificationGateError,match='C1D2_UNSUPPORTED_APPLICATION_CONTRACT'):
        q.require_passing_build(Mock(),version=v)


def test_worker_idle_without_pending():
    db=Mock();db.scalar.return_value=None
    profile=SimpleNamespace(environment={})
    with patch.object(q,'read_profile',return_value=profile), patch.object(q,'check_runtime_host',return_value=SimpleNamespace(ready=True)):
        assert q.worker_one(db)=='IDLE'


def test_worker_fail_closed_without_profile():
    with patch.object(q,'read_profile',return_value=None):
        with pytest.raises(q.QualificationGateError,match='C1D2_RUNTIME_HOST_UNREADY'):
            q.worker_one(Mock())


def test_worker_rejects_changed_candidate_without_docker():
    db=Mock();row=SimpleNamespace(build_id=BUILD_ID,application_version_id=VERSION_ID)
    db.scalar.return_value=row
    b=build();b.status='failed';v=version()
    db.get.side_effect=[b,v]
    with patch.object(q,'read_profile',return_value=SimpleNamespace(environment={})),patch.object(q,'check_runtime_host',return_value=SimpleNamespace(ready=True)):
        assert q.worker_one(db)=='FAIL'
    assert row.status=='needs_review'
    assert row.failure_code=='C1D2_CANDIDATE_CHANGED'
    db.commit.assert_called_once()


def test_worker_marks_live_success_only_after_runner_result():
    db=Mock();row=SimpleNamespace(build_id=BUILD_ID,application_version_id=VERSION_ID, started_at=None,
                                  image_id=IMAGE)
    db.scalar.return_value=row
    db.get.side_effect=[build(),version()]
    env={'AUGMIS_C1B_POSTGRES_IMAGE_ID':IMAGE, 'AUGMIS_C1C_GENERIC_RELAY_IMAGE_ID':IMAGE,
         'AUGMIS_C1B_CRUD_INGRESS_NETWORK':'augmis-dev-ingress'}
    checks={k:True for k in q.SMOKE_KEYS}
    runner=Mock(return_value=Mock(run=Mock(return_value=checks)))
    with patch.object(q,'read_profile',return_value=SimpleNamespace(environment=env)), patch.object(q,'check_runtime_host',return_value=SimpleNamespace(ready=True)),patch.object(q,'pinned_image_identity',return_value=IMAGE),patch.object(q,'record_smoke_result') as record:
        assert q.worker_one(db,runner_class=runner)=='PASS'
    assert row.started_at is not None
    assert db.commit.call_count==2
    assert record.call_args.kwargs['checks']==checks
    assert runner.call_count==1


def test_worker_failure_is_a_failed_record_not_a_pass():
    db=Mock();row=SimpleNamespace(build_id=BUILD_ID,application_version_id=VERSION_ID,image_id=IMAGE)
    db.scalar.return_value=row;db.get.side_effect=[build(),version()]
    env={'AUGMIS_C1B_POSTGRES_IMAGE_ID':IMAGE, 'AUGMIS_C1C_GENERIC_RELAY_IMAGE_ID':IMAGE,
         'AUGMIS_C1B_CRUD_INGRESS_NETWORK':'augmis-dev-ingress'}
    runner=Mock(return_value=Mock(run=Mock(side_effect=q.QualificationFailure('C1D2_HEALTH_FAILED'))))
    with patch.object(q,'read_profile',return_value=SimpleNamespace(environment=env)),patch.object(q,'check_runtime_host',return_value=SimpleNamespace(ready=True)),patch.object(q,'pinned_image_identity',return_value=IMAGE),patch.object(q,'record_smoke_result') as record:
        assert q.worker_one(db,runner_class=runner)=='FAIL'
    assert record.call_args.kwargs['failure_code']=='C1D2_HEALTH_FAILED'
    assert not any(record.call_args.kwargs['checks'].values())
