"""R08 restore-probe socket contract and secret-safe failure diagnostics.

Offline regression tests; never access Docker, a real database or backup secrets.
"""
from __future__ import annotations
import re
from tools import r08_backup_restore as r08


def test_isolated_postgres_socket_matches_clients():
    script = r08.RESTORE_SCRIPT
    assert "--network" not in script  # networking is restricted by Docker invocation
    assert "listen_addresses=''" in script
    assert "unix_socket_directories=/tmp" in script
    assert "export PGHOST=/tmp" in script
    assert re.search(r"pg_restore\b[^\n]*-h /tmp\b", script)
    assert re.search(r"psql\b[^\n]*-h /tmp\b", script)
    assert "--auth-host=reject" in script


def test_stage_markers_only_after_successful_commands():
    s = r08.RESTORE_SCRIPT
    for command, marker in (("initdb -D", 'R08_STAGE=initdb_ready'),
                            ("pg_ctl -D", 'R08_STAGE=postgres_started'),
                            ("pg_restore --exit-on-error", 'R08_STAGE=pg_restore_completed')):
        assert command in s and marker in s
        assert s.index(marker) > s.index(command)
    assert 'R08_RESTORED_TABLES=' in s


def test_restore_security_flags_preserved():
    import inspect
    source = inspect.getsource(r08._restore_probe)
    for flag in ('"--network", "none"', '"--read-only"', '"--user", "postgres"',
                 '"--cap-drop", "ALL"', '"--security-opt", "no-new-privileges:true"',
                 '"--confirm-isolated"'):
        if flag == '"--confirm-isolated"':
            assert 'args.confirm_isolated' in source
        else:
            assert flag in source
    assert 'R08_RESTORE_LAST_STAGE=' in source
    assert 'stderr=subprocess.DEVNULL' in source
    assert 'docker", "volume", "rm"' in source
