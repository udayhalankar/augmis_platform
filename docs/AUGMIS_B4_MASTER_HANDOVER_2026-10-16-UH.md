# AUGMIS SaaS — B3/B4 Project Handover and Continuation State

**As of:** 16 October 2026  
**Workstream:** AUGMIS platform control plane + Techtango AI Builder integration + 21AugDashboard isolated container runtime  
**Primary repo:** `https://github.com/udayhalankar/augmis_platform`  
**Local repo:** `D:\Uday_Documents\AUGMIS_PLATFORM`  
**Current branch used:** `main` (verify before every commit)  
**Prior verified GitHub checkpoint:** `97f026b` — `checkpoint: AUGMIS B1-B4 secure runtime and Techtango integration`  
**New GitHub checkpoint:** **PENDING** — user requested new commit/push; record actual SHA only after `git push` succeeds.  
**Purpose of this document:** Durable Project Source handover. This is a dated snapshot, not proof of newly completed tests. Use alongside canonical architecture and current repository code. Do not override newer evidence or project instructions.

## 1. Executive status (read this first)

- The **Techtango Tenant 1 → AUGMIS ABC Engineering Secure** tenant link was verified using independently signed proof. Techtango `21augdashboard` immutable **metadata-only** snapshot was staged in AUGMIS; this did **not** export customer rows or create a runnable application.
- A separate **read-only standalone `21AugDashboard` Docker pilot** has been built, secured and tested with tenant-scoped PostgreSQL, Ed25519 assertions, internal Docker networking, and a temporary loopback-only relay. Synthetic signed HTTP and loopback tests passed.
- The actual `21AugDashboard` is now **registered, built, published**, has an **active offer**, and ABC Engineering Secure has an **active subscription and `application.deploy` entitlement with maxInstances=1**.
- The new **guarded two-phase instance provisioning** backend patch is installed; **95 regression tests passed, 1 Windows symlink test skipped**. The guard evaluated `True` in the configured Python shell and a Uvicorn server was restarted from that environment (port 8001, PID at test time 32024; PID is not durable).
- One **real** application instance was successfully **reserved** with `PENDING_SECRETS`, and **per-instance Ed25519 and restricted database password files were provisioned outside the repository**. No container was started by the reservation or secret-provisioning steps.
- **CURRENT BLOCKER (do not gloss over):** `Check-AUGMIS-B4-Instance-Preflight.py` passed identity, key matching, image, network and private PostgreSQL-container checks, but stopped on **`Private DB test failed: check the password, Docker mount permissions, and network DNS`**. It has **not passed the actual restricted DB login from the temporary non-root client**. Root cause remains unknown. Do not activate the reserved instance until that check passes and managed-ingress/live-authorized-launch prerequisites are verified.
- Three older **failed** instance/deployment records remain for audit. They failed under the legacy Open Application path with `WinError 10061` localhost health-check connection refused. Do not retry the legacy Open Application path or manually delete/change those records.
- **New scope request:** Build a reusable **AUGMIS App Containerization Tool** integrated into existing Publisher Center, rather than custom hand packaging. See the companion `AUGMIS_APP_CONTAINERIZATION_TOOL_SCOPE.md`.

## 2. Current authoritative identifiers

> IDs are *identifiers*, not passwords. Do not paste access tokens, database passwords or signing private keys into project sources.

| Object | Identifier / value | State |
|---|---|---|
| AUGMIS tenant | `b6e8ccbc-aefb-4a4d-8955-1434dc1213d7` | ABC Engineering Secure |
| Techtango tenant | `1` | Verified link to above AUGMIS tenant |
| Techtango tenant-link ID | `ee934e10-50cf-45ef-968b-61cbd443cb85` | `verified` |
| Techtango source slug | `21augdashboard` | Published source application |
| Techtango metadata snapshot ID | `ee92171f-f737-4be3-b0a8-27dc29628ff0` | `staged_metadata_only` |
| Metadata snapshot digest | `5da4ec1e7194523b70107b4daaf8ffe2faec591c46631e4e2ae027021f4675e0` | Immutable metadata snapshot (NOT AAPS ZIP) |
| AUGMIS application ID | `09e2ccc5-9b9a-4146-9ba3-b72517e78e68` | Published |
| AUGMIS app key | `techtango-21augdashboard` | 21AugDashboard — Standalone Pilot |
| AUGMIS version ID | `af0749e3-21dd-43aa-9c5a-8f01d26a3da9` | Version `0.1.0`, `image_ready`, `published` |
| AUGMIS package ID | `abe2f184-e9be-4977-88aa-03a5a07435bb` | Validated AAPS package |
| AAPS registration ZIP SHA-256 | `32f0135373727898ee0dde749abf31b9b59c37f9c8f20ecfe095c8136933edb6` | Actual registered candidate |
| AUGMIS build ID | `18f3177a-066e-4e57-8f1b-80d6bfd1903e` | `ready` |
| Published built image ref | `augmis.local/atlas-development-qa/techtango-21augdashboard:0.1.0` | Docker exists locally |
| Published image immutable ID | `sha256:8e4b4206a87199b531919b56cf861d33a26976545e694dbcfd9d3e8c84865db7` | Approved pilot reference; non-root `10001:10001` |
| Earlier standalone build-only image | `augmis-21augdashboard:pass3h-build-only` | Earlier build, not authoritative published digest |
| Local registration-candidate build image | `augmis-21augdashboard:3h5e-registration-candidate` | Digest differs from Publisher Center image; do not interchange |
| Relay image ref | `augmis-dashboard-dev-relay:3h5d` | Built |
| Relay image immutable ID | `sha256:0c489822231ff957b057c39813480d320a3ee9844f94d05f8262e63e055914b1` | Non-root `10002:10002` |
| Commercial offer ID | `66841920-1b87-4b67-aa46-6ce489c854bc` | Active; `hosted_dedicated`; `same_major` |
| Offer key/name | `contanarised-app` / `contanarized-app` | Spelling in records is intentional historical value; do not silently rename |
| Subscription ID | `50101616-2cdf-44f5-a3f7-ac615c489779` | Active for ABC Engineering Secure |
| Subscription baseline version | `af0749e3-21dd-43aa-9c5a-8f01d26a3da9` | Version policy `same_major` |
| Subscription entitlement | `application.deploy`: `active`, `{"maxInstances":1}` | Active |
| **Reserved live instance ID** | **`cf33d8fa-a8f8-4281-b68b-421d6d28ec73`** | **`PENDING_SECRETS`; do not repeat reservation** |
| **Reserved deployment ID** | **`6f23c55f-0027-40c4-acc9-226b9b54a41b`** | `runtimeStarted=False` at reservation |
| Private Docker network | `augmis-dashboard-private` | `bridge`, `Internal=true` |
| Private PostgreSQL container | `augmis-21augdashboard-postgres-dev` | Running, host port NOT published |
| Private PostgreSQL network hostname | `augmis-dashboard-db` | Port 5432 inside private network |
| Private PostgreSQL database | `augmis_app_21augdashboard_dev` | Separate from `augmis_platform` control-plane DB |
| Restricted PostgreSQL role | `augmis_21augdashboard_dev_runtime` | LOGIN, reader membership, no superuser/CREATEDB/CREATEROLE/BYPASSRLS |
| AUGMIS local API | `http://127.0.0.1:8001` | Windows FastAPI; PID may change |
| AUGMIS frontend | `http://localhost:3000` | Next.js control plane |
| Techtango development service | `http://127.0.0.1:5000` | Node.js, separate service |

**Three legacy failed instances for this application** (all associated with ABC Engineering Secure and version `0.1.0`):
- `6d858455-71a8-4d71-83d1-0345ec6322ff`
- `c6b8e9ab-a585-42e2-8ca4-453d56c10af6`
- `ad18aee6-b5d2-4401-aeba-4ec2028f78a6`

Each had a failed/unhealthy deployment with `Application health check failed: <urlopen error [WinError 10061] No connection could be made because the target machine actively refused it>`. Keep these as audit data until reviewed under the normal lifecycle. They do not prove the new two-phase path failed.

## 3. Architecture and security constraints

```
Techtango AI App Builder (source authoring, port 5000)
   -> signed tenant verification and metadata-only staging
AUGMIS Publisher Center (Next.js :3000)
   -> FastAPI control plane (Windows :8001)
   -> publisher application/version/package/build, offer, subscription,
      tenant authorization, entitlement and instance lifecycle
   -> signed gateway runtime assertion + controlled local relay ingress
        -> dedicated read-only dashboard container (Docker private network)
             -> private PostgreSQL 15 (no Windows-published DB port)
```

Rules:
1. Preserve **backend-authoritative** tenant membership, RBAC, `application.deploy`, maxInstances and B3 security release gate.
2. Techtango and AUGMIS data are different trust domains. Verified mapping does not authorize copying live customer rows; metadata staging is NOT a runnable export.
3. Do not directly expose the dashboard or PostgreSQL from the Docker internal network. The tested relay is loopback-only development transport and NOT yet production-grade ingress. The gateway must remain authoritative for user/tenant/instance authorization.
4. Dashboard validates **short-lived Ed25519 signed claims** independently; do not accept browser-supplied tenant IDs or forged identity headers.
5. Keep the Ed25519 **Techtango proof keys** separate from **per-instance AUGMIS gateway signing keys**. Signing private keys remain on trusted host, public verification key in dashboard container read-only.
6. Password is file-mounted, not baked into the image or passed on command line; least-privilege DB role; RLS `ENABLE + FORCE` verified, tenant1/tenant2 isolation tests and zero rows after rollback completed.
7. Do not modify `apps/web/src/app/providers.tsx`, duplicate AppShell/TenantProvider, or create parallel authorization pipelines; follow canonical AUGMIS project instruction documents.
8. Immutable image digest pinning and per-instance tenant/application/instance identity must be checked again immediately before activation.
9. No production-ready claim until a separate production ingress, credential lifecycle, revocation and operational test review.

## 4. Work completed (chronological milestones)

| Phase | Verified accomplishment | Remaining caution |
|---|---|---|
| B3 / B4 Pass 1 | Tenant mapping API rejects unauthorized/duplicate/wrong input; persisted Techtango Tenant 1 → AUGMIS tenant mapping | Initially pending until independently proved |
| B4 Pass 2 | Ed25519 tenant proof verified; mapping status `verified`; staged immutable `21augdashboard` schema metadata; rejected forged, mismatched, expired and duplicate proofs; persisted nonce IDs in PostgreSQL | No executable export or data copy |
| B4 Pass 3A–3B | Inspected published Techtango dashboard, `advanced-dashboard` mode, source table and backend/frontend dependencies | Analysis-only; source not independently packaged at that stage |
| B4 Pass 3C | Tenant-scoped isolated dashboard adapter, 11 unit tests | Not a live HTTP runtime yet |
| B4 Pass 3D | Dedicated dev DB schema/RLS provisioning, 17 contract tests and SQL rollback verified | No source business data copied |
| B4 Pass 3E | Restricted role, real PostgreSQL adapter, read-only smoke; isolated DB rows = 0 | Windows role and separate Docker DB are different DB instances |
| B4 Pass 3F | Standalone FastAPI HTTP runtime and signed assertion verifier; 34 tests + 13 subtests passed | Synthetic identity at this phase |
| B4 Pass 3G | Host gateway assertions and security tests; post-patch 29 pass with test path configured | Pilot gated off by default |
| B4 Pass 3H / 3H2 | Validated AAPS build-only ZIP, Docker image built under UID 10001; secure-mount development guard tests | Build-only ZIP not final registration artifact |
| B4 Pass 3H3–3H5A | Private Docker PostgreSQL 15 created on internal network with no published host port; RLS isolation tests with rollback; restricted password login and container-to-DB smoke | Used a restricted development database |
| B4 Pass 3H5B | Actual dashboard Docker peer signed HTTP; valid Ed25519 yields `Card=0, Chart=[]`; invalid/missing/expired/wrong identity denied | Synthetic identities, not real AUGMIS launch |
| B4 Pass 3H5C | Windows localhost → temporary relay → internal Docker dashboard; full signed/negative-case HTTP smoke passed | Relay is development-only and no real app identity |
| B4 Pass 3H5D | Guarded managed ingress deployment code, relay lifecycle, tests; `86 passed, 1 skipped`; built non-root relay image | Activation kept OFF; production gate unchanged |
| B4 Pass 3H5E | AAPS `0.1.0` final registration candidate validated, exact candidate Docker build passed, uploaded via Publisher Center | Package registered immutably; no silent changes to `0.1.0` |
| B4 Pass 3H5F | Application built in Publisher Center (`image_ready`), SHA-guarded two-phase reservation/activation/cancel patch installed; `95 passed, 1 skipped` | This is source-level, not a successful actual launch |
| B4 Pass 3H5G | App published; active hosted-dedicated offer; ABC Engineering Secure subscribed, entitlement `maxInstances=1` | Subscription confirmed from SQL |
| B4 Pass 3H5H | Exact two-phase endpoints present in OpenAPI; Python guard `True`; FastAPI relaunched with guarded env; real instance reserved `PENDING_SECRETS` without Docker | Old Open Application had previously created three failed instances |
| B4 Pass 3H5I | Created per-instance signing key/public key and DB password file with restrictive ACL outside source tree; preflight partly passed | **STOP: restricted PostgreSQL probe failed. No activation.** |

## 5. Current B4 code files that must be preserved

**Existing files modified by patches** (as last observed; inspect current `git status`):

- `services/api/app/services/deployment_engine.py` (managed ingress lifecycle)
- `services/api/app/routes/instances.py` (reserve/activate/cancel endpoints + pilot legacy path block)
- `tools/test_b4_pass3h2_secure_mounts.py` (regressions)

**New files** (expected untracked until the requested Git commit):

- `services/api/app/services/dev_dashboard_ingress.py`
- `services/api/app/services/dashboard_instance_reservation.py`
- `tools/b4_dashboard_dev_ingress_relay/` (Dockerfile, relay server, .dockerignore)
- `tools/test_b4_pass3h5d_managed_ingress.py`
- `tools/test_b4_pass3h5d_relay.py`
- `tools/test_b4_pass3h5f_reservation.py`

**Previously committed secure runtime modules** include:

- `services/api/app/services/dashboard_runtime_mounts.py`
- `services/api/app/services/dashboard_runtime_assertions.py`
- `services/api/app/services/security_release_gate.py`
- `tools/test_b4_pass3g_runtime_assertions.py`
- `tools/test_b3b4_security.py`

**Working local helper scripts outside Git repo** (not source files to commit):

- `D:\Provision-AUGMIS-B4-Instance-Secrets.py`
- `D:\Check-AUGMIS-B4-Instance-Preflight.py`
- `D:\B4_PASS3H5F_PATCH\apply_b4_pass3h5f.py`
- `D:\B4_PASS3H5D_PATCH\apply_b4_pass3h5d.py`

## 6. Last verified tests and honest acceptance

- Pass 3H5D managed ingress + related regressions: **86 passed, 1 skipped** (Windows symlink test requires developer mode).
- Pass 3H5F two-phase provisioning + managed ingress + B3/B4 regressions: **95 passed, 1 skipped**, zero failures; symlink skip is known on Windows.
- Live internal peer signed HTTP: success, including valid assertion to empty dashboard and invalid claim rejections.
- Live Windows loopback relay signed HTTP: success, including negative cases, `Card=0, Chart=[]`.
- Publisher Center app upload/build/publish: success, distinct registered application/version/package/build IDs.
- Tenant ABC entitlement: verified active, `maxInstances=1`.
- Real reserve API: **success**, returned instance `cf33d8fa-a8f8-4281-b68b-421d6d28ec73`, `PENDING_SECRETS`, `runtimeStarted=False`.
- Secret generation: success, file ACL and public/private key matching checked by initial contract preflight.
- **Latest local read-only preflight:**
  - PASS: real tenant/application/instance IDs, matching Ed25519 keys, expected secret layout.
  - PASS: immutable image approved and UID `10001:10001`.
  - PASS: internal Docker network.
  - PASS: private Docker PostgreSQL running with no published port.
  - **STOP: `Private DB test failed: check the password, Docker mount permissions, and network DNS`.**
  - Therefore: password authentication/readability from *that specific non-root temporary client* and least-privilege SELECT/RLS assertions are **NOT YET ACCEPTED** by this preflight. No activation attempted.
- The preflight used a disposable non-root `postgres:15` client with a bind-mounted `db_password` and `psql`; its failure category is broad because the script intentionally redacts Docker stderr. **Do not assume which cause occurred without a targeted safe diagnostic.**

## 7. Next work, in strict order

### Immediate (B4 3H-5I continuation)

1. **Commit source checkpoint to GitHub** after staging only audited source/test files (do not stage keys or `.env`). Capture commit SHA in this handover. Pushing source is independent of the failing database preflight; do not say live runtime is accepted.
2. Diagnose **read-only private DB preflight** failure *without printing credentials*. Check on-host existence and ACL of per-instance secret files, non-root Docker mount readability, exact private network/DNS membership, and credentials against the *private Docker PostgreSQL* (not Windows host PostgreSQL). Use a safe status-only test and inspect sanitized categories; do not regenerate or replace secrets indiscriminately.
3. Re-run `Check-AUGMIS-B4-Instance-Preflight.py`; require the final **SUCCESS** before proceeding.
4. Independently verify new host FastAPI process environment has appropriate **explicit** pilot flags plus `AUGMIS_DASHBOARD_SECRET_ROOT`, `AUGMIS_DASHBOARD_ASSERTION_PRIVATE_KEY_FILE`, `AUGMIS_DASHBOARD_APPROVED_IMAGE_ID`, `AUGMIS_DASHBOARD_PRIVATE_NETWORK`, `AUGMIS_DASHBOARD_DB_HOST`, `AUGMIS_DASHBOARD_DB_PORT`, required approved relay image/digest and ingress network (use actual code contract). Do not paste private key/password values into chat.
5. Inspect the reserved instance and subscription/entitlement via read-only API/SQL before activation. Avoid creating any additional instances; keep three failed legacy records for audit. Verify reserve/activate/cancel route guards, operator stop gate, and capacity behavior.
6. Verify the image digest and managed relay configuration preflight, and implement any missing gateway signing-key/relay provisioning steps based on canonical code rather than guessing environment variables.
7. Call **activate-reserved** only after all checks pass, once, using an authorized token; inspect result and gateway health and failure cleanup. Verify browser runtime routes under the correct AUGMIS tenant and application (NOT the separate `localhost:3011/customapps` Tenant Alpha site).
8. End-to-end negative cases: unauthorized, wrong tenant, wrong app/instance, expired/replayed assertion, subscription revoked, maxInstances, stale image, missing secret, stop/restart, relay cleanup, no DB host port, no secret leaks, graceful cancellation. Revisit old failed instances only through standard audited lifecycle.
9. Commit next separately accepted runtime fixes once tested, update this handover with the new commit SHA and acceptance result.

### Wider pending AUGMIS scope

- Production ingress (replace dev loopback relay as needed): isolated trusted network, process-bound service authentication, TLS/mTLS/socket strategy, revocation, rate limiting, supervised recovery, monitoring, audit, host policy, no accidental bypass of B3 gate.
- Finish B3 release/security hardening and full frontend lint/RBAC acceptance; these were never closed by a synthetic runtime smoke test.
- Techtango **real source export** / dependency bundle contract, not only metadata snapshot; containerize supported app modes without copying live data or secrets.
- Generic **App Containerization Tool** integrated into Publisher Center (see companion detailed scope file); user explicitly requested this addition.
- Wider platform Phase 4 tenant users/RBAC work, as tracked in `AUGMIS_PHASE4_RBAC_TRACKER.md`; source project state from 2026-10-04 predates B4 and should not be treated as the latest B4 status.
- UX: eventually support a safe "Reserve / Provision / Activate" operator workflow and explain why ordinary Open Application is blocked for an unprovisioned pilot; do not add duplicate global context/providers.

## 8. Secrets and local resource handling

**NEVER upload, print or commit:** Techtango proof private key; AUGMIS per-instance `*-gateway-private.pem`; `db_password` files; `.env` or production connection strings; access or refresh tokens; database dumps; raw archived Docker logs without redaction; raw certificates/keys; signing-key backups.

Local locations are user-scoped and should be used for configuration **only**, not copied into Project Sources:

```
%USERPROFILE%\augmis-b4-runtime-secrets\<AUGMIS_TENANT_UUID>\<INSTANCE_UUID>\db_password
%USERPROFILE%\augmis-b4-runtime-secrets\<AUGMIS_TENANT_UUID>\<INSTANCE_UUID>\assertion_public.pem
%USERPROFILE%\augmis-b4-dashboard-signing-keys\<INSTANCE_UUID>-gateway-private.pem
```

The staging helper writes the DB password file after asking for the restricted **Docker private PostgreSQL** login password. A file being created successfully does NOT prove that the stored password is correct or that non-root Linux Docker can read its Windows bind mount.

## 9. GitHub checkpoint procedure (only on user's Windows workstation)

From `D:\Uday_Documents\AUGMIS_PLATFORM`, inspect branch and working tree. Stage only the B4 3H5D + 3H5F files listed in Section 5. Run `git diff --cached --check`, review `git diff --cached --name-only`, check for hardcoded secrets, commit with:

`git commit -m "feat(b4): add guarded ingress and two-phase instance provisioning"`

Then `git push origin main`, followed by `git log -1 --oneline` and `git status --short`. No forced push. **The preceding commands must be run by the user; this handover does not claim a push occurred.** Save actual SHA to the header after success. The prior known pushed baseline was `97f026b`.

## 10. Acceptance definition — current next finish line

The first *real* `21AugDashboard` pilot is accepted only when: (a) per-instance secret read and private DB RLS checks pass; (b) the reserved instance can activate once using normal RBAC/subscription/entitlement checks; (c) approved published image and approved relay are pinned and non-root; (d) private DB/dashboard have no direct host port; (e) AUGMIS gateway issues valid app/tenant/instance-scoped Ed25519 assertions; (f) authorized ABC Engineering Secure session reaches correct dashboard; (g) unauthorized/mismatched/expired requests fail closed; (h) instance and relay lifecycle, cleanup and audits work; and (i) no regression in other apps. Anything short of this must be marked as partial or blocked, not complete.

---
**Next conversation starting prompt:** "Continue AUGMIS B4 from `AUGMIS_B4_MASTER_HANDOVER_2026-10-16.md`. The real `21AugDashboard` instance is reserved (`cf33d8fa-a8f8-4281-b68b-421d6d28ec73`) and secret files were created, but the read-only non-root Docker PostgreSQL preflight stopped at private DB test failed. Do not activate, reserve again, alter secret files, or bypass entitlements. First verify the Git commit state and diagnose this failure without leaking credentials; then continue guarded launch acceptance. Include the planned App Containerization Tool in backlog." 
