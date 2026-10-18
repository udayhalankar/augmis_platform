"""Offline security and integration tests. No Docker, PostgreSQL or network access."""
import asyncio
import importlib.util
import types
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from starlette.requests import Request

from services.api.app.services import private_crud_runtime as runtime
from services.api.app.services import crud_runtime_assertions as signing
from services.api.app.services import deployment_engine as docker


def _keypair(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    p = tmp_path / 'private.pem'
    q = tmp_path / 'public.pem'
    p.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    q.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    monkeypatch.setenv('AUGMIS_C1B_CRUD_SIGNING_PRIVATE_KEY_FILE', str(p))
    monkeypatch.setenv('AUGMIS_C1B_CRUD_SIGNING_PUBLIC_KEY_FILE', str(q))
    return key, p, q


def _context(monkeypatch):
    ids = [uuid.uuid4() for _ in range(4)]
    app, tenant, instance, user = ids
    monkeypatch.setenv('AUGMIS_C1B_CRUD_APPLICATION_ID', str(app))
    monkeypatch.setenv('AUGMIS_C1B_CRUD_PRIVATE_RUNTIME_ENABLED', '1')
    monkeypatch.setattr(signing, 'settings', SimpleNamespace(app_env='development'))
    return dict(application=SimpleNamespace(id=app), tenant=SimpleNamespace(id=tenant),
                instance=SimpleNamespace(id=instance), user=SimpleNamespace(id=user))


def test_signed_request_scope_and_body(tmp_path, monkeypatch):
    key, _, _ = _keypair(tmp_path, monkeypatch)
    context = _context(monkeypatch)
    token = signing.make_crud_request_assertion(
        context=context, method='POST', relative_path='api/records', body=b'{"name":"a"}')
    decoded = jwt.decode(token, key.public_key(), algorithms=['EdDSA'], issuer='augmis.control-plane',
                         audience=f"augmis.runtime:{context['instance'].id}")
    assert decoded['method'] == 'POST'
    assert decoded['scope'] == ['records.write']
    assert decoded['path'] == '/api/records'
    assert decoded['tenantId'] == str(context['tenant'].id)
    assert decoded['exp'] - decoded['iat'] == 20


@pytest.mark.parametrize('method,path', [('DELETE','api/summary'), ('POST','api/summary'),
                                        ('POST','api/records/'+str(uuid.UUID(int=1))),
                                        ('PUT','api/records'), ('GET','api/nope')])
def test_forbidden_methods_and_routes(tmp_path, monkeypatch, method, path):
    _keypair(tmp_path, monkeypatch)
    context = _context(monkeypatch)
    with pytest.raises(runtime.CrudRuntimeError):
        signing.make_crud_request_assertion(context=context,method=method,relative_path=path,body=b'')


def test_signing_pair_mismatch_denied(tmp_path, monkeypatch):
    _keypair(tmp_path, monkeypatch)
    other = Ed25519PrivateKey.generate()
    Path(os.environ['AUGMIS_C1B_CRUD_SIGNING_PUBLIC_KEY_FILE']).write_bytes(
        other.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
    with pytest.raises(runtime.CrudRuntimeError):
        runtime.signing_material()


def test_private_runtime_opt_in_fail_closed(monkeypatch):
    monkeypatch.setattr(runtime, 'settings', SimpleNamespace(app_env='development'))
    monkeypatch.delenv('AUGMIS_C1B_CRUD_PRIVATE_RUNTIME_ENABLED', raising=False)
    obj=SimpleNamespace(application_id=uuid.uuid4())
    with pytest.raises(runtime.CrudRuntimeError):
        runtime.enabled_for(obj, {'metadata':{'id':'augmis-crud-reference'}})
    assert runtime.enabled_for(obj, {'metadata':{'id':'other'}}) is False


def _load_app():
    root=Path(__file__).resolve().parents[1]
    app=root/'examples/augmis-crud-reference-v1.2.0/app/main.py'
    # System development venv may not install the sample image's psycopg;
    # the verifier test never opens a DB, so stub the import locally.
    if importlib.util.find_spec('psycopg') is None:
        stub=types.ModuleType('psycopg')
        rows=types.ModuleType('psycopg.rows')
        rows.dict_row=object()
        stub.rows=rows
        sys.modules['psycopg']=stub
        sys.modules['psycopg.rows']=rows
    spec=importlib.util.spec_from_file_location('test_c1b4_app',app)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _request(method, path, token, body=b'', query=b''):
    async def recv():
        return {'type':'http.request','body':body,'more_body':False}
    return Request({'type':'http','method':method,'path':path,'query_string':query,
                    'headers':[(b'x-augmis-runtime-assertion',token.encode())]}, receive=recv)


def test_end_to_end_signed_token_verifier_and_replay(tmp_path,monkeypatch):
    key, _, _ = _keypair(tmp_path, monkeypatch)
    context = _context(monkeypatch)
    mod=_load_app()
    mod.PUBLIC_KEY=key.public_key()
    mod.TENANT_ID=str(context['tenant'].id)
    mod.APPLICATION_ID=str(context['application'].id)
    mod.INSTANCE_ID=str(context['instance'].id)
    token=signing.make_crud_request_assertion(
        context=context,method='GET',relative_path='api/records',raw_query='q=abc+def',body=b'')
    asyncio.run(mod.require_signed_gateway(asyncio.run(_request('GET','/api/records',token,query=b'q=abc+def'))))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.require_signed_gateway(asyncio.run(_request('GET','/api/records',token,query=b'q=abc+def'))))
    assert exc.value.status_code==401
    token2=signing.make_crud_request_assertion(
        context=context,method='GET',relative_path='api/records',raw_query='q=abc+def',body=b'')
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.require_signed_gateway(asyncio.run(_request('GET','/api/records',token2,query=b'q=other'))))
    assert exc.value.status_code==403


def test_dev_relay_allowlist():
    root=Path(__file__).resolve().parents[1]/'tools/c1b4_crud_dev_ingress_relay/server.py'
    spec=importlib.util.spec_from_file_location('c1b4_dev_relay',root)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.allowed('GET','/health')
    assert mod.allowed('POST','/api/records')
    assert mod.allowed('PUT','/api/records/'+str(uuid.uuid4()))
    assert not mod.allowed('POST','/api/summary')
    assert not mod.allowed('DELETE','/api/records')
    assert not mod.allowed('GET','/api/internal')
    assert not mod.allowed('PATCH','/api/records/'+str(uuid.uuid4()))


def test_private_launch_uses_no_direct_host_app_port(monkeypatch,tmp_path):
    monkeypatch.setattr(docker, 'settings', SimpleNamespace(app_env='development'), raising=False)
    import services.api.app.core.config as config
    monkeypatch.setattr(config, 'settings', SimpleNamespace(app_env='development'))
    commands=[]
    img='sha256:' + 'a'*64
    def fake_run(args, timeout=120):
        commands.append(args)
        if args[1:3] == ['network','inspect']:
            return 'true' if args[-1]=='augmis-prv-test' else 'false'
        if args[1:3] == ['image','inspect']:
            return img if '{{.Id}}' in args else ('10002:10002' if args[-1] == img else '10001:10001')
        if args[1:3] == ['docker','never']:
            raise AssertionError('never')
        if args[1:3] == ['port','augmis-my-crud-ingress']:
            return '127.0.0.1:60003'
        return 'fake-id'
    monkeypatch.setattr(docker,'run_docker',fake_run)
    monkeypatch.setattr(docker,'wait_for_health',lambda *a,**kw: None)
    launch=runtime.CrudRuntimeLaunch(
        network_name='augmis-prv-test',secret_volume='augmis-rw-secret',
        public_key_file=tmp_path/'public.pem',ingress_network='augmis-crud-ingress',
        relay_image_id=img,environment={'APP_TENANT_ID':'trusted-tenant','PGUSER':'restricted-user'})
    result=docker._start_private_crud_container(
        image_ref='sha256:'+'b'*64,
        manifest={'services':{'web':{'public':True,'type':'web','port':8080,'health':{'path':'/health'}}},
                  'lifecycle':{'startupTimeoutSeconds':5}},
        container_name='augmis-my-crud',labels={'augmis.managed':'true'},
        environment={},launch=launch)
    assert result['runtime_url']=='http://127.0.0.1:60003'
    app_runs=[cmd for cmd in commands if cmd[:3]==['docker','run','-d'] and 'augmis-my-crud' in cmd]
    assert len(app_runs)==1
    app_cmd=app_runs[0]
    assert '-p' not in app_cmd
    assert '--network' in app_cmd and 'augmis-prv-test' in app_cmd
    assert 'type=volume,source=augmis-rw-secret,target=/run/secrets,readonly' in app_cmd
    assert 'APP_TENANT_ID=trusted-tenant' in app_cmd
    assert not any('PASSWORD=' in arg or 'DATABASE_URL=' in arg for arg in app_cmd)
