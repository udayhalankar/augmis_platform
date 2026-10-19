"""Offline C1-D2 smoke-runner security/regression tests; never invokes Docker."""
import uuid
import pytest
from unittest.mock import patch
from services.api.app.services.c1d2_disposable_qualification import (
    RuntimeImages, DisposableQualification, QualificationFailure,
    _jwt, _port, _inspect_network, _inspect_ports, _quote,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import jwt

IMAGE = 'sha256:' + 'a'*64
CONFIG = RuntimeImages(IMAGE, IMAGE, 'augmis-crud-dev-ingress')
BASE = {
    'metadata': {'id': 'augmis-test'},
    'runtime': {'deploymentMode':'dedicated','buildType':'dockerfile'},
    'services': {'web':{'type':'web','public':True,'port':8080,'health':{'path':'/health'}}},
    'authentication': {'type':'augmis_oidc','required':True},
    'addons': {'database': {'type':'postgresql','version':'15', 'schema':{'tables':[
        {'name':'asset_checkouts','columns':[{'name':'asset_tag','type':'text','maxLength':60}]}
    ]}}},
    'gateway': {'routes':[{'path':'/api/checkouts','methods':['GET','POST']}]} ,
}

def test_manifest_accepted():
    probe=DisposableQualification(manifest=BASE,image_id=IMAGE,images=CONFIG)
    assert probe.get_path=='/api/checkouts'
    assert probe.plan.requires_private_database

@pytest.mark.parametrize('id', ['test:1', '', 'sha256:AAA', 37, None])
def test_immutable_image_required(id):
    with pytest.raises(QualificationFailure, match='C1D2_IMMUTABLE_APP_IMAGE_REQUIRED'):
        DisposableQualification(manifest=BASE,image_id=id,images=CONFIG)

@pytest.mark.parametrize('network',['bridge','host','none','bad/network',''])
def test_invalid_network(network):
    with pytest.raises(QualificationFailure, match='C1D2_INGRESS_NETWORK_INVALID'):
        RuntimeImages(IMAGE,IMAGE,network).validate()

def test_invalid_relay_image():
    with pytest.raises(QualificationFailure,match='C1D2_IMAGE_ID_INVALID'):
        RuntimeImages(IMAGE,'postgres:15-alpine','augmis-intake').validate()

def test_requires_gateway_and_schema():
    broken={**BASE,'gateway':None}
    with pytest.raises(QualificationFailure,match='C1D2_UNSUPPORTED_SMOKE_CONTRACT'):
        DisposableQualification(manifest=broken,image_id=IMAGE,images=CONFIG)

def test_readonly_smoke_route_required():
    broken={**BASE,'gateway': {'routes':[{'path':'/api/checkouts','methods':['POST']}]}}
    with pytest.raises(QualificationFailure,match='C1D2_READONLY_SMOKE_ROUTE_REQUIRED'):
        DisposableQualification(manifest=broken,image_id=IMAGE,images=CONFIG)

def test_signed_jwt_scopes_and_wrong_tenant():
    key=Ed25519PrivateKey.generate()
    ids=(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    good=jwt.decode(_jwt(key,tenant=ids[0],app=ids[1],instance=ids[2],path='/api/checkouts'),
                    key.public_key(), algorithms=['EdDSA'],audience=f'augmis.runtime:{ids[2]}')
    assert good['tenantId']==str(ids[0]) and good['path']=='/api/checkouts'
    assert good['bodySha256']=='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
    wrong=jwt.decode(_jwt(key,tenant=ids[0],app=ids[1],instance=ids[2],path='/api/checkouts',foreign_tenant=True),
                     key.public_key(),algorithms=['EdDSA'],audience=f'augmis.runtime:{ids[2]}')
    assert wrong['tenantId'] != good['tenantId']

def test_safe_sql_literal():
    assert _quote("x'; DROP TABLE public.foo;--") == "'x''; DROP TABLE public.foo;--'"

def test_loopback_only_port():
    with patch('services.api.app.services.c1d2_disposable_qualification._cmd',return_value='127.0.0.1:45677'):
        assert _port('augmis-q-test-relay')==45677
    with patch('services.api.app.services.c1d2_disposable_qualification._cmd',return_value='0.0.0.0:45677'):
        with pytest.raises(QualificationFailure,match='C1D2_RELAY_NOT_LOOPBACK_ONLY'):
            _port('augmis-q-test-relay')

def test_reject_published_app_db_ports():
    with patch('services.api.app.services.c1d2_disposable_qualification._cmd',return_value='{"8080/tcp":null}'):
        assert _inspect_ports('app')
    with patch('services.api.app.services.c1d2_disposable_qualification._cmd',return_value='{"5432/tcp":[{"HostIp":"0.0.0.0","HostPort":"5432"}]}'):
        assert not _inspect_ports('db')

def test_network_boolean_strict():
    with patch('services.api.app.services.c1d2_disposable_qualification._cmd',return_value='true'):
        assert _inspect_network('private')
    with patch('services.api.app.services.c1d2_disposable_qualification._cmd',return_value='false'):
        assert not _inspect_network('ingress')
    with patch('services.api.app.services.c1d2_disposable_qualification._cmd',return_value='maybe'):
        with pytest.raises(QualificationFailure,match='C1D2_NETWORK_POLICY_UNKNOWN'):
            _inspect_network('n')
