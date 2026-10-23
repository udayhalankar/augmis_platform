"""C1-D5.3 generated application assertion compatibility (no Docker/DB)."""
import hashlib
import os
import time
import uuid
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI

from services.api.app.services.c1d5_runtime_guard import AugmisRuntimeGuard


@pytest.fixture
def configured(monkeypatch, tmp_path):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    public_file = tmp_path / 'public.pem'
    public_file.write_bytes(public)
    ids = {k: str(uuid.uuid4()) for k in ('tenantId','applicationId','instanceId')}
    for environment, claim in (
        ('APP_TENANT_ID','tenantId'),
        ('AUGMIS_RUNTIME_APPLICATION_ID','applicationId'),
        ('AUGMIS_RUNTIME_INSTANCE_ID','instanceId'),
    ):
        monkeypatch.setenv(environment, ids[claim])
    monkeypatch.setenv('AUGMIS_RUNTIME_ASSERTION_PUBLIC_KEY_FILE', str(public_file))

    application = FastAPI()
    @application.get('/health')
    def health():return {'status':'ok'}
    @application.get('/api/requests')
    def get_requests(): return {'status':'ok'}
    @application.post('/api/requests')
    async def create_request(payload:dict):return payload
    application.add_middleware(AugmisRuntimeGuard)

    def make_claims(*, method='GET', path='/api/requests', body=b'', query='', **overrides):
        now = int(time.time())
        data = dict(iss='augmis.control-plane', aud=f"augmis.runtime:{ids['instanceId']}",
                    sub=str(uuid.uuid4()), iat=now, nbf=now, exp=now+20,
                    jti=str(uuid.uuid4()), typ='augmis.runtime.crud.v1',
                    tenantId=ids['tenantId'],applicationId=ids['applicationId'],instanceId=ids['instanceId'],
                    method=method,path=path,
                    bodySha256=hashlib.sha256(body).hexdigest(),querySha256=hashlib.sha256(query.encode()).hexdigest(),
                    scope=['records.read' if method=='GET' else 'records.write'])
        data.update(overrides)
        return jwt.encode(data,private,algorithm='EdDSA',headers={'typ':'JWT'})

    return application, make_claims, ids


@pytest.mark.anyio
async def test_signed_unsigned_wrong_tenant_replay(configured):
    app, sign, ids=configured
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get('/health')).status_code == 200
        assert (await client.get('/api/requests')).status_code == 401
        token=sign()
        assert (await client.get('/api/requests',headers={'X-Augmis-Runtime-Assertion':token})).status_code == 200
        assert (await client.get('/api/requests',headers={'X-Augmis-Runtime-Assertion':token})).status_code == 401
        wrong=sign(tenantId=str(uuid.uuid4()))
        assert (await client.get('/api/requests',headers={'X-Augmis-Runtime-Assertion':wrong})).status_code == 403
        assert (await client.get('/api/not-declared',headers={'X-Augmis-Runtime-Assertion':sign(path='/api/not-declared')})).status_code == 404


@pytest.mark.anyio
async def test_body_method_query_scope_bindings(configured):
    app, sign, ids=configured
    body=b'{"title":"test"}'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        token=sign(method='POST',body=body)
        ok=await client.post('/api/requests',content=body,headers={'content-type':'application/json','X-Augmis-Runtime-Assertion':token})
        assert ok.status_code == 200 and ok.json() == {'title':'test'}
        bad=sign(method='POST',body=body)
        assert (await client.post('/api/requests',content=b'{}',headers={'content-type':'application/json','X-Augmis-Runtime-Assertion':bad})).status_code == 403
        wrong_path=sign(path='/api/other')
        assert (await client.get('/api/requests',headers={'X-Augmis-Runtime-Assertion':wrong_path})).status_code == 403
        wrong_scope=sign(scope=['records.write'])
        assert (await client.get('/api/requests',headers={'X-Augmis-Runtime-Assertion':wrong_scope})).status_code == 403
        bad_query=sign()
        assert (await client.get('/api/requests?x=1',headers={'X-Augmis-Runtime-Assertion':bad_query})).status_code == 403


def test_fails_closed_when_configuration_absent(monkeypatch):
    monkeypatch.delenv('AUGMIS_RUNTIME_ASSERTION_PUBLIC_KEY_FILE',raising=False)
    for key in ('APP_TENANT_ID','AUGMIS_RUNTIME_APPLICATION_ID','AUGMIS_RUNTIME_INSTANCE_ID'):
        monkeypatch.delenv(key,raising=False)
    with pytest.raises(RuntimeError,match='identity'):
        AugmisRuntimeGuard(FastAPI())


def test_generator_embeds_protected_wrapper_and_pinned_dependencies():
    """New AAPS drafts must carry their verifier in the exact hashed ZIP."""
    import io
    import json
    import zipfile
    from services.api.app.services.c1d5_aaps_generator import generate_aaps_zip
    entries = {
        'frontend/package.json': json.dumps({'scripts':{'build':'vite build'},
            'dependencies':{'react':'19.0.0','vite':'6.0.0'}}),
        'frontend/src/main.jsx': 'import React from "react"; console.log(React)',
        'frontend/index.html': '<div id="root"></div>',
        'app/main.py': 'from fastapi import FastAPI\napp=FastAPI()\n@app.get("/health")\ndef health(): return {"ok":True}\n',
        'requirements.txt': 'fastapi==0.115.12\nuvicorn==0.34.2\npsycopg[binary]==3.2.6\n',
        'gateway/routes.json': json.dumps([{'path':'/api/requests','methods':['GET','POST']}]),
        'db/aaps-schema.json': json.dumps({'tables':[{'name':'service_requests','columns':[
            {'name':'title','type':'text','maxLength':120}]}]}),
    }
    src = io.BytesIO()
    with zipfile.ZipFile(src,'w',zipfile.ZIP_DEFLATED) as out:
        for path,content in entries.items():out.writestr(path,content)
    def generate():
        return generate_aaps_zip(src.getvalue(),filename='app.zip',
            app_key='service-register-test',app_name='Service Register Test',version='1.0.2')
    first,meta = generate()
    second,_ = generate()
    assert first == second
    assert meta['artifactSha256'] == hashlib.sha256(first).hexdigest()
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert 'augmis_runtime_guard.py' in archive.namelist()
        wrapper = archive.read('augmis_generated_entry.py').decode()
        dockerfile = archive.read('Dockerfile').decode()
        assert 'app.add_middleware(AugmisRuntimeGuard)' in wrapper
        assert 'COPY augmis_runtime_guard.py' in dockerfile
        assert 'PyJWT==2.13.0' in dockerfile
        assert 'cryptography==46.0.4' in dockerfile
        assert archive.read('augmis_runtime_guard.py') == Path(
            __file__).resolve().parents[1].joinpath('services/api/app/services/c1d5_runtime_guard.py').read_bytes()
