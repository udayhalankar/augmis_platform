"""B1A standalone unit checks for log archival and platform resource limits.

No Docker daemon or database required.
"""
from __future__ import annotations
import os
from types import SimpleNamespace
from unittest.mock import patch
from services.api.app.services import deployment_engine as engine
from services.api.app.services import runtime_log_archive as archives


def fresh():
    return SimpleNamespace(container_name="augmis-test", archived_logs=None,
                           archived_logs_at=None, archived_logs_truncated=False,
                           archived_logs_error=None)


def check():
    text, truncated = archives._bounded("α" * (archives.MAX_ARCHIVE_BYTES + 50) + "\nfinal-line")
    assert truncated and len(text.encode("utf8")) <= archives.MAX_ARCHIVE_BYTES
    assert text.endswith("final-line")

    dep = fresh()
    with patch.object(archives, "get_container_logs", return_value="line-one\nline-two\nline-three"):
        assert archives.archive_before_removal(dep)
    assert dep.archived_logs_at is not None
    assert archives.archived_tail(dep, 2) == "line-two\nline-three"

    # Retried stop after a failed earlier removal must refresh its snapshot.
    dep.status = "running"
    with patch.object(archives, "get_container_logs", return_value="newer-line"):
        assert archives.archive_before_removal(dep)
    assert dep.archived_logs == "newer-line"

    dep = fresh()
    with patch.object(archives, "get_container_logs", side_effect=engine.DeploymentError("missing")):
        assert not archives.archive_before_removal(dep)
    assert dep.archived_logs_error == "docker_logs_unavailable"

    dep = fresh()
    archives.archive_failed_start(dep, engine.DeploymentError("health", log_snapshot="boot error"))
    assert dep.archived_logs == "boot error"

    with patch.dict(os.environ, {
        "AUGMIS_RUNTIME_MEMORY_MB": "768",
        "AUGMIS_RUNTIME_CPUS": "1.5",
        "AUGMIS_RUNTIME_PIDS": "128",
    }):
        assert engine.runtime_resource_limits() == ("768m", "1.5", "128")
        commands = []
        def fake(command, timeout=120):
            commands.append(command)
            if command[1] == "port":
                return "127.0.0.1:49152"
            return "test-container-id"
        with patch.object(engine, "run_docker", side_effect=fake), patch.object(engine, "wait_for_health"):
            engine.start_container("sample:1", {"services": {"web": {"public": True, "port": 8080}}}, "augmis-test", {"augmis.managed": "true"})
        run = commands[0]
        assert run[run.index("--memory")+1] == "768m"
        assert run[run.index("--cpus")+1] == "1.5"
        assert run[run.index("--pids-limit")+1] == "128"
        assert "-p" in run and run[run.index("-p")+1] == "127.0.0.1::8080"


    # Health failure snapshots logs before Docker rm and preserves failure details.
    calls = []
    def fake_fail_docker(command, timeout=120):
        calls.append(command)
        return "127.0.0.1:49152" if command[1] == "port" else "test-id"
    with patch.object(engine, "run_docker", side_effect=fake_fail_docker), \
         patch.object(engine, "wait_for_health", side_effect=engine.DeploymentError("unhealthy")), \
         patch.object(engine, "get_container_logs", return_value="boot trace"):
        try:
            engine.start_container("sample:1", {"services": {"web": {"public": True, "port": 8080}}}, "augmis-test", {})
            raise AssertionError("Expected startup failure")
        except engine.DeploymentError as exc:
            assert exc.log_snapshot == "boot trace"
    assert any(c[1:3] == ["rm", "-f"] for c in calls)

    with patch.dict(os.environ, {"AUGMIS_RUNTIME_MEMORY_MB": "0"}):
        try:
            engine.runtime_resource_limits()
            raise AssertionError("Expected invalid limits to fail closed")
        except engine.DeploymentError:
            pass

    print("[PASS] bounded log snapshots, failed-start logs, archived tail")
    print("[PASS] platform-owned Docker memory/CPU/PID limits and loopback binding")
    print("[PASS] invalid limits rejected")


if __name__ == "__main__":
    check()
