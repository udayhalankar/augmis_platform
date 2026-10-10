#!/usr/bin/env python3
"""Safe, minimal AUGMIS AppShell navigation addition: My Applications."""
import argparse
from pathlib import Path
import sys

NAV_ANCHOR = '  {\n    label: "Applications",\n    href: "/publisher",\n    icon: (\n      <AppsOutlined\n        fontSize="small"\n      />\n    ),\n  },\n'
NAV_ADD = '  {\n    label: "My Applications",\n    href: "/tenant-applications",\n    tenantPermission: "subscription.view",\n    icon: (\n      <AppsOutlined\n        fontSize="small"\n      />\n    ),\n  },\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo',default='.')
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--apply', action='store_true')
    args=ap.parse_args()
    path = Path(args.repo).resolve() / 'apps/web/src/components/app-shell.tsx'
    if not path.is_file():
        sys.exit(f'[BLOCKED] Missing AppShell: {path}')
    blob=path.read_bytes()
    # Keep existing Windows/Unix newlines unchanged.
    newline = '\r\n' if b'\r\n' in blob else '\n'
    content=blob.decode('utf-8')
    old=NAV_ANCHOR.replace('\n',newline)
    extra=NAV_ADD.replace('\n',newline)
    if 'href: "/tenant-applications"' in content:
        print('[ALREADY APPLIED] My Applications navigation already exists; no changes.')
        return
    if content.count(old)!=1:
        sys.exit(f'[BLOCKED] Expected exactly one Applications navigation anchor; found {content.count(old)}. No changes made. Share current app-shell.tsx for a targeted patch.')
    if 'const visibleNavigation' not in content or 'hasTenantPermission' not in content:
        sys.exit('[BLOCKED] AppShell permission-aware navigation not found. No changes.')
    if args.check:
        print('[PASS] Compatible: apps/web/src/components/app-shell.tsx')
        print('[CHECK ONLY] No files changed.')
        return
    backup=path.with_name(path.name + '.before-tenant-app-nav.bak')
    if backup.exists():
        sys.exit(f'[BLOCKED] Backup already exists: {backup} (do not overwrite).')
    backup.write_bytes(blob)
    try:
        path.write_bytes(content.replace(old,old+extra,1).encode('utf-8'))
    except BaseException:
        path.write_bytes(blob)
        raise
    print('[APPLIED] My Applications link added to AppShell with subscription.view permission.')
    print(f'[BACKUP] {backup}')


if __name__ == '__main__':
    main()
