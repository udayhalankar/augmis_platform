"""R08 regression for role-aware, isolated restoration of tenant RLS policies.

No Docker daemon, PostgreSQL server, database, or secrets are used by these tests.
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import types
import uuid
from types import SimpleNamespace

import pytest

from tools import r08_backup_restore as r08


ID = uuid.UUID('03821732-84fd-4ca6-92ce-e6db0c5a6f67')
ROLE = f'augmis_rw_{ID.hex}'


def fake_role_module(monkeypatch):
    # The installed source imports the existing AUGMIS C1-B2 canonical helper.
    mod = types.ModuleType('services.api.app.services.application_database_credentials')
    mod.runtime_role = lambda identity: f'augmis_rw_{identity.hex}'
    monkeypatch.setitem(sys.modules, mod.__name__, mod)


def test_authenticated_instance_id_generates_canonical_role(monkeypatch):
    fake_role_module(monkeypatch)
    assert r08._isolated_restore_role({'scope': 'application', 'instance_id': str(ID)}) == ROLE
    assert r08._isolated_restore_role({'scope': 'platform'}) is None


@pytest.mark.parametrize('bad_id', [None, '', 'not-a-uuid', 'xyz; DROP ROLE postgres;', str(ID).upper(), ID, '{'+str(ID)+'}'])
def test_reject_untrusted_or_noncanonical_identity(monkeypatch, bad_id):
    fake_role_module(monkeypatch)
    with pytest.raises(r08.R08Error, match='R08_RESTORE_INSTANCE_ID'):
        r08._isolated_restore_role({'scope': 'application', 'instance_id': bad_id})


def test_reject_unsupported_scope(monkeypatch):
    fake_role_module(monkeypatch)
    with pytest.raises(r08.R08Error, match='R08_RESTORE_SCOPE_INVALID'):
        r08._isolated_restore_role({'scope': 'unexpected', 'instance_id': str(ID)})


def test_reject_noncanonical_role_from_source(monkeypatch):
    mod = types.ModuleType('services.api.app.services.application_database_credentials')
    mod.runtime_role = lambda _: 'postgres;DROP DATABASE postgres'
    monkeypatch.setitem(sys.modules, mod.__name__, mod)
    with pytest.raises(r08.R08Error, match='R08_RESTORE_RUNTIME_ROLE_INVALID'):
        r08._isolated_restore_role({'scope': 'application', 'instance_id': str(ID)})


def test_restore_role_is_safe_and_precedes_pg_restore():
    script = r08.RESTORE_SCRIPT
    assert "CREATE ROLE ${R08_PROBE_RUNTIME_ROLE} WITH NOLOGIN NOINHERIT NOSUPERUSER" in script
    assert 'NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS' in script
    assert "grep -Eq '^augmis_rw_[0-9a-f]{32}$'" in script
    assert script.index('CREATE ROLE ${R08_PROBE_RUNTIME_ROLE}') < script.index('pg_restore --exit-on-error')
    assert script.index('R08_STAGE=restore_role_ready') < script.index('pg_restore --exit-on-error')
    assert 'DROP POLICY' not in script
    assert 'DISABLE ROW LEVEL SECURITY' not in script
    assert 'R08_RESTORE_ROLE_SAFE=' in script
    assert 'R08_RESTORED_RLS_POLICIES=' in script
    assert '--no-owner --no-acl' in script
    assert 'unix_socket_directories=/tmp' in script
    assert 'listen_addresses=' in script
    assert 'PGHOST=/tmp' in script


def test_restore_script_posix_shell_syntax():
    """Check shell syntax where sh exists; restore-probe runs the script in Linux.

    Windows development hosts may have no POSIX shell. Do not skip any of
    the role/RLS/security assertions in the separate structural test above.
    """
    import shutil

    shell = shutil.which('sh')
    if shell is None:
        pytest.skip('POSIX sh is unavailable on this host; Linux restore-probe remains mandatory')

    result = subprocess.run([shell, '-n'], input=r08.RESTORE_SCRIPT, text=True,
                            capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_temporary_container_receives_only_trusted_role(monkeypatch, tmp_path):
    fake_role_module(monkeypatch)
    pwd = 'isolated test passphrase 0123456789'
    image = 'sha256:'+'a'*64
    meta = {'scope':'application', 'instance_id':str(ID), 'created_utc':'2026-10-28T00:00:00+00:00',
            'postgres_image':image, 'schema':'augmis.r08.backup.v1'}
    from io import BytesIO
    archive = tmp_path/'fixture.r08'
    r08.seal_stream(BytesIO(b'PGDMP'+b'synthetic only'*100),archive,pwd,meta)
    monkeypatch.setattr(r08,'_dev_db',lambda:None)
    monkeypatch.setattr(r08,'_password',lambda: pwd)
    state = {'labels': None, 'cmd': None, 'removed': False}
    def fake_run(args, *, input_data=None):
        if args[:3] == ['docker', 'image', 'inspect']:
            return image
        if args[:3] == ['docker', 'volume', 'create']:
            labels = [args[i + 1].split('=', 1) for i, x in enumerate(args) if x == '--label']
            state['labels'] = dict(labels)
            state['volume'] = args[-1]
            return state['volume']
        if args[:3] == ['docker', 'volume', 'inspect']:
            return json.dumps([{'Labels': state['labels']}])
        if args[:3] == ['docker', 'volume', 'rm']:
            assert args[-1] == state['volume']
            state['removed'] = True
            return args[-1]
        raise AssertionError('Unexpected Docker operation '+repr(args))
    monkeypatch.setattr(r08,'_run',fake_run)

    class FakeProcess:
        def __init__(self, cmd, **kwargs):
            state['cmd'] = cmd
            assert kwargs['stderr'] == subprocess.DEVNULL
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO(b'R08_STAGE=initdb_ready\nR08_STAGE=postgres_started\n'
                                      b'R08_STAGE=restore_role_ready\nR08_STAGE=pg_restore_completed\n'
                                      b'R08_RESTORE_ROLE_SAFE=1\nR08_RESTORED_RLS_POLICIES=5\n'
                                      b'R08_RESTORED_TABLES=2\n')
        def wait(self, timeout=None):
            return 0
        def poll(self):
            return 0
        def kill(self):
            raise AssertionError('Unexpected kill')
    monkeypatch.setattr(r08.subprocess,'Popen',FakeProcess)
    r08._restore_probe(SimpleNamespace(execute=True,confirm_isolated=True,
                                      archive=str(archive),postgres_image=None))
    cmd=state['cmd']
    assert '--network' in cmd and cmd[cmd.index('--network')+1] == 'none'
    assert '--read-only' in cmd and '--cap-drop' in cmd
    assert 'R08_PROBE_RUNTIME_ROLE='+ROLE in cmd
    assert '--entrypoint' in cmd and '/bin/sh' in cmd
    assert state['removed'] is True
    assert archive.is_file()
