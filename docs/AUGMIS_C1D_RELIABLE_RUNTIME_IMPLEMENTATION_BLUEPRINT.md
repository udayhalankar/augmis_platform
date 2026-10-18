# AUGMIS C1-D — Reliable Application Runtime and Containerization Release Gate

Status: **Implementation blueprint — NOT installed, NOT production-accepted**  
Prepared: 2026-10-18  
Basis: AUGMIS project architecture instructions, supplied C1-C source snapshots and C1-C3 generic-runtime integration package, reported live acceptance of three apps.

## 1. Desired contract

For **supported** application types, the path must be repeatable:

**Analyze source → Produce validated AAPS → Build immutable image → Test in isolated disposable environment → Certify deployability → Publish → Subscribe → Provision dedicated database → Launch and route → Verify → Activate → Observe and recover.**

AAPS upload must not imply deployability. Unsupported features are rejected before subscribers are offered a deployable version. Deployment can fail for external reasons; failures must be bounded, safely recoverable, traceable, and never silently downgrade security.

## 2. What exists and what is missing

| Area | Demonstrated today | Remaining mandatory gap |
|---|---|---|
| Publisher/build | Upload/build/publish across multiple apps | Runtime compatibility qualification before a deployable version is offered |
| Runtime | Independent Next.js/Python, generic C1-C3 path in development | Durable runtime configuration, host readiness and a production-rated ingress |
| Data | Separate per-instance PostgreSQL + persisted new records + controlled declarative schema | Backup/restore, storage quotas, DB disaster recovery, migrations for upgrades |
| Security | Signed gateway, route contracts, restricted DB access, RLS foundation | App CRUD permissions, key rotation, distributed replay prevention, security-negative acceptance |
| Lifecycle | Open, upgrade and baseline promotion pilots | Durable idempotent operations, reconciliation, safe retry/rollback after interrupted operations |
| Operations | Manual preflight and diagnostics scripts | First-class deployability report, detailed stages, authorized diagnostics, alerting |
| Containerization Tool | Scoped, not implemented | Analyzer, generator, smoke runner and Publisher Center wizard |

## 3. C1-D implementation, integrated into existing services

### C1-D1 — Durable runtime host configuration and fail-fast startup (first)
- Establish **one typed, centrally loaded platform runtime profile**. Development file configuration must be outside source control; production uses orchestration configuration and a managed secret store. Never place raw secrets in metadata or AAPS.
- Eliminate ad hoc per-terminal setting requirements. Image references must be immutable digests or validated image IDs; signing private keys referenced by secure file/secret handle, with permissions checked.
- `settings.app_env` controls dev/production policy explicitly. Do not enable development-only unquoted volumes or loopback ingress in production.
- API startup validates Docker/orchestrator connectivity, image IDs, network topology, signing material, DB provisioning, quota limits and safe ingress. Expose precise readiness state. **Management API may remain observable while deployment operations fail closed when the host is unready.**
- Reuse `services/api/app/core/config.py`, `services/api/app/main.py`, `tools/check_c1c3_generic_readiness.py`, `services/api/app/services/aaps_generic_runtime.py`, and existing deployment services. No parallel engine.
- Test restart in a new terminal and simulated host reboot: configuration still loads; no browser-side setting or copy-paste flags are necessary.

### C1-D2 — Deployability qualification before subscription launch
- Keep AAPS versioned and immutable. Containerization Tool emits verified contract: runtime/port/health, database schema mode, versioned schema changes, routes and methods, auth, secret names, external dependencies, resources, assets, compatible storage, rollout policy.
- A signed qualification result is bound to immutable build image digest + manifest digest + platform runtime capabilities.
- Isolated temporary smoke deployment validates app readiness using real provider-managed credentials, a disposable private database, schema bootstrap, signed create/read/update call where declared, and private relay behavior. On failure: `INCOMPATIBLE` / `TEST_FAILED`, reason and stage surfaced to publisher. Cleanup temporary resources without touching persistent tenant volumes.
- Version states distinguish `IMAGE_READY`, `DEPLOYABLE`, and `NOT_SUPPORTED`. Publication/catalog visibility and eligibility to launch are separate concerns; only compatible, qualified versions become deployable.
- Use existing package validator, build engine, Publisher Center and app routes, not a second registry.

### C1-D3 — Idempotent, durable deployment workflow
- Introduce explicit stages: `RESERVED → DB_PROVISIONING → DB_READY → SCHEMA_INITIALIZING → RUNTIME_STARTING → HEALTH_CHECKING → GATEWAY_VERIFYING → ACTIVE`.
- Each stage records attempt, correlation ID, resource ownership, immutable images, timestamps, error code (no secrets) and redacted log reference. Stage completion is committed transactionally where possible.
- Re-run/reconcile after API crash, Docker daemon restart or network timeouts. Enforce one in-flight operation per instance, bounded retries/backoff for transient failures, quarantine permanent contract errors. Preserve volumes and previous healthy deployment on failure.
- Adopt names/aliases <=63 characters, unique per instance and candidate, with tested Docker DNS/relay forwarding.
- Deployment must never fall through from a private-DB contract to public-port ordinary Docker mode. No implicit destructive cleanup of failed data resources.

### C1-D4 — Production security, health and operations
- Authenticated tenant and application-context authorization for every request; replace development pilot's broad `application.deploy` for CRUD writes with application CRUD permission grants.
- Distributed one-time JWT/JTI replay tracking for multiple workers; rotate Ed25519 keys; enforce TTL, method/path/query/body binding; deny wrong app/tenant/instance, expired/replayed assertions and undeclared routes.
- Enforce RLS for reads AND writes, least-privilege runtime role, isolated PostgreSQL credentials/volume/network, backup/restore and versioned upgrade migration privileges.
- True production ingress over TLS with private service-to-service connectivity, no browser access to container/DB ports. Health probe HTTP from runtime network, not `docker exec python` or Node-dependent tools. Distinguish liveness and readiness; avoid database-sensitive response text.
- Tenant quota, CPU/memory/PID quotas, DB storage quotas, secret redaction, audit events, metrics and alerting.
- Add Deployment Diagnostics to existing Runtime workspace: stage, error code, retry eligibility, redacted logs, correlation ID, precise remediation and last healthy version.

### C1-D5 — App Containerization Tool integration
- Publisher Center guided `Source → Analyze → Configure → Generate → Build/Test → Validate/Register` workflow using existing AppShell/auth/tenant context and backend registry/build services.
- Recognize and report *supported*, *guided adaptation*, *unsupported*. Never claim arbitrary source apps deploy unchanged.
- Emit the exact AAPS runtime contract the generic engine can qualify and host, instead of maintaining separate adapter assumptions.

## 4. Release blockers / non-negotiable tests

**Acceptance runs in a clean new environment using no manually entered per-session flags.**

1. Fresh upload/build/qualification/subscribe/deploy/open of **three independent application identities** (FastAPI CRUD, Next.js Maintenance, Next.js Asset Checkout), each receiving separate PostgreSQL instance resources.
2. Database-backed create/edit/refresh SQL verification; existing records never vanish across application and control-plane restarts.
3. Ten repeated provision/deploy/open cycles using disposable **new** test instances with explicit cleanup policies; no manual source edits or failed orphaned resources. (Expand coverage before production sign-off.)
4. Simulated failure: Docker temporarily unavailable, DB not ready, bad image, wrong health path, relay DNS failure, timeout, API process crash mid-stage. Stage errors must be actionable; retried runs converge safely or stop clearly.
5. Negative security tests: no-token, wrong user, wrong tenant, wrong instance, wrong route/method, expired/replayed assertion, revoked subscription, missing entitlement, SQL injection/malicious declaration, attempted RLS bypass.
6. Restart/recovery: API in new process and host reboot, app container restart, DB restart, restore-from-backup in isolated acceptance environment.
7. Upgrade/rollback retains old healthy version until new candidate is healthy; schema migration/rollback is reversible or explicitly blocks unsafe rollback.
8. No externally published PostgreSQL or application ports; inspected network isolation and runtime least privileges.
9. The user-facing Runtime/Publisher UIs display `DEPLOYABLE`, `INCOMPATIBLE`, `DEPLOYING (stage)`, `ACTIVE`, `FAILED (code)` and authorized diagnostics accurately.
10. Legacy dashboard/static gateway routes and working CRUD deployments regressions remain green.

## 5. Definition of completion

**Development reliable-runtime accepted** only when tests above pass on the user environment, no app-specific bypass is required, and a fresh service start loads configuration automatically. **Production accepted** only after production ingress, durable secret management, distributed replay protection, storage quotas, backups/recovery, application-level RBAC, observability and deployment rollback testing pass in staging.

## 6. Implementation hygiene

- Preserve existing application data, versions, subscriptions and DB volumes.
- No raw business-data migration from Techtango; only supported app functionality/structure.
- No silent major-version promotion or automatic tenant upgrade. Offer/publisher versions are distinct from tenant baseline and running image.
- No Git commits/pushes until explicitly requested.
- Source changes must be targeted to the **latest installed files**. Project ZIP snapshots may be older than the user's local C1-C4 changes. Require exact current files for any installer that patches those components.

## 7. Immediate source baseline for first code increment

For C1-D1 specifically, retrieve current:

- `services/api/app/core/config.py`
- `services/api/app/main.py`
- `services/api/app/services/aaps_generic_runtime.py`
- `services/api/app/services/aaps_deployment_contract.py`
- `services/api/app/services/deployment_engine.py`
- `tools/check_c1c3_generic_readiness.py`

Also inspect current deployment/start scripts/services, if any, and `services/api/app/services/security_release_gate.py` before editing; avoid replacing existing runtime bootstrap. Add a clean machine/restart regression before calling the increment complete.
