"""B1A: bounded historical runtime logs, never a substitute for external log retention.

Logs may contain application data; only retrieve through the authorized Operations API.
"""
from __future__ import annotations
from datetime import datetime, timezone
from services.api.app.services.deployment_engine import DeploymentError, get_container_logs

MAX_ARCHIVE_BYTES = 256 * 1024
MAX_ARCHIVE_LINES = 2000


def _bounded(text: str) -> tuple[str, bool]:
    data = text.encode("utf-8", errors="replace")
    truncated = len(data) > MAX_ARCHIVE_BYTES
    if truncated:
        data = data[-MAX_ARCHIVE_BYTES:]
        # Trim the partial first line/UTF-8 character when possible.
        data = data.decode("utf-8", errors="ignore").encode("utf-8")
        newline = data.find(b"\n")
        if newline >= 0:
            data = data[newline + 1:]
    return data.decode("utf-8", errors="replace"), truncated


def _store(deployment, text: str) -> None:
    deployment.archived_logs, deployment.archived_logs_truncated = _bounded(text)
    deployment.archived_logs_at = datetime.now(timezone.utc)
    deployment.archived_logs_error = None


def archive_before_removal(deployment) -> bool:
    """Snapshot logs before docker rm; idempotent. Does not commit the DB."""
    if deployment.archived_logs_at is not None and getattr(deployment, 'status', None) != 'running':
        return True
    if not deployment.container_name:
        deployment.archived_logs_error = "container_reference_missing"
        return False
    try:
        output = get_container_logs(container_name=deployment.container_name, tail=MAX_ARCHIVE_LINES)
    except DeploymentError:
        # Do not persist raw Docker errors: they can include sensitive paths.
        deployment.archived_logs_error = "docker_logs_unavailable"
        return False
    _store(deployment, output)
    return True


def archive_failed_start(deployment, error: DeploymentError) -> None:
    """The start engine captured logs before removing an unhealthy candidate."""
    if error.log_snapshot is not None:
        _store(deployment, error.log_snapshot)
    else:
        deployment.archived_logs_error = "failed_start_logs_unavailable"


def archived_tail(deployment, tail: int) -> str:
    text = deployment.archived_logs or ""
    return "\n".join(text.splitlines()[-max(1, min(tail, MAX_ARCHIVE_LINES)):])
