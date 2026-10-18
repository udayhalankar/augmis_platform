"""C1-D1 deterministic offline tests: no Docker, database or secrets created."""
from __future__ import annotations
import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import Mock
import pytest

from services.api.app.core import runtime_host as host
from services.api.app.services import runtime_host_readiness as readiness

ID='sha256:'+'a'*64
RELAY='sha256:'+'b'*64
CRUD='sha256:'+'c'*64
APP='d530406d-29f2-4def-b1ca-6d6c12a13299'


def profile(tmp_path):
    pri=tmp_path/'private.pem';pub=tmp_path/'public.pem'
    pri.write_text('placeholder');pub.write_text('placeholder')
    return {
        'schemaVersion':1, 'environment':'development',
        'postgresImageId':ID, 'genericRelayImageId':RELAY,
        'ingressNetwork':'augmis-crud-dev-ingress',
        'signingPrivateKeyFile':str(pri), 'signingPublicKeyFile':str(pub),
        'allowDevelopmentUnquotedVolumes':True,'enableLegacyCrud':False,
    }


def test_reads_profile(tmp_path):
    p=tmp_path/'host.json';p.write_text(json.dumps(profile(tmp_path)))
    out=host.read_profile(p)
    assert out.environment['AUGMIS_C1C_GENERIC_RUNTIME_ENABLED']=='1'
    assert out.environment['AUGMIS_C1B_POSTGRES_IMAGE_ID']==ID


def test_absent_does_not_implicitly_enable(tmp_path):
    assert host.read_profile(tmp_path/'missing.json') is None


@pytest.mark.parametrize('field,value',[
    ('schemaVersion',2),('schemaVersion',True),('environment','production'),
    ('postgresImageId','postgres:15-alpine'),('genericRelayImageId','oops'),
    ('ingressNetwork','host'),('ingressNetwork','a'*64),
    ('allowDevelopmentUnquotedVolumes',False),('enableLegacyCrud','yes'),
])
def test_rejects_invalid_profile_fields(tmp_path,field,value):
    p=profile(tmp_path);p[field]=value
    with pytest.raises(host.RuntimeProfileError): host._parse(p)


def test_reject_unknown_keys(tmp_path):
    p=profile(tmp_path);p['ignoreUnknownSecurityOption']=True
    with pytest.raises(host.RuntimeProfileError):host._parse(p)


def test_canonical_crud_id_and_image_required(tmp_path):
    p=profile(tmp_path);p['enableLegacyCrud']=True;p['legacyCrudApplicationId']=APP
    with pytest.raises(host.RuntimeProfileError):host._parse(p)
    p['legacyCrudRelayImageId']=CRUD
    assert host._parse(p)['AUGMIS_C1B_CRUD_PRIVATE_RUNTIME_ENABLED']=='1'


def test_profile_conflicting_environment_is_rejected(tmp_path,monkeypatch):
    p=tmp_path/'host.json';p.write_text(json.dumps(profile(tmp_path)))
    monkeypatch.setattr(host,'default_profile_path',lambda:p)
    monkeypatch.setenv('AUGMIS_C1C_GENERIC_RUNTIME_ENABLED','0')
    with pytest.raises(host.RuntimeProfileError,match='C1D_PROFILE_ENV_CONFLICT'):
        host.hydrate_runtime_profile()


def test_profile_is_loaded_from_fresh_environment(tmp_path,monkeypatch):
    p=tmp_path/'host.json';p.write_text(json.dumps(profile(tmp_path)))
    monkeypatch.setattr(host,'default_profile_path',lambda:p)
    for k in host._parse(profile(tmp_path)):
        monkeypatch.delenv(k, raising=False)
    loaded=host.hydrate_runtime_profile()
    assert loaded and os.environ['AUGMIS_C1C_DECLARED_SCHEMA_ENABLED']=='1'
    monkeypatch.setattr(host,'_LOADED',None)


def test_host_readiness_unconfigured(monkeypatch):
    monkeypatch.setattr(readiness,'active_profile',lambda:None)
    assert readiness.check_runtime_host().code=='C1D_PROFILE_NOT_CONFIGURED'


def test_host_readiness_ok_and_drift(tmp_path,monkeypatch):
    data=profile(tmp_path);mapping=host._parse(data)
    loaded=host.LoadedProfile(tmp_path/'test.json',mapping)
    monkeypatch.setattr(readiness,'active_profile',lambda:loaded)
    monkeypatch.setattr(readiness.settings,'app_env','development')
    for k,v in mapping.items(): monkeypatch.setenv(k,v)
    # Prevent filesystem/cryptography from being used in the mocked readiness test.
    monkeypatch.setitem(sys.modules, "services.api.app.services.private_crud_runtime",
                        types.SimpleNamespace(signing_material=lambda:(Path('private'),Path('public'))))
    def docker(*args):
        if args[0]=='info':return '29.2.1'
        if args[0]=='image' and args[2]=='--format':
            if args[3]=='{{.Id}}':return args[4]
            if args[3]=='{{.Config.User}}':return '10002:10002'
        if args[0]=='network' and args[3]=='{{.Internal}}':return 'false'
        if args[0]=='network' and args[3]=='{{.Driver}}':return 'bridge'
        raise AssertionError(args)
    monkeypatch.setattr(readiness,'_docker',docker)
    assert readiness.check_runtime_host().ready
    monkeypatch.setenv('AUGMIS_C1C_GENERIC_RUNTIME_ENABLED','0')
    assert readiness.check_runtime_host().code=='C1D_RUNTIME_ENV_DRIFT'


def test_runtime_absent_docker_is_fail_closed(tmp_path,monkeypatch):
    data=host._parse(profile(tmp_path))
    monkeypatch.setattr(readiness,'active_profile',lambda:host.LoadedProfile(tmp_path/'host.json',data))
    monkeypatch.setattr(readiness.settings,'app_env','development')
    for k,v in data.items():monkeypatch.setenv(k,v)
    monkeypatch.setitem(sys.modules, "services.api.app.services.private_crud_runtime",
                        types.SimpleNamespace(signing_material=lambda:None))
    monkeypatch.setattr(readiness,'_docker',lambda *args: (_ for _ in ()).throw(RuntimeError('C1D_DOCKER_UNAVAILABLE')))
    assert readiness.check_runtime_host().code=='C1D_DOCKER_UNAVAILABLE'
    with pytest.raises(host.RuntimeProfileError):readiness.require_generic_host_ready()


def test_fresh_python_process_loads_profile_without_shell_flags(tmp_path):
    """Fresh interpreter: no inherited AUGMIS_C1* settings, no runtime initialization command."""
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    directory = tmp_path / '.augmis'
    directory.mkdir()
    doc = profile(tmp_path)
    dest = directory / 'runtime-host.json'
    dest.write_text(json.dumps(doc),encoding='utf-8')
    env = {k: v for k,v in os.environ.items() if not k.startswith('AUGMIS_C1') and k != 'AUGMIS_RUNTIME_PROFILE_FILE'}
    env.update({'AUGMIS_RUNTIME_PROFILE_FILE':str(dest),
                'DATABASE_URL':'postgresql://dummy:dummy@localhost:5432/dummy',
                'JWT_SECRET':'dummy-test-key-not-for-use',
                'PYTHONPATH':str(root)})
    cmd=[sys.executable,'-c',
         "import os; from services.api.app.core.config import settings; print(os.environ.get('AUGMIS_C1C_GENERIC_RUNTIME_ENABLED')); print(os.environ.get('AUGMIS_C1C_GENERIC_RELAY_IMAGE_ID'))"]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-2:] == ['1',RELAY]


def test_profile_does_not_embed_signing_key_material(tmp_path):
    data=profile(tmp_path)
    text=json.dumps(data)
    assert 'BEGIN PRIVATE KEY' not in text
    assert json.loads(text)['signingPrivateKeyFile'] == data['signingPrivateKeyFile']


def test_permission_guard_on_unix(tmp_path):
    if os.name == 'nt':
        pytest.skip('Windows uses ACLs, not POSIX mode bits')
    p=tmp_path/'host.json';p.write_text(json.dumps(profile(tmp_path)))
    p.chmod(0o666)
    with pytest.raises(host.RuntimeProfileError,match='WRITABLE_BY_OTHERS'):
        host.read_profile(p)


def test_explicit_override_missing_must_not_fall_back(tmp_path,monkeypatch):
    monkeypatch.setenv(host.PROFILE_OVERRIDE_ENV,str(tmp_path/'not-there.json'))
    with pytest.raises(host.RuntimeProfileError,match='C1D_PROFILE_NOT_FOUND'):
        host.read_profile()
