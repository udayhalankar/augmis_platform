# AUGMIS — Runtime Control Configuration Catalog + Quota Administration

## Scope
One combined, guarded patch for the previously accepted B1+B2 runtime-control system. Adds:

- Searchable, categorised library of **25 example environment names** (not universal application settings)
- Bulk-selection catalog and three ready-made suggested variable sets
- Custom-variable entry, suggested enumerated values, row edit/remove and discard changes
- Name, reserved-prefix, duplicate, secret-like name, per-value, total-size and 64-key frontend validation
- Existing optimistic-revision (`409`) persistence and existing backend RBAC/audit checks
- Platform-only tenant container-quota UI using existing PUT API (`platform.settings.manage`)
- Server-returned permission flag for quota-edit visibility; GET remains tenant-scoped
- Existing upgrade consent panel, job list, routing and deployments unchanged

## Security notes
1. Suggested keys have no effect unless an application explicitly reads them. This is **not** a Docker variable discovery facility or an AAPS manifest schema registry.
2. Do not enter secrets, tokens, credentials or passwords. A future secrets provider requires its own implementation; no vault is introduced here.
3. Client-side validation is for usability; FastAPI `validate_runtime_variables` remains authoritative. The backend still enforces 64 keys, allowed uppercase names, reserved prefixes, <=2048 UTF-8 bytes/value and <=16384 total.
4. Quota mutations remain protected by `platform.settings.manage`, validated server-side (1–1000) and audited.
5. Editing an instance does **not** restart a running container; new values apply at next start/restart/upgrade.
6. No Alembic migrations, workers, Docker operations, session/gateway modifications or RBAC catalog changes.

## Local acceptance (use a disposable instance)
1. Compatibility check: `python "<extracted>/install.py" --repo . --check`
2. Apply: `python "<extracted>/install.py" --repo . --apply`
3. Verify: `python -m tools.verify_runtime_control_catalog_batch`
4. Backend `python -m compileall -q services/api/app tools` and `python -m tools.verify_phase4_rbac_matrix`
5. Frontend `cd apps/web; npx tsc --noEmit; npm run build`
6. Open `/runtime`, select tenant + instance. Search/select LOG_LEVEL; choose INFO/DEBUG; add via catalog; save; refresh and verify persistence.
7. Add an existing custom name TEST with value 12. Save; reopen; update and remove; verify revision changes.
8. Add a Web/API baseline. Make one value different and save; confirm all keys persist. Attempt duplicate name / forbidden prefix / 65th key; Save should be disabled.
9. In a separate account, verify non-platform member sees quota read-only. Platform operator with required tenant view and platform.settings.manage may set a quota; an invalid or below-usage limit is rejected.
10. Repeat installation `--check` and confirm `[ALREADY]`, no unexpected changes.
11. Verify Runtime Lab gateway and subscription upgrade readiness remain working.

## Failure and recovery
- Installer performs a **full compatibility preflight** before any write and protects against unrelated local modifications.
- The original files are copied under ignored `data/phase5-verification/runtime-control-catalog-backup/` before replacement.
- Source writes roll back if an installation step fails.
- Do not force an installer that returns `[BLOCKED]`; upload only the specific differing file for correction.
