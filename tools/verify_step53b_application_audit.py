"""Static coverage verifier for AUGMIS Phase 5 Step 53B.

Does not need a running API or database. Real API tests are still required.
"""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

TARGET = Path('services/api/app/routes/applications.py')
EXPECTED = {
    'upload_application': {
        'application.package.uploaded',
        'application.package.validation.started',
        'application.package.validation.failed',
        'application.package.validated',
        'application.created',
        'application.updated',
        'application.version.created',
    },
    'upload_static_application': {
        'application.package.uploaded',
        'application.package.validation.failed',
        'application.package.validated',
        'application.created',
        'application.updated',
        'application.version.created',
    },
    'build_application_package': {
        'application.build.started',
        'application.build.succeeded',
        'application.build.failed',
    },
    'publish_application_version': {
        'application.version.published',
        'application.version.retired',
    },
    'retire_application_version': {'application.version.retired'},
}


def main():
    path = TARGET
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    seen = {}
    fails = []
    for fn in tree.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name not in EXPECTED:
            continue
        actions = []
        for n in ast.walk(fn):
            if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Name) or n.func.id != 'record_audit_event':
                continue
            args = {kw.arg: kw.value for kw in n.keywords if kw.arg is not None}
            action = args.get('action')
            if not isinstance(action, ast.Constant) or not isinstance(action.value, str):
                fails.append(f'{fn.name}: dynamic audit action not allowed in this step')
                continue
            actions.append(action.value)
            required = {'db', 'actor_user_id', 'publisher_id', 'resource_type', 'resource_id'}
            missing = required - set(args)
            if missing:
                fails.append(f'{fn.name} {action.value}: missing audit fields: {sorted(missing)}')
            if action.value.endswith('.failed'):
                outcome = args.get('outcome')
                if not isinstance(outcome, ast.Constant) or outcome.value != 'failed':
                    fails.append(f'{fn.name} {action.value}: failure requires outcome=failed')
        seen[fn.name] = set(actions)
        counts = Counter(actions)
        for action, cnt in counts.items():
            if cnt > 1 and not (fn.name == 'upload_static_application' and action == 'application.package.validation.failed'):
                fails.append(f'{fn.name}: unexpected duplicate action {action} ({cnt})')
        missing = EXPECTED[fn.name] - set(actions)
        unexpected = set(actions) - EXPECTED[fn.name]
        if missing or unexpected:
            fails.append(f'{fn.name}: missing={sorted(missing)} unexpected={sorted(unexpected)}')
        else:
            print(f'[PASS] {fn.name}: {len(set(actions))} actions; actor/publisher/resource fields present')
    for fn in set(EXPECTED) - set(seen):
        fails.append(f'Function not found: {fn}')
    if fails:
        for f in fails:
            print('[FAIL]', f)
        raise SystemExit(1)
    print('STEP 53B APPLICATION AUDIT STATIC COVERAGE: PASSED')
    print('Note: End-to-end API/DB state and audit atomicity still require local testing.')


if __name__ == '__main__':
    main()
