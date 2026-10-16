# AUGMIS B1+B2 — practical, ordered acceptance runbook (11 October 2026)

**Purpose:** G01–G12 live acceptance, using only disposable test organizations/instances.

## A. What has already passed
- G01: `python -m pytest -q tools/test_b1b2_worker_safety.py` — `6 passed in 0.81s`.
- Static/runtime structural verifiers, Phase 4 RBAC matrix (121), publisher-owner integrity, Alembic head match.
- Previously inspected DB/Docker: `4` active deployments sampled, `3` mismatches. **Do not delete containers or edit DB statuses to make this report green.**
- Runtime Lab gateway HTML/CSS/JS/health/metrics/log/POST probes were demonstrated earlier.

## B. Before starting
1. Retain a verified PostgreSQL backup and Git checkpoint; test on localhost/isolation only. Use disposable tenants and publisher workspace. Never expose developer gateway/containers to the internet. Do not put secret values in environment-variable UI.
2. Start backend from repository root in terminal A using your normal AUGMIS uvicorn command; verify `http://127.0.0.1:8001/docs`.
3. Start frontend in terminal B:
   `cd D:\Uday_Documents\AUGMIS_PLATFORM\apps\web; npm run dev`
   Verify `http://localhost:3000/runtime` and `/tenant-applications`.
4. Use terminal C at `D:\Uday_Documents\AUGMIS_PLATFORM` to execute tests. PostgreSQL and Docker Desktop must be started. If a continuous upgrade worker is running, stop it for the tests.

## C. Gate G02 — mandatory preflight before mutations
From repository root:
```
python -m tools.b1b2_live_preflight --with-db --with-docker
powershell -NoProfile -File "<extracted kit>\03_readonly_checks\SHOW_PREFLIGHT.ps1"
python -m tools.runtime_upgrade_worker
```
Inspect every mismatch: DB deployment ID, instance ID, DB status and Docker status. Historical orphaned records may exist; document them. **Do not proceed with `--enqueue-and-run` if unexplained mismatches could affect the test instance, if there are queued unrelated jobs, or if another instance is upgrade-eligible.** A known, documented historical mismatch can be separately classified as not affecting disposable Test A, but strict G02 is not PASS until reconciled.

## D. Prepare fresh isolated test resources (G03-G08)
1. In Tenants, create `AUGMIS B1B2 TEST A` and `AUGMIS B1B2 TEST B`. Use owner roles authorized to manage each. Create a third/fourth disposable tenant for pinned/any policy scenarios if policy cannot safely be changed through a permitted API.
2. For TEST A, enable Publisher in Users/organization management if necessary (one publisher workspace per tenant). The default workspace is `<tenant name> Workspace`. A publisher admin/owner performs uploads.
3. In Publisher Center select the new test workspace. Choose `Upload Application` → `AAPS / Containerized`. Upload **only** `01_container_packages/AUGMIS_B1B2_ACCEPTANCE_1.0.0_BASELINE.zip`. Verify package validated; build the image; publish `1.0.0`.
4. Create and activate one offer with Hosted Dedicated / instance entitlement; use subscription policy `same_major`. In Marketplace choose TEST A as selected tenant and subscribe **once**. Confirm active subscription and `application.deploy` entitlement. Do not subscribe again or add a duplicate offer for the same tenant/application.
5. In My Applications under TEST A, launch the Acceptance Lab and confirm gateway reports v1.0.0 and healthy. In Runtime Control select its instance. Collect the instance UUID using authenticated `GET /api/v1/tenants/{tenant_id}/instances` on `/docs`. Store UUID in the record.
6. In TEST B create a non-platform user who belongs **only** to TEST B. Do not add them to TEST A. Test B can remain without this app until negative authorization checks finish.

## E. G03 — saved configuration injection
1. Runtime Control → TEST A → Acceptance Lab → environment variables. Add `APP_ENV=development` and `LOG_LEVEL=INFO`, save; refresh and confirm persisted.
2. Before restart, at repository root:
   `python -m tools.b1b2_verify_instance_environment --instance-id <INSTANCE_UUID> --with-docker`
   `[PENDING RESTART]` is expected if current deployment predates revision.
3. Restart the **disposable** instance via authorized Swagger: `POST /api/v1/instances/{instance_id}/restart` (no body unless Swagger schema requests one).
4. Rerun the verifier. PASS = snapshot matches saved revision and expected names/values reached Docker; no values displayed. Existing old deployment remains historical.

## F. G04 — quota with correct proof
1. With TEST A having no running container, set `Tenant container quota` to 1 as Platform Owner. If one is running, don't reduce below current usage; verify any change through permitted API.
2. Deploy permitted workload A (Acceptance Lab). Attempt a **separate, entitled application** as workload B (for example a second test app with its own active subscription), while A remains running.
3. PASS = B rejected by the **tenant runtime quota check** (inspect exact error), and A remains healthy. Do not attempt the same app twice under an offer allowing only one instance: that tests subscription/instance entitlement, not the tenant runtime quota.
4. Confirm a non-platform Tenant Owner/Operator gets HTTP 403 on `PUT /api/v1/tenants/{tenant_id}/runtime-quota` without `platform.settings.manage`.

## G. G05 — two-tenant negative authorization
Log in with the TEST B-only user (not platform_owner). Via authenticated Swagger attempt Test A:
- `GET` and `PUT /api/v1/instances/{id}/configuration`
- `GET /api/v1/tenants/{A}/runtime-quota`
- `GET /api/v1/tenants/{A}/upgrade-jobs`
- `GET /api/v1/deployments/{deployment_id}/logs`
- `POST /api/v1/instances/{id}/stop` or `/restart` (do not use a real third-party instance)
Every request must return 403 or 404 without state change. Attempt opening the TEST A container gateway without valid TEST A authorization. Never copy cookies, JWTs or secret env values into test evidence.

## H. G06 — healthy AUTO upgrade (only after G02/G05 clear)
1. While TEST A runs 1.0.0, upload `...1.1.0_HEALTHY_UPGRADE.zip` **as a new version of the SAME application in the same publisher workspace**. Build and publish 1.1.0.
2. In Runtime Control → Subscription upgrade readiness, select TEST A instance and enable auto upgrades. Verify policy `same_major` and current version 1.0.0. This requires an actor with tenant `subscription.manage`. **Consent alone does not run the worker.**
3. Run `python -m tools.runtime_upgrade_worker`. PASS planning only if exactly one eligible target equals TEST A instance and 1.1.0, and no unrelated queued jobs exist. Otherwise STOP.
4. In terminal C run `python -m tools.runtime_upgrade_worker --enqueue-and-run` **once**, only after explicit review; this changes Docker. Refresh Runtime Control and My Applications.
5. PASS = one job succeeded, new running version 1.1.0, health 200, old deployment retained as historical/archived logs. Record two container hostnames to prove replacement.

## I. G07 — unhealthy candidate rollback/preservation
1. Only after G06, upload `...1.2.0-UNHEALTHY_FAILED_UPGRADE.zip` as same app, build/publish. This candidate's `/health` returns 503 deliberately.
2. Dry-run; confirm sole planned target is 1.2.0 for TEST A. Confirm no other eligible jobs/instances. Execute single `--enqueue-and-run` iteration.
3. PASS = job failed or quarantined as `needs_reconciliation` if outcome uncertain; v1.1.0 gateway still returns healthy/200; no zombie running candidate, or reconcile if reported. Capture job status and old/new deployment history. Do not repeatedly run worker against the failed candidate.

## J. G08 — policies
- `same_major`: 1.0→1.1 permissible; 1.x→2.0 not eligible.
- `pinned`: new test tenant with a single offer/subscription pinned to an existing published version; opt-in doesn't permit version move.
- `any`: **separate** disposable test tenant with one active subscription and policy any; start on 1.x and use healthy 2.0.0 as latest candidate; allow 2.0 only if authorized and entitled. This test must not re-use a tenant with two simultaneously active subscriptions for the same app.
- Create policy-specific test offers/subscriptions from authorized UI/API; do not edit database rows directly. If the UI doesn't expose required policy configuration, record a test-enablement gap.
- *WARNING:* Publisher versions are immutable and retiring is not reversible. Do not retire 1.1 or other test versions before these tests.

## K. G09 — lifecycle logs
1. On a disposable running container click `Write test log` in the Lab. Confirm container output is present under authenticated `GET /api/v1/deployments/{old_deployment_id}/logs`.
2. Stop and restart using authorized instance lifecycle routes in Swagger. Verify previous deployment logs are returned with source archived when a snapshot was obtained, while the new deployment is healthy.
3. A missing Docker log snapshot may be reported as best-effort, not guaranteed archival. Record it as a limitation, not a fabricated PASS.

## L. G10 — uncertain job/crash test (isolated environment ONLY)
- Baseline test: the included `tools/test_b1b2_worker_safety.py` already passed 6/6, proving the fail-closed code paths.
- Live sign-off needs a dedicated disposable copy of PostgreSQL and Docker on a separate test environment; simulate worker interruption, inspect job state, run read-only preflight, confirm reconciliation required, and no automatic retry. **Do not kill or crash the shared AUGMIS development worker** to force a result. Without isolation, record G10 live as PENDING (not PASS).

## M. G11 — static package tests
1. Publisher Center → Upload Application → Static Web Application. Upload `02_static_packages/AUGMIS_B1B2_STATIC_VALID_MULTI_ASSET.zip`. Confirm index.html loads with CSS, JS and nested `images/check.png`; click button to confirm JS works.
2. Upload each `STATIC_INVALID_*.zip` in the same **Static Web** mode. Expected failure: missing index, `../` path traversal, symlink and forbidden file extension.
3. No rejected archive may write outside its quarantine/extract directory. If any unsafe archive is accepted, record FAIL and stop; do not deploy it.

## N. G12 — regressions and closeout
From repo root:
```
python -m compileall -q services/api/app tools
python -m pytest -q tools/test_b1b2_worker_safety.py
python -m tools.verify_b1b2_runtime
python -m tools.verify_b1b2_upgrade_controls
python -m tools.verify_runtime_control_catalog_batch
python -m tools.verify_b1_runtime_safety
python -m tools.verify_phase4_rbac_matrix
python -m tools.verify_publisher_owner_integrity
alembic current
alembic heads
```
Stop `npm run dev` before running release build if they share Next output directory; from `apps/web`:
```
npx tsc --noEmit
npm run build
```
Finally in repo root: `git diff --check`; record version IDs, instance UUID, outcome and screenshots. All 12 gates must pass to call B1+B2 accepted; document any environment limitations. Do not publish developer runtime to internet; shared sessions/private networking/secrets remain production blockers for B3.
