# AUGMIS B0+B1 — Actual implementation contract

## Verified from the available project snapshots

- `routes/instances.py` defines: `deploy_application`, `stop_application_instance`, `restart_application_instance`, `upgrade_application_instance`, `rollback_application_instance`, `open_containerized_application`, list/get endpoints and a runtime gateway route.
- `routes/operations.py` defines: `platform_readiness`, `deployment_health`, `deployment_logs`.
- `deployment_logs` currently reports HTTP 410 after Docker container removal if no persisted historical logs exist.
- Publisher/Tenant permissions and event audit already exist. Do **not** build a parallel auth, tenant or runtime gateway subsystem.
- Source snapshots are not sufficient to claim end-to-end correctness of start/stop/restart, health or rollback. Implement repairs after reviewing the **current** `build_engine.py`, `deployment_engine.py`, `instance.py`, models and route files.

## B0 acceptance

1. Source inventory generated; no secrets included in report; no database mutations.
2. Confirm current Git and Alembic revisions; preserve accepted Step 53E GitHub checkpoint.
3. GitHub Actions baseline (backend compile + source contract, frontend npm ci/TypeScript/build) green.
4. Manual live negative audit-export tests completed: denied tenant/platform scope 403, cross-tenant denial and export event audit record. Retention remains non-destructive.
5. Dev reset **not performed automatically**. User authorizes explicit database, time and environment only after separate DB dump/restore test. Do not delete legacy Infomentica data as an implicit migration side effect.

## B1 code to be implemented against the current source

1. State machine & idempotency: guarded transitions with per-instance DB locking, single active running deployment, durable operation identifiers and retry-safe handling of crashes between Docker actions and DB commits.
2. Lifecycle: deploy/start/stop/restart with explicit outcomes, health state, Docker state reconciliation, bounded timeouts, audit success/failure/denial and consistent instance/deployment history.
3. Upgrades & rollback: immutable application version references, image digest validation, new candidate health gate, promote only when healthy, safe rollback to prior known-good deployment if candidate fails; do not mutate offer/subscription state to hide failures.
4. Logs: retained bounded logs and durable deployment logs independent of deleted containers; tenant-specific access control; redact sensitive fields and never leak env/secrets.
5. Configuration: versioned tenant/instance configuration, typed validation, no unsafe arbitrary shell command or host mounts. Secrets stored by reference, resolved only by runtime with audited rotation; never plaintext via REST/list/CSV/audit.
6. Quotas: enforce per-tenant application instance count as already implemented; separately enforce per-container CPU/memory/PIDs/disk/network policies and start/restart failure cleanup.
7. Networking: do not assume published Docker host ports are production safe. Keep all B1 testing local/private until Phase 8 private network + TLS shared-session gateway is complete.
8. Tests: A and B tenants, four role scopes, cross-tenant access denial, stopped→restart, unhealthy-upgrade→rollback, Docker daemon unavailable, orphan container, duplicate request, missing build/image, cancellation and log retrieval after container deletion.

## B1 dependency inventory (canonical code, not stale snapshots)

- `services/api/app/routes/instances.py`, `operations.py`, `applications.py`.
- `services/api/app/services/build_engine.py`, `deployment_engine.py`, `instance_limit_service.py`, `entitlement_service.py`, `version_policy_service.py`, `audit_service.py`, `authorization_service.py`.
- `services/api/app/models/platform.py`, `commerce.py`, `audit.py`; `schemas/instance.py`; `core/rbac_catalog.py`.
- `apps/web/src/lib/tenant-applications.ts`, `runtime-gateway.ts`, `apps/web/src/app/tenant-applications/page.tsx`, static runtime gateway route, AppShell only for existing navigation reference.
- Current Alembic heads & repo source tree; existing tests and GitHub Actions.

**Exit criterion**: two tenants can each publish a deployment under appropriate entitlement, cannot access each other's instances/logs/config, and demonstrate successful restart plus failed-upgrade recovery, with state and audit consistent across API restart.

## Phase boundary

B0/B1 does **not** certify production isolation. Shared runtime session storage, HTTPS gateway, private container networks, production secrets storage and hardened Docker deployment remain required Phase 8 gates. Full auto-upgrade scheduling remains Phase 6.
