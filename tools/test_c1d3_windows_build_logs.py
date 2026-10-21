"""Offline tests for Windows-safe Docker subprocess log decoding.

Does not invoke Docker or touch AUGMIS databases.
"""
from __future__ import annotations

import subprocess
import sys
import zipfile

import pytest

from services.api.app.services import build_engine as eng


def _test_archive(tmp_path):
    zpath = tmp_path / 'dummy.zip'
    with zipfile.ZipFile(zpath, 'w') as z:
        z.writestr('Dockerfile', 'FROM scratch\n')
    return zpath


def _call(tmp_path, monkeypatch, process_source, *, timeout_seconds=10):
    original_run = subprocess.run
    observed = {}

    def fake_docker(command, **kwargs):
        observed['command'] = command
        observed['kwargs'] = kwargs
        return original_run([sys.executable, '-c', process_source], **kwargs)

    monkeypatch.setattr(eng, 'docker_available', lambda: True)
    monkeypatch.setattr(eng.subprocess, 'run', fake_docker)
    payload = _test_archive(tmp_path)
    result = eng.build_docker_image(
        package_path=payload,
        manifest={'runtime': {'buildType': 'dockerfile', 'context': '.', 'dockerfile': 'Dockerfile'}},
        image_ref='augmis.local/tests/log-capture:1.0.0',
        timeout_seconds=timeout_seconds,
    )
    return result, observed


def test_success_captures_utf8_docker_output(tmp_path, monkeypatch):
    code = 'import sys;sys.stdout.buffer.write("Build success ☑".encode("utf-8"))'
    result, observed = _call(tmp_path, monkeypatch, code)
    assert result['status'] == 'ready'
    assert 'Build success ☑' in result['log']
    assert observed['kwargs']['encoding'] == 'utf-8'
    assert observed['kwargs']['errors'] == 'replace'
    assert observed['kwargs']['timeout'] == 10
    assert observed['command'][0] == 'docker'


def test_non_utf8_docker_output_never_erases_underlying_error(tmp_path, monkeypatch):
    code = ('import sys;'
            'sys.stdout.buffer.write(b"Build step 7 completed\\n");'
            'sys.stderr.buffer.write(b"ERROR: npm install failed\\n"+bytes([0x81,0xff]));'
            'sys.exit(17)')
    with pytest.raises(eng.BuildError) as err:
        _call(tmp_path, monkeypatch, code)
    message = str(err.value)
    assert 'Build step 7 completed' in message
    assert 'ERROR: npm install failed' in message
    assert '\ufffd' in message


def test_nonzero_exit_without_output_reports_code(tmp_path, monkeypatch):
    with pytest.raises(eng.BuildError, match='exit code 13'):
        _call(tmp_path, monkeypatch, 'import sys;sys.exit(13)')


def test_build_timeout_behavior_preserved(tmp_path, monkeypatch):
    with pytest.raises(eng.BuildError, match='Docker build timed out'):
        _call(tmp_path, monkeypatch, 'import time;time.sleep(2)', timeout_seconds=0.1)
