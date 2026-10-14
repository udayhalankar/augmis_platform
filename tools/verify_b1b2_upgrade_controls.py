"""Non-destructive verification of the upgrade-consent integration.

Structural checks are intentionally lightweight. Follow with local full
Next.js tsc/build and live HTTP 403/409 acceptance tests.
"""
from __future__ import annotations
import ast
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    route = (root / "services/api/app/routes/runtime_control.py").read_text("utf-8")
    api = (root / "apps/web/src/lib/runtime-control.ts").read_text("utf-8")
    page = (root / "apps/web/src/app/runtime-control/page.tsx").read_text("utf-8")
    component = (root / "apps/web/src/components/runtime-upgrade-readiness-panel.tsx").read_text("utf-8")
    tree = ast.parse(route)
    defs = {x.name: x for x in tree.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert {"_active_runtime_contracts", "get_upgrade_readiness", "update_instance_auto_upgrade_consent"} <= set(defs)
    consent = ast.get_source_segment(route, defs["update_instance_auto_upgrade_consent"]) or ""
    assert '"subscription.manage"' in consent and '"application.instance.view"' in consent
    assert 'len(contracts) != 1' in consent
    assert '"needs_reconciliation"' in consent
    assert 'expected_auto_upgrade' in consent
    assert '"subscription.auto_upgrade.updated"' in consent
    assert 'start_scoped_container' not in consent and 'perform_instance_upgrade' not in consent
    readiness = ast.get_source_segment(route, defs["get_upgrade_readiness"]) or ""
    assert '"subscription.view"' in readiness and 'eligible_upgrade(db, instance)' in readiness
    assert "updateRuntimeAutoUpgradeConsent" in api and "getRuntimeUpgradeReadiness" in api
    assert page.count('import RuntimeUpgradeReadinessPanel ') == 1
    assert page.count('<RuntimeUpgradeReadinessPanel ') == 1
    assert 'window.confirm(' in component and 'useTenant' not in component
    print("[PASS] Subscription-scope authorization and duplicate-contract safeguards")
    print("[PASS] Consent persistence and audit trail present; no worker/container action")
    print("[PASS] Runtime UI uses canonical API helper; single readiness panel inserted")
    print("[NOTE] These are structural tests; live HTTP and TypeScript build acceptance remains required.")


if __name__ == "__main__":
    main()
