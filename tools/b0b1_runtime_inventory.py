"""AUGMIS B0+B1 runtime inventory. Read-only, standard library only.

Run from repository root: python -m tools.b0b1_runtime_inventory
Optional --with-db / --with-docker probes use timeouts and collect only outcome.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "phase5-verification" / "b0b1-runtime-inventory.json"
FILES = {
    "models": [
        "services/api/app/models/platform.py",
        "services/api/app/models/commerce.py",
        "services/api/app/models/audit.py",
    ],
    "routes": [
        "services/api/app/routes/instances.py",
        "services/api/app/routes/operations.py",
        "services/api/app/routes/applications.py",
        "services/api/app/routes/audit.py",
    ],
    "services": [
        "services/api/app/services/build_engine.py",
        "services/api/app/services/deployment_engine.py",
        "services/api/app/services/instance_limit_service.py",
        "services/api/app/services/entitlement_service.py",
        "services/api/app/services/version_policy_service.py",
        "services/api/app/services/subscription_lifecycle_service.py",
        "services/api/app/services/audit_service.py",
        "services/api/app/services/authorization_service.py",
    ],
    "frontend": [
        "apps/web/src/lib/tenant-applications.ts",
        "apps/web/src/lib/runtime-gateway.ts",
        "apps/web/src/app/tenant-applications/page.tsx",
        "apps/web/src/app/runtime/[runtimeId]/[[...assetPath]]/route.ts",
    ],
    "config": [
        "services/api/app/main.py",
        "services/api/app/schemas/instance.py",
        "apps/web/package.json",
        "apps/web/package-lock.json",
        "alembic.ini",
        "requirements.txt",
    ],
}

ROUTE_ACTIONS = {"get", "post", "put", "patch", "delete", "api_route"}
EXPECTED_LIFECYCLE = {
    "deploy": "deploy_application",
    "stop": "stop_application_instance",
    "restart": "restart_application_instance",
    "upgrade": "upgrade_application_instance",
    "rollback": "rollback_application_instance",
    "health": "deployment_health",
    "logs": "deployment_logs",
}

def file_result(relative: str) -> dict:
    p = ROOT / relative
    if not p.is_file() or p.is_symlink():
        return {"path": relative, "present": False}
    data = p.read_bytes()
    result: dict = {"path": relative, "present": True, "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest()}
    if p.suffix == ".py":
        try:
            tree = ast.parse(data.decode("utf-8-sig"), filename=relative)
            funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            result["functions"] = sorted({n.name for n in funcs})
            endpoints = []
            for fn in funcs:
                for decorator in fn.decorator_list:
                    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                        continue
                    if decorator.func.attr not in ROUTE_ACTIONS or not decorator.args:
                        continue
                    path_arg = decorator.args[0]
                    if isinstance(path_arg, ast.Constant) and isinstance(path_arg.value, str):
                        endpoints.append({"http": decorator.func.attr.upper(), "path": path_arg.value, "handler": fn.name})
            if endpoints:
                result["endpoints"] = endpoints
        except (SyntaxError, UnicodeError) as error:
            result["parse_error"] = type(error).__name__
    return result

def probe(command: list[str], timeout=15) -> dict:
    binary = command[0]
    if not shutil.which(binary):
        return {"available": False, "ok": False}
    try:
        r = subprocess.run(command, cwd=ROOT, text=True, capture_output=True,
                           timeout=timeout, check=False)
        # Do not retain potentially sensitive stderr/stdout in report.
        return {"available": True, "ok": r.returncode == 0, "exitCode": r.returncode}
    except (OSError, subprocess.TimeoutExpired):
        return {"available": True, "ok": False, "timeoutOrExecutionError": True}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-db", action="store_true", help="Check Alembic commands; read only")
    parser.add_argument("--with-docker", action="store_true", help="Check Docker CLI/server; read only")
    parser.add_argument("--ci", action="store_true", help="Fail when mandatory runtime route files are missing or invalid")
    args = parser.parse_args()

    groups = {name: [file_result(rel) for rel in names] for name, names in FILES.items()}
    all_files = [row for value in groups.values() for row in value]
    bypath = {x["path"]: x for x in all_files}
    runtime_handlers = set()
    for rel in ("services/api/app/routes/instances.py", "services/api/app/routes/operations.py"):
        runtime_handlers.update(bypath.get(rel, {}).get("functions", []))
    lifecycle = {kind: {"handler": handler, "inSource": handler in runtime_handlers,
                        "endToEndVerified": False} for kind, handler in EXPECTED_LIFECYCLE.items()}
    report = {
        "kind": "AUGMIS_B0B1_SOURCE_INVENTORY",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "mode": "read-only",
        "disclaimer": "Functions in source do not prove runtime behavior, deployment security, or production readiness.",
        "files": groups,
        "lifecycle": lifecycle,
        "knownUnverifiedRequirements": [
            "Persist logs after container removal", "restart after process/Docker crash",
            "resource quotas CPU/memory/pids/disk", "per-instance environment configuration",
            "secret store reference and injection", "image digest pinning and signature policy",
            "cross-tenant instance read/write denial", "durable upgrade/rollback state",
            "private container networking", "startup/health check timeouts and audit failure"
        ],
    }
    if args.with_db:
        report["dbProbe"] = {key: probe(["alembic", key]) for key in ("current", "heads")}
    if args.with_docker:
        report["dockerProbe"] = probe(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=10)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[READ ONLY] Report: {OUTPUT}")
    print("Source inventory: found", sum(bool(f["present"]) for f in all_files),
          "of", len(all_files), "tracked source/config paths")
    for action, state in lifecycle.items():
        print(f"[{ 'PRESENT' if state['inSource'] else 'REVIEW' }] {action}: {state['handler']}")
    print("[NOTE] In-source means code was found, not end-to-end tested.")
    mandatory = ("services/api/app/routes/instances.py", "services/api/app/routes/operations.py",
                 "services/api/app/models/platform.py")
    if args.ci and any(not bypath[x].get("present") or bypath[x].get("parse_error") for x in mandatory):
        print("[FAIL] Mandatory runtime source is missing or unparseable.")
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
