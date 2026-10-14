"""AUGMIS B1+B2 read-only live inventory. No plaintext env, cookies or tokens."""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def _now():
    return datetime.now(timezone.utc)


def _docker_state(name: str):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", name):
        return {"result": "invalid_container_name"}
    try:
        proc = subprocess.run(
            ["docker", "inspect", "--type", "container", "--format", "{{json .State}}", name],
            capture_output=True, text=True, timeout=12, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"result": "docker_unavailable"}
    if proc.returncode:
        return {"result": "not_found_or_unavailable"}
    try:
        state = json.loads(proc.stdout)
        health = state.get("Health") or {}
        return {"result": "found", "running": bool(state.get("Running")),
                "status": str(state.get("Status")),
                "health": str(health.get("Status")) if health else None}
    except (ValueError, AttributeError):
        return {"result": "invalid_docker_response"}


def inspect_db(*, with_docker: bool = False, max_containers: int = 80) -> dict:
    """Read-only diagnostics: no writes, Docker state inspection only."""
    from sqlalchemy import select, func
    from services.api.app.db.session import SessionLocal
    from services.api.app.models.platform import ApplicationInstance, ApplicationDeployment
    from services.api.app.models.commerce import TenantSubscription, ApplicationOffer
    from services.api.app.models.runtime_control import RuntimeUpgradeJob, TenantRuntimeQuota
    from services.api.app.services.runtime_automation_service import plan_upgrades

    result: dict = {"readOnly": True, "tenants": [], "jobs": {}, "duplicateSubscriptions": [],
                    "deployments": {"checked": 0, "issues": []},
                    "eligibleUpgrades": [], "warnings": []}
    with SessionLocal() as db:
        try:
            # This is a Session-local read only transaction, explicitly rolled back.
            instances = list(db.scalars(select(ApplicationInstance)))
            deployments = list(db.scalars(select(ApplicationDeployment)))
            jobs = list(db.scalars(select(RuntimeUpgradeJob)))
            quotas = {str(q.tenant_id): q.max_running_containers for q in db.scalars(select(TenantRuntimeQuota))}
            result["instances"] = {"total": len(instances), "byStatus": dict(Counter(i.status for i in instances))}
            result["jobs"] = {"total": len(jobs), "byStatus": dict(Counter(j.status for j in jobs)),
                "needsReconciliation": [str(j.id) for j in jobs if j.status == "needs_reconciliation"],
                "expiredRunning": [str(j.id) for j in jobs if j.status == "running" and j.lease_until
                    and j.lease_until < _now()]}
            if result["jobs"]["expiredRunning"]:
                result["warnings"].append("Expired running jobs must be reconciled; do not auto-retry.")
            if result["jobs"]["needsReconciliation"]:
                result["warnings"].append("Uncertain runtime job outcomes require operator reconciliation.")
            slots = Counter(str(i.tenant_id) for i in instances)
            tenant_for_instance = {str(i.id): str(i.tenant_id) for i in instances}
            running = Counter(tenant_for_instance.get(str(d.instance_id)) for d in deployments
                              if d.status in ("running", "deploying"))
            for tenant_id in sorted(slots):
                cap = quotas.get(tenant_id)
                usage = running.get(tenant_id, 0)
                result["tenants"].append({"tenantId": tenant_id, "instances": slots[tenant_id],
                    "runningOrReservedContainers": usage, "containerLimit": cap,
                    "overQuota": cap is not None and usage > cap})
                if cap is not None and usage > cap:
                    result["warnings"].append("Tenant has running/reserved deployments above quota: " + tenant_id)
            subs = list(db.execute(select(TenantSubscription.tenant_id, ApplicationOffer.application_id,
                TenantSubscription.id).join(ApplicationOffer, ApplicationOffer.id == TenantSubscription.offer_id)
                .where(TenantSubscription.status == "active", ApplicationOffer.status == "active")))
            grouped = defaultdict(list)
            for tid, aid, sid in subs:
                grouped[(str(tid), str(aid))].append(str(sid))
            result["duplicateSubscriptions"] = [
                {"tenantId": tid, "applicationId": aid, "activeSubscriptionCount": len(ids)}
                for (tid, aid), ids in sorted(grouped.items()) if len(ids) > 1
            ]
            if result["duplicateSubscriptions"]:
                result["warnings"].append("Duplicate active subscriptions: automatic upgrades fail closed.")
            result["eligibleUpgrades"] = plan_upgrades(db, dry_run=True, limit=1000)
            if with_docker:
                active = [d for d in deployments if d.status in ("running", "deploying")]
                for d in active[:max_containers]:
                    state = _docker_state(str(d.container_name or ""))
                    result["deployments"]["checked"] += 1
                    if state.get("result") != "found" or (d.status == "running" and not state.get("running")):
                        result["deployments"]["issues"].append({"deploymentId": str(d.id),
                           "instanceId": str(d.instance_id), "dbStatus": d.status, "docker": state})
                if len(active) > max_containers:
                    result["warnings"].append("Docker sample capped; not all active deployments were inspected.")
            return result
        finally:
            db.rollback()


def main():
    parser = argparse.ArgumentParser(description="Read-only AUGMIS B1+B2 runtime preflight")
    parser.add_argument("--with-db", action="store_true", help="Read current database")
    parser.add_argument("--with-docker", action="store_true", help="Inspect containers (implies --with-db)")
    parser.add_argument("--max-containers", type=int, default=80)
    parser.add_argument("--output", default="data/phase5-verification/b1b2-live-preflight.json")
    parser.add_argument("--strict", action="store_true", help="Fail if issues require operator review")
    args = parser.parse_args()
    if not 1 <= args.max_containers <= 500:
        parser.error("--max-containers must be 1..500")
    report = {"generatedAt": _now().isoformat(), "readOnly": True,
              "scope": "B1+B2 local runtime acceptance", "checks": {}}
    if args.with_db or args.with_docker:
        try:
            report["checks"] = inspect_db(with_docker=args.with_docker, max_containers=args.max_containers)
        except Exception as error:
            # Report error type, not database connection strings or credentials.
            report["checks"] = {"errorType": type(error).__name__, "error": "DB or runtime inventory unavailable"}
            print("[FAIL] DB/runtime inventory:", type(error).__name__)
    else:
        print("[INFO] No DB/Docker accessed. Use --with-db --with-docker for live inventory.")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str)+"\n", encoding="utf-8")
    print("[READ ONLY] Report:", out)
    result = report["checks"]
    if result.get("error"):
        sys.exit(2)
    if result.get("instances"):
        print("[DB] Instances:", result["instances"]["total"], "Jobs:", result["jobs"]["total"])
        print("[DB] Eligible opt-in upgrades:", len(result["eligibleUpgrades"]))
        print("[DB] Duplicate active subscription groups:", len(result["duplicateSubscriptions"]))
        print("[DB] Jobs needing reconciliation:", len(result["jobs"]["needsReconciliation"]))
        print("[DOCKER] Inspected:", result["deployments"]["checked"],
              "Mismatch:", len(result["deployments"]["issues"]))
        for warning in result["warnings"]:
            print("[REVIEW]", warning)
    if args.strict and (result.get("warnings") or result.get("deployments", {}).get("issues")):
        sys.exit(1)

if __name__ == "__main__":
    main()
