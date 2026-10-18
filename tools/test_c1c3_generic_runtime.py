"""C1-C3 offline tests. Never reach real Docker/PostgreSQL or network."""
from __future__ import annotations
import importlib.util
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
import pytest
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from services.api.app.services import aaps_runtime_assertions as assertions
from services.api.app.services import deployment_engine as engine
from services.api.app.services import private_crud_runtime as runtime
from services.api.app.services import aaps_deployment_contract as contracts


def manifest():
    return {'metadata':{'id':'example-maintenance'},
        'runtime':{'deploymentMode':'dedicated','buildType':'dockerfile'},
        'services':{'web':{'type':'web','port':8080,'public':True,'health':{'path':'/health'}}},
        'authentication':{'type':'augmis_oidc','required':True},
        'addons':{'database':{'type':'postgresql','version':'15','schema':{'tables':[
            {'name':'maintenance_work_orders','columns':[{'name':'title','type':'text','maxLength':140}]}]}}},
        'gateway':{'routes':[{'path':'/api/overview','methods':['GET']},
                             {'path':'/api/work-orders','methods':['GET','POST']},
                             {'path':'/api/work-orders/{id:uuid}','methods':['GET','PUT','DELETE']}]}}


def context(m=None):
    def obj(i):return SimpleNamespace(id=uuid.UUID(i))
    return {'version':SimpleNamespace(manifest=m or manifest()),
         'tenant':obj('b6e8ccbc-aefb-4a4d-8955-1434dc1213d7'),
         'application':obj('54ef8cf6-7753-4d0c-b308-e2b87f18a0b2'),
         'instance':obj('6074d0c9-e4bc-4926-8051-e4900b6e194c'),
         'user':obj('a0000000-0000-0000-0000-000000000001')}


def test_route_contract_positive_and_negative():
    m=manifest()
    u='00112233-4455-6677-8899-aabbccddeeff'
    assert assertions.declared_route_allowed(m,method='GET',path='/api/overview')
    assert assertions.declared_route_allowed(m,method='POST',path='/api/work-orders')
    assert assertions.declared_route_allowed(m,method='PUT',path='/api/work-orders/'+u)
    assert not assertions.declared_route_allowed(m,method='POST',path='/api/overview')
    assert not assertions.declared_route_allowed(m,method='GET',path='/api/work-orders/notuuid')
    assert not assertions.declared_route_allowed(m,method='GET',path='/api/work-orders/%2e%2e')
    assert not assertions.declared_route_allowed(m,method='GET',path='/api/admin')


def test_signed_assertion_binds_body_method_tenant_and_instance(monkeypatch,tmp_path):
    key=Ed25519PrivateKey.generate()
    priv=tmp_path/'private.pem';pub=tmp_path/'public.pem'
    priv.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
    monkeypatch.setattr(assertions,'signing_material',lambda:(priv,pub))
    c=context();token=assertions.make_aaps_request_assertion(context=c,method='POST',relative_path='api/work-orders',body=b'{"title":"ok"}')
    claim=jwt.decode(token,key.public_key(),algorithms=['EdDSA'],audience='augmis.runtime:'+str(c['instance'].id),options={'verify_aud':True})
    assert claim['tenantId']==str(c['tenant'].id) and claim['applicationId']==str(c['application'].id)
    assert claim['scope']==['records.write'] and claim['method']=='POST' and claim['path']=='/api/work-orders'
    assert claim['bodySha256']


def test_signer_refuses_undeclared_api():
    with pytest.raises(runtime.CrudRuntimeError,match='C1C_ROUTE_OR_METHOD_NOT_ALLOWED'):
        assertions.make_aaps_request_assertion(context=context(),method='POST',relative_path='api/overview',body=b'{}')


def test_generic_gate_is_development_opt_in(monkeypatch):
    monkeypatch.delenv('AUGMIS_C1C_GENERIC_RUNTIME_ENABLED',raising=False)
    with pytest.raises(contracts.DeploymentContractError,match='ADAPTER_PENDING'):
        contracts.fail_closed_if_unimplemented(manifest(),legacy_crud=False)
    monkeypatch.setenv('AUGMIS_C1C_GENERIC_RUNTIME_ENABLED','1')
    import services.api.app.core.config as cfg
    monkeypatch.setattr(cfg,'settings',SimpleNamespace(app_env='development'))
    contracts.fail_closed_if_unimplemented(manifest(),legacy_crud=False)
    monkeypatch.setattr(cfg,'settings',SimpleNamespace(app_env='production'))
    with pytest.raises(contracts.DeploymentContractError,match='ADAPTER_PENDING'):
        contracts.fail_closed_if_unimplemented(manifest(),legacy_crud=False)


def load_relay():
    filename=Path(__file__).resolve().parents[0]/'c1b4_crud_dev_ingress_relay'/'server.py'
    # actual relay is in tools/c1b4...
    filename=Path(__file__).resolve().parents[0]/'c1b4_crud_dev_ingress_relay'/'server.py'
    spec=importlib.util.spec_from_file_location('c1c_relay_test',filename)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m


def test_relay_generic_allowlist_and_legacy(monkeypatch):
    relay=load_relay()
    assert relay.allowed('GET','/api/records')
    assert not relay.allowed('GET','/api/work-orders')
    m=manifest();routes=[{'path':x['path'],'methods':x['methods']} for x in m['gateway']['routes']]
    assert relay._declared_allowed('GET','/',routes,'/health')
    assert relay._declared_allowed('GET','/health',routes,'/health')
    assert relay._declared_allowed('POST','/api/work-orders',routes,'/health')
    assert relay._declared_allowed('PUT','/api/work-orders/00112233-4455-6677-8899-aabbccddeeff',routes,'/health')
    assert not relay._declared_allowed('POST','/api/overview',routes,'/health')
    assert not relay._declared_allowed('GET','/api/work-orders/%2f..',routes,'/health')
    monkeypatch.setenv('AUGMIS_RELAY_ROUTE_CONTRACT',json.dumps(routes))
    assert relay._relay_contract()==routes
    monkeypatch.setenv('AUGMIS_RELAY_ROUTE_CONTRACT','[{"path":"/api/admin","methods":["GET"]},{"bad":"x"}]')
    with pytest.raises(ValueError):relay._relay_contract()


def test_generic_launcher_uses_no_python_and_only_loopback(monkeypatch,tmp_path):
    import services.api.app.core.config as cfg
    monkeypatch.setattr(cfg,'settings',SimpleNamespace(app_env='development'))
    commands=[];checked=[]
    app_image='sha256:'+'a'*64;relay_image='sha256:'+'b'*64
    def run(args,timeout=120):
        commands.append(args)
        if args[1:3]==['network','inspect']:
            return 'true' if args[-1]=='augmis-prv-test' else 'false'
        if args[1:3]==['image','inspect']:
            return args[-1] if '{{.Id}}' in args else ('10002:10002' if args[-1]==relay_image else '10001:10001')
        if args[1:2]==['port']:return '127.0.0.1:43000'
        return 'id'
    monkeypatch.setattr(engine,'run_docker',run)
    monkeypatch.setattr(engine,'wait_for_health',lambda url,sec: checked.append((url,sec)))
    launch=runtime.CrudRuntimeLaunch(
        network_name='augmis-prv-test',ingress_network='augmis-ingress',
        relay_image_id=relay_image,secret_volume='secret',public_key_file=tmp_path/'public.pem',
        environment={'APP_TENANT_ID':'test'},declared_routes=(('/api/overview',('GET',)),('/api/work-orders',('GET','POST'))),
        service_port=8080,health_path='/health')
    result=engine._start_private_crud_container(image_ref=app_image,
        manifest={'services':{'web':{'public':True,'port':8080,'health':{'path':'/health'}}}},
        container_name='augmis-independent-app',labels={'augmis.instance_id':'test'},
        environment={},launch=launch)
    assert result['host_port']==43000 and checked==[('http://127.0.0.1:43000/health',180)]
    assert not any(len(c)>2 and c[1]=='exec' for c in commands)
    relayrun=[c for c in commands if c[1:3]==['run','-d'] and '-p' in c][0]
    assert '127.0.0.1::18080' in relayrun
    assert any(x.startswith('AUGMIS_RELAY_ROUTE_CONTRACT=') for x in relayrun)
    assert any(x.startswith('AUGMIS_RELAY_UPSTREAM_PORT=') for x in relayrun)
    assert not any('-p' in c for c in commands if c[1:3]==['run','-d'] and '-p' not in c)
