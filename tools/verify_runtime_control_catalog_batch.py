"""Read-only AUGMIS catalog and quota integration smoke checks."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = lambda path: (root / path).read_text(encoding='utf-8')
editor = source('apps/web/src/components/runtime-environment-variables-editor.tsx')
catalog = source('apps/web/src/lib/runtime-variable-catalog.ts')
quota = source('apps/web/src/components/runtime-quota-manager.tsx')
route = source('services/api/app/routes/runtime_control.py')
page = source('apps/web/src/app/runtime-control/page.tsx')
api = source('apps/web/src/lib/runtime-control.ts')
checks = {
    'catalog and selectable multi-variable presets': all(s in editor for s in ('RUNTIME_VARIABLE_CATALOG', 'RUNTIME_CONFIG_PROFILES', 'Autocomplete', 'Checkbox', 'Add selected', 'Browse full catalog')),
    'server-backed revision save remains intact': all(s in editor for s in ('onSave(normalize(rows))', 'revision', 'Discard edits')) and 'updateRuntimeConfig(currentId, config.revision' in page,
    'backend variable validation unchanged': 'validate_runtime_variables(payload.variables)' in route,
    'quota UI requires server-returned capability': 'quota?.canManageQuota' in quota and 'quota?.canManageQuota' in quota,
    'quota write backend authorization intact': 'permission_code="platform.settings.manage"' in route and 'max_running_containers: int = Field(ge=1, le=1000)' in route,
    'quota response capability added after tenant view check': '"canManageQuota": can_manage_quota' in route and 'permission_code="application.instance.view"' in route,
    'quota helper uses existing API and expected shape': 'api.put<RuntimeQuota>' in api and 'max_running_containers: maxRunningContainers' in api,
    'existing upgrade controls retained': 'RuntimeUpgradeReadinessPanel' in page and 'Automatic upgrade jobs' in page,
    'sample names do not use reserved prefixes': all(not (s.startswith('AUGMIS_') or s.startswith('DOCKER_') or s.startswith('LD_')) for s in __import__('re').findall(r'name: "([A-Z0-9_]+)"',catalog)),
}
for label, ok in checks.items():
    print(('[PASS] ' if ok else '[FAIL] ') + label)
if not all(checks.values()):
    raise SystemExit(1)
print('[PASS] Combined runtime configuration/quotas structural verification; live frontend/API testing still required.')
