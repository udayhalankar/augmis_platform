"""Read-only runtime reconciliation inventory. NEVER stops/starts containers or mutates DB.

Run from repository root: python -m tools.b1_runtime_recovery_report --with-docker
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import subprocess
from sqlalchemy import select
from services.api.app.db.session import SessionLocal
from services.api.app.models.platform import ApplicationInstance, ApplicationDeployment

REVIEW_STATUSES = ("deploying", "stopping")
INSTANCE_REVIEW = ("provisioning", "upgrading", "stopping")


def inspect_docker(deployment, instance) -> dict:
    if not deployment.container_name:
        return {"found": False, "reason": "container_name_missing"}
    try:
        proc = subprocess.run(
            ["docker", "inspect", "--format", "{{json .State}}|{{json .Config.Labels}}", deployment.container_name],
            capture_output=True, text=True, timeout=8, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"found": None, "reason": "docker_unavailable"}
    if proc.returncode != 0:
        return {"found": False, "reason": "docker_container_not_found"}
    try:
        state_text, labels_text = proc.stdout.strip().split("|", 1)
        state, labels = json.loads(state_text), json.loads(labels_text)
    except (ValueError, TypeError):
        return {"found": None, "reason": "docker_inspect_unparseable"}
    matches = bool(
        labels and labels.get("augmis.managed") == "true"
        and labels.get("augmis.instance_id") == str(instance.id)
        and labels.get("augmis.tenant_id") == str(instance.tenant_id)
    )
    return {"found": True, "running": bool(state.get("Running")), "labelMatch": matches}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-docker", action="store_true", help="Read Docker metadata; no modifications")
    parser.add_argument("--stale-minutes", type=int, default=10)
    args = parser.parse_args()
    if args.stale_minutes < 1:
        parser.error("stale-minutes must be positive")

    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(minutes=args.stale_minutes)
    records = []
    with SessionLocal() as db:
        rows = db.execute(
            select(ApplicationDeployment, ApplicationInstance)
            .join(ApplicationInstance, ApplicationInstance.id == ApplicationDeployment.instance_id)
            .where((ApplicationDeployment.status.in_(REVIEW_STATUSES)) |
                   (ApplicationInstance.status.in_(INSTANCE_REVIEW)))
            .order_by(ApplicationDeployment.created_at)
        ).all()
        for dep, instance in rows:
            creation = dep.created_at
            if creation is not None and creation.tzinfo is None:
                creation = creation.replace(tzinfo=timezone.utc)
            stale = creation is not None and creation < stale_before
            result = {
                "instanceId": str(instance.id),
                "tenantId": str(instance.tenant_id),
                "deploymentId": str(dep.id),
                "instanceStatus": instance.status,
                "deploymentStatus": dep.status,
                "containerName": dep.container_name,
                "candidateRecorded": bool(dep.container_id and dep.runtime_url),
                "olderThanThreshold": bool(stale),
                "manualReviewNeeded": bool(stale),
            }
            if args.with_docker:
                result["docker"] = inspect_docker(dep, instance)
            records.append(result)

    path = Path("data/phase5-verification/b1-runtime-recovery-report.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"generatedAt": now.isoformat(), "readOnly": True,
                                "staleMinutes": args.stale_minutes, "records": records}, indent=2), encoding="utf-8")
    print(f"[READ ONLY] Runtime lifecycle review: {len(records)} deployments")
    print(f"[REVIEW] Older than {args.stale_minutes} min: {sum(r['olderThanThreshold'] for r in records)}")
    for r in records:
        if r["olderThanThreshold"]:
            print(f"[STALE] instance={r['instanceId']} deployment={r['deploymentId']} status={r['deploymentStatus']}")
    print(f"Report: {path.resolve()}")
    print("No database records or containers were modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
