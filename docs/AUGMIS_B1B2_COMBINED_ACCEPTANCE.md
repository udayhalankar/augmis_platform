# AUGMIS B1 + B2 — Integrated Runtime Controls and Version Automation

**State:** Installable implementation; local acceptance REQUIRED. **Do not treat it as production security sign-off.**

## Adds

- Canonical manual upgrade operation extracted into a shared internal executor. Existing HTTP route **still enforces** `application.deploy`; trusted background worker does NOT impersonate a user. Shared executor rechecks commercial subscription/entitlement/version policy and uses the B1A healthy-candidate-before-cutover flow and archived log snapshots.
- PostgreSQL `runtime_upgrade_jobs` with unique source/target job keys, atomic row claims (`FOR UPDATE SKIP LOCKED`), 30-minute leases, explicit system audit events, change-of-eligibility deferral, and **quarantine of expired running jobs for manual reconciliation**. Automatic replay is intentionally disabled for uncertain Docker outcomes.
- CLI opt-in scheduler/worker: dry-run by default. `--enqueue-and-run` enables a single queue/execute iteration; `--loop --enqueue-and-run` opt-in loop.
- Runtime config API (`GET/PUT /api/v1/instances/{id}/configuration`) with revision conflict checks, backend `application.deploy` on writes, `application.instance.view` on reads, strict **non-secret** environment validation. Configuration revisions/snapshots apply on *next start, restart, manual upgrade or rollback*, never silently to running containers. No raw secret values accepted in `secretRefs`; providers are **not implemented** in this release.
- Immutable local Docker image identity (`sha256:...`), stored on build at first launch. Subsequent retag of the same build rejects startup; Docker starts by pinned ID, not mutable tag. Image signing/provenance/remote registry remain Phase B3.
- Per-tenant concurrent container cap (`tenant_runtime_quotas`). Platform settings manager alone can change via `PUT /api/v1/tenants/{id}/runtime-quota`. Default for existing tenants: no quota record means baseline behavior unchanged. If configured, candidate deployment counts toward the limit. Existing B1A per-container CPU/RAM/PID Docker limits remain enforced; aggregate CPU/RAM reservations are NOT yet implemented.
- Tenant-visible jobs `GET /api/v1/tenants/{id}/upgrade-jobs` scoped by `application.instance.view`.
- New Next.js page `/runtime-control`, using the existing AppShell and TenantProvider, shows instances, jobs, quotas and allows backend-authorized non-secret configuration changes. No duplicate tenant selection or user-role bypass. This route is available directly without altering the working AppShell navigation.
- Read-only multi-asset static ZIP regression (existing canonical static ZIP support reused).

## Important limitations

- No user-created secret plaintext storage, key management, rotation, isolated secret provider or Docker runtime secrets. Secret values in plain environment variables are inherently visible to Docker operators; never enter real credentials in `variables`.
- Active sessions remain in Python memory; private Docker network, shared Redis sessions, WebSockets/SSE isolation, automated host disaster recovery, log archival guarantees, storage quotas, metering, antivirus hooks and remote provenance are **still Phase B3/production hardening**.
- Upgrade worker has no automatic stalled-job replay. A `needs_reconciliation` job MUST be reviewed against live Docker containers/deployments before an explicit operator action. **Do not automatically delete candidates.**
- **Ambiguous duplicate active subscriptions:** automatic upgrade planning refuses to pick a contract if more than one active subscription exists for the same tenant/application. Do not delete test records just to force a worker run. Bind instances to subscriptions in a future migration.
- **Surge:** one candidate is allowed above a tenant's container cap only while an old deployment for that same instance is running and an upgrade/rollback candidate is starting.
- Two-tenant testing, parallel upgrade stress and real secrets-provider testing have not been executed by the package generator. Package files compiling is not final acceptance.
- Containerized automation only; multi-file static ZIP remains supported by existing canonical code, not Docker upgrades.

## Safe installation (Windows PowerShell)

1. Back up PostgreSQL and your Git branch. Stop FastAPI and any runtime worker. Review `.env`/secrets and keep local backups outside Git.
2. Extract the release ZIP and find `AUGMIS_B1B2_COMBINED/install.py`. From repository root:

```powershell
python "D:\Downloads\AUGMIS_B1B2_COMBINED\install.py" --repo . --check
# If every compatibility check passes:
python "D:\Downloads\AUGMIS_B1B2_COMBINED\install.py" --repo . --apply

alembic current
alembic heads
alembic upgrade head
alembic current

python -m compileall -q services/api/app tools
python -m tools.verify_b1b2_runtime
python -m tools.verify_b1_runtime_safety
python -m tools.verify_phase4_rbac_matrix
python -m tools.verify_single_publisher_workspace

git diff --check
cd apps/web
npx tsc --noEmit
npm run build
```

3. Restart FastAPI only after `alembic current` is `b1b22026101001`; browse `/docs` for the runtime governance endpoints. `--apply` edits source only; it DOES NOT run migrations, start jobs, change containers, or reset test data.
4. The previous gateway base-href patch is deliberately not replaced. Verify current fully styled Runtime Lab still loads JS/CSS/health APIs.

## Worker commands — OFF by default

```powershell
# Dry run: shows eligible running container instances; no DB write/Docker change.
python -m tools.runtime_upgrade_worker

# Development-only execution: opt-in; queues then executes ONE job.
python -m tools.runtime_upgrade_worker --enqueue-and-run

# Explicit, separately supervised process (do not run for production yet):
python -m tools.runtime_upgrade_worker --enqueue-and-run --loop --interval 60
```

Workers require DB access, Docker host, and the same settings as the FastAPI service. One worker must not be started until the following disposable-instance test gates pass.

## Required acceptance

1. Publisher publishes healthy v1.1.0 and the opted-in tenant has a running v1.0.0 instance with `auto_upgrade=true` and `same_major`. Dry run finds it. With `auto_upgrade=false`, no job. For `pinned`, version must stay pinned. `any` permits 2.0.0 when published and healthy. `same_major` disallows 1.x→2.x.
2. Unhealthy v1.2.0 published and selected: worker job records **failed**, candidate health fails, previous deployment and gateway remain on healthy version, failed logs archived if available. No ambiguous automatic retry.
3. Two isolated tenants: no cross-tenant read/write of configuration, jobs, quotas, deployments or logs. A publisher role never grants tenant deployment permission.
4. Restart then check new hostname; old config revision remains in old deployment while revised config applies only to new one.
5. Set a 1-container quota on a **disposable** tenant. Second simultaneous container must fail without starting; clear quota only through platform-authorized endpoint. Avoid setting quota below a live tenant's active usage.
6. Retag a built image and confirm startup rejects changed tag. Confirm running deployment stores immutable image ID and config snapshot.
7. Multi-file static `index.html`+CSS+JS+images works. Traversal/symlink/missing-index ZIP denied. Bad AAPS manifest denied. Any required malware scanning must be fail-closed in a later hooked provider implementation.
8. Run production build and full existing Phase4/Phase5 regression. No DB wipes or publisher data reconciliation in this batch.

## Recovery, aborts and rollback

Installer is guarded; on mismatch it prints `[BLOCKED]` and makes no source changes. It creates `.before-b1b2.bak` for four edited files; do not commit backups. **DB downgrade deletes control-job and config history**, so take a PostgreSQL backup first. A stopped or crashed worker leaves a running job; after lease expiry it is quarantined as `needs_reconciliation`, **not retried**. Review Docker and database state manually before resuming any upgrade.

### Runtime UI

Open `http://localhost:3000/runtime-control` as a tenant member with `application.instance.view`. Only `application.deploy` can save non-secret config. A `403` from the backend must remain authoritative. Existing AppShell navigation has NOT been overwritten.
