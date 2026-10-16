# AUGMIS Runtime Lab — Recovery & Tenant Applications Navigation

## Contents
- `AUGMIS_RUNTIME_LAB_1.3.0_RECOVERY.zip`: Healthy container package, same immutable app ID (`augmis-runtime-lab`) and new version 1.3.0.
- `AUGMIS_ADD_TENANT_APPLICATIONS_NAV.py`: Optional guarded AppShell patch adding `My Applications` to the top navigation. The link is only shown when the selected tenant grants `subscription.view`; the page/backend also enforce access.

## Application recovery
1. Select the existing **Infomentica Platform** Publisher workspace which owns AUGMIS Runtime Lab (unless you are intentionally testing another publisher).
2. Upload `AUGMIS_RUNTIME_LAB_1.3.0_RECOVERY.zip` as AAPS / Containerized (not Static).
3. Build it and Publish it. Publishing does not revive versions 1.0.0, 1.1.0, 1.2.0 or 2.0.0; they remain retired.
4. An active ABC Engineering Secure subscription using `same_major` is compatible with v1.3.0 ONLY if its stored baseline is a 1.x version. Check `baselineVersionId` / subscription detail before upgrading. Existing instance upgrades are MANUAL and governed by authorization/health tests.
5. In the Tenant Applications page, search `AUGMIS Runtime Lab`. A subscribed tenant may still open its existing 1.0.0 baseline after retirement if its entitlements are valid; publishing new 1.3.0 alone does NOT automatically upgrade the existing instance.

## Add menu link
From `D:\Uday_Documents\AUGMIS_PLATFORM`, save the installer locally and run:
```
python AUGMIS_ADD_TENANT_APPLICATIONS_NAV.py --repo . --check
python AUGMIS_ADD_TENANT_APPLICATIONS_NAV.py --repo . --apply
cd apps/web
npx tsc --noEmit
npm run build
```
`--check` requires the previously-reviewed AppShell navigation block. If blocked, share your latest `apps/web/src/components/app-shell.tsx`, don't force the patch.

## Constraints
- No SQL updates or restoration of retired versions.
- No bypass of tenant permissions, subscriptions or entitlements.
- No changes to AppShell providers, backend runtime gateway, tenant selection, or audit behavior.
- `.bak` file remains local and should not be committed.
