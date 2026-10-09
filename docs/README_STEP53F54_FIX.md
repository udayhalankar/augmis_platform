# AUGMIS Step 53F + 54 — targeted patcher correction (2026-10-09)

## Root cause
The original `tools/apply_step53f54.py` expected `const noAuditAccess =` in
`apps/web/src/app/audit/page.tsx`. The accepted Step 52D Audit Center page
uses `const permissionLoading = ...` and scope-specific `canPlatformAudit` /
`canTenantAudit` permissions instead. The original patcher therefore stopped
before writing any files. **No rollback is needed.**

## Install — REPLACE ONLY ONE FILE
Copy `tools/apply_step53f54.py` from this ZIP into:

`D:\Uday_Documents\AUGMIS_PLATFORM\tools\apply_step53f54.py`

The remainder of the original combined package (service, verification and
reporting scripts) does not need recopying if already installed.

## Run — from repo root

```powershell
cd D:\Uday_Documents\AUGMIS_PLATFORM
python -m tools.apply_step53f54 --check
```

Expected three `[PASS] Compatible` messages (audit route, audit client,
Audit Center page), followed by `[CHECK ONLY] No files changed.`

If compatible, continue:

```powershell
python -m tools.apply_step53f54 --apply
python -m compileall services/api/app tools
python -m tools.verify_step53f54
python -m tools.verify_phase4_rbac
python -m tools.verify_phase4_rbac_matrix
python -m tools.verify_single_publisher_workspace
python -m tools.report_legacy_publisher_reconciliation
cd apps/web
npx tsc --noEmit
npm run build
```

The script saves three `.before-step54.bak` copies locally. Do not commit them.

## UI behavior
After restarting backend and frontend and opening `/audit`, **Export CSV**
and **Evidence JSON** should be enabled for authorized Tenant or Platform
scopes, and disabled for **My Activity**. Personal exports are intentionally
not implemented because they require a separate server-authorized export
endpoint. The UI still shows and loads personal activity as before.

Exports use *applied* filters, not unsaved draft filters or current-page rows.
The backend remains the authorization boundary.

No Alembic migration is involved in this correction. The two legacy
Infomentica publishers are still intentionally unassigned pending a
confirmed reconciliation decision.

If `--check` blocks again, do not force the patch: share the exact output and
the newest versions of the named divergent file(s).
