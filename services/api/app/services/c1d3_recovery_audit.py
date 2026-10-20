"""C1-D3 non-destructive deployment recovery audit.

Inspect application/deployment/journal consistency against Docker *by exact
container name*, validating immutable AUGMIS ownership labels before reporting.
No automatic restart/removal/DB migration is allowed here. Never log raw Docker
inspect results; Docker inspect includes container environment and secret paths.
"""
from __future__ import annotations

import json
import re
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.models.platform import ApplicationDeployment, ApplicationInstance
from services.api.app.models.deployment_reliability import DeploymentOperationJournal

_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,199}\Z")


class DockerInspectionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class DockerState:
    state: str  # running, exited, paused, missing, unknown
    labels: dict[str, str]
    id: str | None = None


def inspect_exact_container(name: str) -> DockerState:
    """Read only, no shell and no raw inspect output in logs/responses."""
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise DockerInspectionError("C1D3_CONTAINER_NAME_INVALID")
    try:
        proc = subprocess.run(
            ["docker", "container", "inspect", name],
            check=False, capture_output=True, text=True, timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DockerInspectionError("C1D3_DOCKER_UNAVAILABLE") from exc
    if proc.returncode:
        # Inspect failure is ambiguous: missing object or unavailable daemon.
        # Check daemon separately before reporting an object as missing.
        try:
            daemon = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                                    check=False, capture_output=True, text=True, timeout=6)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DockerInspectionError("C1D3_DOCKER_UNAVAILABLE") from exc
        if daemon.returncode != 0:
            raise DockerInspectionError("C1D3_DOCKER_UNAVAILABLE")
        # Never infer 'missing' solely from a nonzero inspect exit: errors
        # other than not-found can occur. Only explicitly detected not-found.
        text = (proc.stderr + proc.stdout).lower()
        if "no such object" in text or "no such container" in text:
            return DockerState(state="missing", labels={})
        raise DockerInspectionError("C1D3_INSPECT_FAILED")
    try:
        documents = json.loads(proc.stdout)
        if not isinstance(documents, list) or len(documents) != 1:
            raise ValueError("invalid inspect shape")
        item = documents[0]
        if item.get("Name", "").lstrip("/") != name:
            raise ValueError("container name mismatch")
        labels = item["Config"]["Labels"] or {}
        state = item["State"]
        if not isinstance(labels, dict) or not isinstance(state, dict):
            raise ValueError("invalid metadata")
        status = str(state.get("Status", "unknown"))
        return DockerState(state=status, labels=labels, id=str(item.get("Id") or ""))
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise DockerInspectionError("C1D3_INSPECT_INVALID") from exc


def classify_deployment(*, instance: ApplicationInstance,
                        deployment: ApplicationDeployment,
                        journal: DeploymentOperationJournal | None,
                        state: DockerState | None = None,
                        inspect_error: str | None = None) -> dict[str, Any]:
    """Pure classification, no state transitions and no privileges granted."""
    if deployment.instance_id != instance.id:
        raise ValueError("C1D3_DEPLOYMENT_INSTANCE_MISMATCH")
    if journal and (journal.deployment_id != deployment.id
                    or journal.instance_id != instance.id
                    or journal.tenant_id != instance.tenant_id):
        return _result(instance, deployment, journal, "OWNERSHIP_CONFLICT", "STOP_SECURITY_REVIEW")
    if inspect_error:
        return _result(instance, deployment, journal, inspect_error, "RECHECK_DOCKER_HOST")
    if state is None:
        return _result(instance, deployment, journal, "NOT_INSPECTED", "INSPECT_BEFORE_ACTION")
    # Report expired leases even before an operator explicitly quarantines
    # metadata; a live container may be the result of a partially committed
    # operation and must not be automatically adopted as active.
    if journal and journal.state == 'running' and journal.lease_until is not None:
        expiration = journal.lease_until
        if expiration.tzinfo is None:
            expiration = expiration.replace(tzinfo=timezone.utc)
        if expiration <= datetime.now(timezone.utc):
            return _result(instance, deployment, journal, 'LEASE_EXPIRED_RECONCILE', 'OPERATOR_RECONCILE')
    if state.state == "missing":
        if deployment.status in {"deploying", "running"}:
            return _result(instance, deployment, journal, "CONTAINER_MISSING", "RECONCILE_DEPLOYMENT")
        return _result(instance, deployment, journal, "HISTORICAL_CONTAINER_MISSING", "NO_ACTION")
    labels = state.labels
    expected = {"augmis.managed": "true",
                "augmis.instance_id": str(instance.id),
                "augmis.tenant_id": str(instance.tenant_id),
                "augmis.application_id": str(instance.application_id)}
    if any(labels.get(key) != value for key, value in expected.items()):
        return _result(instance, deployment, journal, "OWNERSHIP_LABEL_MISMATCH", "STOP_SECURITY_REVIEW")
    # A healthy Docker process is NOT proof that HTTP, signed gateway and DB
    # are healthy. Never auto-promote the deployment based on container state.
    if deployment.status == "running" and state.state == "running":
        if journal and journal.state == "needs_reconciliation":
            return _result(instance, deployment, journal, "RUNNING_NEEDS_VERIFICATION", "VERIFY_HEALTH_AND_GATEWAY")
        return _result(instance, deployment, journal, "RUNTIME_PRESENT", "NO_ACTION")
    if state.state == "running" and deployment.status in {"failed", "deploying"}:
        return _result(instance, deployment, journal, "RUNNING_WITH_INCOMPLETE_METADATA", "OPERATOR_RECONCILE")
    if deployment.status == "running":
        return _result(instance, deployment, journal, "RUNTIME_NOT_RUNNING", "OPERATOR_RECONCILE")
    if journal and journal.state == "needs_reconciliation":
        return _result(instance, deployment, journal, "QUARANTINED_OPERATION", "OPERATOR_RECONCILE")
    return _result(instance, deployment, journal, "HISTORICAL_DEPLOYMENT", "NO_ACTION")


def _result(instance, deployment, journal, code: str, action: str):
    # Deliberately omit runtime URL, raw error strings, Docker environment,
    # database credentials, and all container inspect details.
    return {"tenantId": str(instance.tenant_id),
            "instanceId": str(instance.id), "deploymentId": str(deployment.id),
            "deploymentStatus": deployment.status,
            "journalState": journal.state if journal else "not_journaled",
            "journalStage": journal.stage if journal else None,
            "code": code, "nextAction": action}


def inventory(db: Session, *, tenant_id: uuid.UUID | None = None,
              limit: int = 100, include_healthy: bool = False,
              docker_inspector: Callable[[str], DockerState] = inspect_exact_container,
              inspect_docker: bool = True) -> list[dict[str, Any]]:
    """Read-only inventory including legacy unjournaled deployments."""
    if not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("C1D3_LIMIT_INVALID")
    query = (select(ApplicationDeployment, ApplicationInstance, DeploymentOperationJournal)
             .join(ApplicationInstance, ApplicationDeployment.instance_id == ApplicationInstance.id)
             .outerjoin(DeploymentOperationJournal, DeploymentOperationJournal.deployment_id == ApplicationDeployment.id)
             .order_by(ApplicationDeployment.created_at.desc()).limit(limit))
    if tenant_id is not None:
        query = query.where(ApplicationInstance.tenant_id == tenant_id)
    result = []
    for deployment, instance, journal in db.execute(query):
        if not include_healthy and deployment.status not in {"deploying", "failed", "running"} and not (journal and journal.state == "needs_reconciliation"):
            continue
        name = deployment.container_name
        state, error = None, None
        if inspect_docker and name:
            try:
                state = docker_inspector(name)
            except DockerInspectionError as exc:
                error = exc.code
        row = classify_deployment(instance=instance, deployment=deployment,
                                  journal=journal, state=state, inspect_error=error)
        if (include_healthy or row["code"] != "RUNTIME_PRESENT" or
                (journal and journal.state == "needs_reconciliation")):
            result.append(row)
    return result
