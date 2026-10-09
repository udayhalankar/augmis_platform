# AUGMIS Step 53E — TARGETED PATCH for current Users page

Reviewed source: `page(20261009-193335).tsx`, SHA256 normalized = `b9840652da6178c618e24331ed3145595b0e900df79963cc81f8329a54647f8b`.

## What's changed

- Keeps existing `users/page.tsx` (3,396 lines) intact except new imports, 5 states, a workspace-loading effect, an activation action, and one Publisher Capability panel.
- Uses existing `PublisherUsersDialog` and `publisher-users.ts` from Step 53C. No duplicate modal, app shell, providers or tenant selector.
- Shows **`<Tenant Account Name> Workspace (not enabled)`** if publishing is not enabled.
- Activating an eligible Tenant Owner creates an active workspace called **`<Tenant Account Name> Workspace`** and grants the initiating Tenant Owner **Publisher Owner** in that workspace. Existing workspaces keep their current names.
- Unique `tenant_id` constraint, idempotent activation and Publisher Owner checks are implemented in existing reviewed Step 53E route/service patch.
- Parent tenant permissions do not automatically grant Publisher permissions; Publisher Users & Roles button requires `publisher.manage` in that workspace.
- Existing tenant member management/invitations/suspend/revoke/last-owner protections untouched.

## Preconditions

From prior Step 53E bundle, these files should already exist:

- `apps/web/src/components/publisher-users-dialog.tsx` from Step 53C
- `apps/web/src/lib/publisher-users.ts` from Step 53C
- `apps/web/src/lib/organization-publisher.ts` from Step 53E
- `services/api/alembic/versions/9d3a4c7e1b20_single_publisher_workspace.py` from Step 53E
- `services/api/app/services/publisher_workspace_service.py` from Step 53E

No changes to the files above except the **existing workspace service's publisher name** are needed; this script patches that service with a strict source compatibility check.

## Apply from repository root (`D:\Uday_Documents\AUGMIS_PLATFORM`)

1. Unzip to a **temporary** folder. Replace only `tools/apply_single_workspace_users.py` in the repository with the supplied new script. **Do not manually copy the PREVIEW page, model, route, or service into your repository.** They show exactly what the script will generate.
2. Ensure you have a database backup and Git checkpoint (working-tree changes saved).
3. Run:

```powershell
python -m tools.apply_single_workspace_users --check
alembic current
alembic heads
```

4. Confirm Alembic head is `9d3a4c7e1b20`. If the database has not yet applied that migration, back it up first and run `alembic upgrade head`. Verify `alembic current` is `9d3a4c7e1b20`.

5. Only if all FOUR compatibility checks pass, apply exactly once:

```powershell
python -m tools.apply_single_workspace_users --apply
python -m compileall services/api/app tools
python -m tools.verify_single_publisher_workspace
python -m tools.verify_phase4_rbac
python -m tools.verify_phase4_rbac_matrix
python -m tools.verify_publisher_owner_integrity
cd apps/web
npx tsc --noEmit
npm run build
cd ../..
git diff --check
git status --short
```

6. Restart FastAPI and Next.js. Test `/users` as Tenant Owner on an existing linked organization and on an organization with no workspace. Check that a second publisher cannot be created for the same tenant (409) and that Tenant Admin activation returns 403. Existing legacy publishers with `tenant_id=NULL` are left untouched.

## Safety notes

- If `--check` reports `[BLOCKED]`, **stop and provide the current file named by the error**. Never disable the hash guard or overwrite user changes.
- If the runner reports that `*.before-single-workspace.bak` already exists, stop and inspect it. Do not delete or overwrite an existing backup without verifying whether a prior application succeeded.
- `--apply` will write `*.before-single-workspace.bak` backups for the four files before modifying them.
- The generated preview sources are only for diff/inspection. They are **not** a replacement for checking source compatibility.
- This was dry-run checked against the provided frontend file and prior backend snapshots, and TSX *syntax* checked locally. Repository-wide TypeScript build and API/DB integration require tests in your own project.
