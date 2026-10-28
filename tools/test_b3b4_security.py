"""B3+B4 baseline security checks; no live Redis/PostgreSQL needed."""
import os
import json
import uuid
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock
import pytest
from tools.techtango_export_contract import ExportContractError,validated_snapshot
from services.api.app.services.shared_runtime_sessions import RedisSessionMap, _LUA_CONSUME


def test_redis_stores_uuid_strings_and_restores_types():
    data={}
    def put(key,payload,ex):
        assert ex > 0
        data[key] = payload
    client=Mock()
    client.set.side_effect=put
    client.get.side_effect=lambda key:data.get(key)
    store=RedisSessionMap(client,'container')
    user_id=uuid.uuid4()
    store['a']={'user_id':user_id,'expires_at':time.time()+100,'ticket_used':False}
    assert store['a']['user_id']==user_id
    assert store['a']['ticket_used'] is False
    assert store.get('missing') is None


def test_redis_ticket_swap_is_atomic_in_script():
    assert "redis.call('GET'" in _LUA_CONSUME
    assert "ticket_used" in _LUA_CONSUME
    assert "'KEEPTTL'" in _LUA_CONSUME
    client=Mock()
    client.eval.return_value=1
    store=RedisSessionMap(client,'static')
    assert store.consume_ticket('safe_id',expected_hash='a'*64,now=10,new_session_hash='b'*64)
    assert client.eval.call_args.args[-1]=='static'
    with pytest.raises(ValueError):
        store.consume_ticket('../escape',expected_hash='a',now=10)


def test_snapshot_only_includes_whitelisted_metadata():
    app={'status':'Published','tenant_id':17,'app_slug':'assets_manager',
         'app_name':'Assets Manager','schema_json':{'fields':[{'name':'serial_no','type':'text','label':'Serial'}],
         'sql':'DROP TABLE','private_token':'never-export'},'records':['PRIVATE']}
    result=validated_snapshot(app)
    serialized=json.dumps(result)
    assert 'PRIVATE' not in serialized and 'DROP TABLE' not in serialized
    assert 'private_token' not in serialized
    assert result['sourceTenantId']==17
    assert len(result['sha256'])==64


def test_snapshot_blocks_unpublished_or_invalid_identity():
    with pytest.raises(ExportContractError):
        validated_snapshot({'status':'draft','tenant_id':1})
    with pytest.raises(ExportContractError):
        validated_snapshot({'status':'Published','tenant_id':'1','app_slug':'a','app_name':'A','schema_json':{}})


def test_production_launch_fail_closed():
    root=Path(__file__).resolve().parents[1]
    env={**os.environ,'PYTHONPATH':str(root),'APP_ENV':'production',
         'AUGMIS_SESSION_STORE':'redis','DATABASE_URL':'postgresql+psycopg://fake:fake@localhost/fake',
         'JWT_SECRET':'sufficiently-long-test-not-real-secret'}
    script='from services.api.app.services.security_release_gate import require_safe_runtime_exposure; require_safe_runtime_exposure()'
    r=subprocess.run([sys.executable,'-c',script],env=env,capture_output=True,text=True)
    assert r.returncode!=0
    # R05 rejects inline production JWT material before the older B3 exposure
    # gate can execute. This is the intended fail-closed ordering, not a launch.
    assert 'RuntimeError: R05_PRODUCTION_INLINE_SECRET_DENIED' in r.stderr
    assert 'sufficiently-long-test-not-real-secret' not in r.stderr


def test_production_gate_requires_shared_redis_after_config_validation(monkeypatch):
    # Exercise B3 independently, after simulating successful configuration
    # validation, so the earlier R05 secret-file guard cannot mask this gate.
    from types import SimpleNamespace
    from services.api.app.services import security_release_gate as gate
    monkeypatch.setattr(gate, 'settings', SimpleNamespace(app_env='production'))
    monkeypatch.delenv('AUGMIS_SESSION_STORE', raising=False)
    with pytest.raises(RuntimeError, match='^Production requires shared Redis runtime sessions$'):
        gate.require_safe_runtime_exposure()


def test_production_gate_rejects_unsafe_runtime_exposure(monkeypatch):
    from types import SimpleNamespace
    from services.api.app.services import security_release_gate as gate
    monkeypatch.setattr(gate, 'settings', SimpleNamespace(app_env='production'))
    monkeypatch.setenv('AUGMIS_SESSION_STORE', 'redis')
    with pytest.raises(RuntimeError, match='^Production launch blocked:'):
        gate.require_safe_runtime_exposure()
