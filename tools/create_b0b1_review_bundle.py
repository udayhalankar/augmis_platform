"""Produce a tightly allowlisted review ZIP for B0+B1 runtime work.

Never packages .env, database exports, runtime data, credentials, node_modules,
venvs or .git. Review the ZIP locally before sharing: source might contain secrets.
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from tools.b0b1_runtime_inventory import FILES, ROOT

OUTPUT = ROOT / "data" / "phase5-verification" / "b0b1-runtime-review.zip"
EXTRA = [
    "services/api/app/core/rbac_catalog.py",
    "services/api/app/schemas/instance.py",
    "services/api/app/services/runtime_session_service.py",
    "services/api/app/services/static_package_service.py",
    "services/api/app/services/audit_export_service.py",
    "apps/web/src/components/app-shell.tsx",
    "apps/web/src/app/runtime/page.tsx",
    "services/api/app/models/iam.py",
]
# Obvious literal credential indicators. It is not a substitute for manual review.
SUSPECT = re.compile(
    r"(?i)(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:ghp_|github_pat_|sk_live_|sk_test_|GOCSPX-|AKIA)[A-Za-z0-9_-]{8,}|(?:password|api_key|client_secret|jwt_secret)\s*[:=]\s*['\"][^'\"\s]{8,}['\"])")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()
    outfile = Path(args.output).resolve()
    items = list(dict.fromkeys([p for group in FILES.values() for p in group] + EXTRA))
    accepted, skipped = [], []
    for rel in items:
        p = (ROOT / rel)
        if p.is_symlink() or not p.is_file():
            skipped.append({"path": rel, "reason": "not found/symlink"})
            continue
        if any(part in (".git", "data", "node_modules", ".venv", ".next") for part in p.parts):
            skipped.append({"path": rel, "reason": "forbidden path"})
            continue
        if p.stat().st_size > 600_000:
            skipped.append({"path": rel, "reason": "size limit"})
            continue
        raw = p.read_bytes()
        if SUSPECT.search(raw.decode("utf-8", errors="replace")):
            skipped.append({"path": rel, "reason": "suspected literal credential; not included"})
            continue
        accepted.append((rel, raw))
    outfile.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(outfile, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
        for rel, raw in accepted:
            zipf.writestr(rel, raw)
        zipf.writestr("B0B1_REVIEW_MANIFEST.json", json.dumps({
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "purpose": "SOURCE REVIEW ONLY - not a deployable application archive",
            "included": [r for r, _ in accepted], "skipped": skipped,
        }, indent=2) + "\n")
    print(f"[CREATED] {outfile}")
    print(f"Included source files: {len(accepted)}; skipped: {len(skipped)}")
    print("[IMPORTANT] Inspect ZIP contents for embedded credentials before sharing.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
