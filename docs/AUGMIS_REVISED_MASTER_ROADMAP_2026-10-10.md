# AUGMIS — Revised Master Development Roadmap
**Baseline date:** 2026-10-10
**Status vocabulary:** Verified = tested evidence in project conversations; Foundation = partial implementation; Unverified = not yet established by evidence; Planned = requires implementation; Deferred = deliberately excluded for now.

> Planning document, not a certification of production readiness. Repository-level reality should be audited at the beginning of each implementation batch. The Project State and Phase 4 tracker provided to ChatGPT were dated 2026-10-04 and may omit subsequent work.

## 1. Corrected nomenclature

The earlier roadmap used **Phase 5** for two separate streams: Containerized Application Runtime and Audit & Governance. Preserve both explicitly:

- **Phase 5A — Audit & Governance**, currently implemented for local/development usage; end-to-end negative security tests and formal retention/legal-hold/archival decisions remain.
- **Phase 5B — Container Runtime Completion**, the important unfinished portion of the originally scoped Phase 5 container work.
- **Phases 6–11** retain their original names, with early CI/security fundamentals included in every batch rather than postponed to their dedicated later phases.

## 2. Baseline snapshot

### Demonstrated or supported by project tests
- FastAPI / PostgreSQL / Alembic backend, Next.js/MUI control center, JWT and tenant/publisher membership RBAC.
- Tenant Users and invitation lifecycle, publisher management/permissions, ownership link and one-workspace-per-tenant database rule.
- Publisher workspace activation names default to `<Tenant account name> Workspace` for newly activated workspaces.
- Applications, version and package models, build/deployment models, offers, subscriptions, entitlements, instances and development runtime pathways.
- Static single-file and ZIP upload paths have been tested; standard package manifest validation rejects invalid uploads.
- RBAC matrix (121 assertions), publisher integrity, audit verification tools, Next.js build and Alembic revision consistency passed recently.
- Audit Center has personal/tenant/platform scopes, filtering, event display, CSV and evidence JSON export controls; a live 190-record JSON export passed SHA-256 manifest verification.
- 365-day retention *assessment only*, with 188 events assessed and none over threshold in the reported run; no purge enabled.

### Must not be assumed complete
- Production container restart, lifecycle reconciliation, log streaming, CPU/memory quotas, configuration and secret injection, secure networking, upgrades/rollback, Redis/shared runtime sessions, WebSocket/SSE.
- Complete event-by-event audit instrumentation for every runtime and upgrade action; live cross-tenant negative export checks and audit-export event validation.
- General multi-asset static application contracts and security scans.
- Production-grade scheduler for auto_upgrade, CI/CD checks, user-level application entitlements, billing, invoicing, payments or commercial metering.
- Legal-hold enforcement, validated external immutable archives, approved purge/retention policy.

### Deliberate decisions
- **One organization (tenant), with Subscriber and optionally Publisher capabilities; at most one publisher workspace per tenant.** A publisher creates offers; a subscriber creates subscriptions. An organization can do both.
- **Legacy publisher `Infomentica` and `Infomentica Platform` ownership resolution is deferred.** The user intends a fresh **development/test data** reset; do not merge or rewrite either publisher. Preserve schemas/migrations, base roles and protected accounts. Back up before any reset.
- **Application runtime is not production-ready merely because development deployments operate.** Security gates remain mandatory.

## 3. Phase-by-phase implementation plan

### Phase 5A — Audit & Governance: closure of development acceptance
**Current:** Local automated technical verifications passed; production governance incomplete.

**Carry-forward:**
1. Live CSV download and downloaded-content validation; live negative 403 tests for tenant and platform audit export endpoints; cross-tenant ID tampering tests.
2. Check export actions appear in the audit log, including actor, scope, filters, count, checksum and outcome. Verify failed exports are auditable without leaking records.
3. Event coverage matrix: application uploaded, version built, application published/retired, offer activated, subscription created/suspended, application opened, instance deployed/upgraded/stopped, rollback. Mark missing emitters and implement them in their owning service.
4. Approve retention duration by legal/contractual jurisdiction. Define hold, archive, retrieval, restore, authorized purge and evidence-access controls before enabling deletion.
5. Retain auditable release-evidence checks and no false claim of tamper-proof archive: SHA-256 is integrity detection, not signing, notarization or WORM.

**Exit:** All enumerated important actions are traceable in UI and export, scope authorization is verified live, limitations documented. Full legal-hold and archiving implementation can remain a **production-launch blocker** if formally excluded from development closure.

### Phase 5B — Containerized Application Runtime Completion (next)
**Current:** Models and portions of upload/build/deploy, instance lifecycle and runtime gateway exist. Production completeness unverified.

**Work packages:**
- **R1 Package/image publication:** trusted immutable package manifests, validated container image digest, image registry permissions, checksums and artifact provenance; no mutable tags as deployment identity.
- **R2 Build lifecycle:** deterministic state machine (queued/building/validated/failed/published), async build workers, retry semantics, output logs, idempotency and recovery after worker crash; never run arbitrary publisher build steps in privileged control-plane process.
- **R3 Instance lifecycle:** deploy, start, stop, restart, terminate and status reconciliation between desired state and actual container state; explicit transitional/failure states and audit trail.
- **R4 Tenant isolation:** tenant-scoped instance ownership, unique runtime identity and authenticated entitlement checks; deny cross-tenant access at API and gateway layers.
- **R5 Health/observability:** startup/readiness/liveness checks, bounded logs, monitoring, structured request/build/deployment correlation IDs, health-aware rollouts.
- **R6 Configuration:** tenant/instance-scoped runtime variables, versioned non-secret config with redaction; secrets by reference with encryption/secure injection and no leakage in UI/logs/manifests.
- **R7 Quotas:** platform/tenant limits for instances, CPU, memory, storage, network and package size; authoritative enforcement at runtime, not only offer metadata.
- **R8 Gateway:** tenant authorization, HTTPS/subdomain routing, private runtime network, safe health probe access, headers/timeouts; hardening must precede any externally accessible container.
- **R9 Manual upgrade/rollback prerequisites:** immutable deployable version, previous healthy deployment retained, health gates and reversible cutover.

**Exit:** Given two tenants and two versions, authorized lifecycle actions work end to end, survive restart/reconciliation, enforce quotas and secrets boundaries, isolate tenants, and recover from failure without data leakage.

### Phase 6 — Complete Version & Subscription Automation
**Current:** `same_major`, `pinned`, `any`, `auto_upgrade` are stored; automated background upgrade worker not established.

**Implement:** durable queue/scheduler, publication event trigger, eligible subscription/entitlement discovery, upgrade plan/dry run, policy checks, idempotent attempt records, locks/concurrency controls, staged deployment, health gate, switch traffic, failure rollback, alerts and auditable outcomes; optional maintenance windows and upgrade pause.

**Policy test matrix:**
- 1.0.0 → 1.1.0 allowed with `same_major`.
- 1.x → 2.0.0 denied with `same_major`.
- Pinned stays pinned regardless of `auto_upgrade`.
- `any` allows valid upgrades where entitlement permits.
- `auto_upgrade=false` never triggers unattended deployment.
- Health failure or timeout rolls back to last healthy deployment and records outcome.
- Duplicate publication events do not create duplicate upgrades; retry/restart is safe.

**Exit:** An eligible published version upgrades a healthy authorized instance without manual operator steps, and a failed upgrade returns traffic to the last known-good version.

### Phase 7 — Universal Application Packaging
**Current:** Single-file static HTML and some static ZIP/standard package validation exist; production-grade multi-asset delivery unverified.

**Implement:** multi-asset static ZIP index+CSS+JS+images+assets; immutable digest/version identity; validate manifest/AAPS contract; entrypoint and MIME rules; zip-bomb/path traversal/symlink prevention, size/depth/file count limits, malware scanning hook, CSP/security policy, tenant/runtime session path resolution, correct relative assets, cache/version isolation. Container contracts should declare start command/ports/probes/resources and build metadata without unrestricted host access. Add sample apps and malicious package fixtures.

**Exit:** Real multi-file static projects and diverse container technologies publish and run through the same immutable package contract with adversarial input validation.

### Phase 8 — Production Runtime Security
**Current:** Development gateway and isolated runtime pathways; memory-only session stores previously identified (`_RUNTIME_GATEWAY_SESSIONS`, `_STATIC_RUNTIME_SESSIONS`) and direct development host ports require revalidation against current code.

**Implement:** Redis/managed shared TTL session storage with revocation and instance binding; TLS/HTTPS-only secure cookies and trusted proxy policy; private container network/no public host ports; domain/origin isolation, per-app CSP, auth/callback protections, short-lived tickets, rate/request-size/timeouts, WebSocket/SSE with explicit authorization, CPU/memory/pids/capability controls, rootless/least privilege where supported, seccomp/network egress controls, secrets/KMS, image scanner/signing, supply-chain trust, audit/security alerting, automated penetration and tenant-isolation tests.

**Exit:** Multiple API workers and a server restart preserve valid sessions appropriately and reject revoked sessions, and runtime containers cannot reach other tenants' data or public host ports. Production security sign-off required.

### Phase 9 — CI/CD & Release Engineering
**Early foundation (do now):** GitHub Actions on PR/push: Python import + pytest, migration check, TypeScript/ESLint/Next build, package validation, dependency scan, minimal permission smoke tests and secrets scanning; branch protection.

**Complete phase later:** reproducible container image, SBOM/provenance, staging deployment, smoke + integration tests, manual production approval, database migration rollback/forward strategy, tagged releases (v0.x.y), environment secrets, automated backup verification, staged rollouts and rollback.

**Exit:** A clean commit builds, tests, signs/releases and deploys to staging deterministically; deployment to production requires gated approval and can be safely reversed.

### Phase 10 — AUGMIS / Techtango Integration
**Current:** Main Techtango integration not yet proven end to end; protect the working `00_TechtangoRJS` code.

**Implement:** publish contract/API from AI Builder to control plane → build/validate/publish immutable version → publisher creates offer → tenant subscribes/entitlement → secure app launch in `/customapps`; SSO/user-tenant context and launch token binding; usage/open events; server-side favorites keyed by (`user_id`, `tenant_id`, `application_id`) with unique constraint and secure REST endpoints; landing-page favorites, revocation and cross-tenant tests.

**Exit:** An AI-built application is published once and launched from the existing Digital Workplace by an entitled tenant user without duplicating the platform in Techtango.

### Phase 11 — Billing & Commercial Marketplace
**Current:** Offer/subscription/entitlement, active/retired offers, subscription lifecycle and instance limits exist in development. Payment, invoicing, metering and complete fulfillment are not established.

**Separate concepts:** offer/plan + delivery method (hosted, downloadable, enterprise) + billing cadence (monthly, annual, one-time) + rating meter (flat, per-seat, per-instance, usage) + discounts/trials/taxes/currency + contract terms.

**Required supported commercial models:**
1. Hosted Monthly: recurring monthly entitlement and payment, suspend/grace handling.
2. Hosted Annual: recurring annual entitlement, renewals and proration rules.
3. Free: zero-price plan with quota and abuse limits.
4. Trial: start/end, expiry, one-trial policy, conversion and cancellation behavior.
5. One-time Download: purchase entitlement, signed expiring download URL, license, refund/reissue policies, no hosted instance unless purchased.
6. Per-user: licensed seats, assignments, reassignment and enforcement.
7. Per-instance: metered or licensed instance count; enforce before provision.
8. Enterprise Contract: negotiated schedules/limits, manual invoicing, purchase-order/account terms and approvals.

**Subsystems:** versioned offer prices, immutable financial snapshots, tax/invoice numbering policies by jurisdiction, multi-currency strategy, payment provider adapter (hosted checkout rather than card storage), signed and idempotent webhooks, ledger/payment attempts/refunds/credit notes, dunning, subscription lifecycle, entitlement provisioning, metering/aggregation/reconciliation, finance reports and admin UX; integrate audit and anti-fraud controls.

**Exit:** A buyer can select each relevant plan, pay or receive approved enterprise terms, receive an accurate invoice and correct entitlement, and retain consistent service state through renewal, failed payment, cancellation and refund.

## 4. Cross-phase carry-forward backlog

| ID | Gap | Priority | Earliest delivery |
|---|---|---|---|
| CF-01 | Application-level user/role authorization within tenant | P0 | 5B/6 before general customer launch |
| CF-02 | Internal verified-domain users, external guests, secure invitation paths | P1 | 5B/6 if needed; before Phase 10 |
| CF-03 | Data reset and deterministic dev seed, with DB backup and protected-account preservation | P0 | Before next broad integration run |
| CF-04 | Baseline GitHub Actions, secret/dependency scan and automated regression | P0 | Start in next combined batch |
| CF-05 | Negative audit export authorization and application-open/upgrade/rollback coverage | P0 | 5A closure + 5B/6 instrumentation |
| CF-06 | Enforced archive/legal-hold/retention controls | P0 for regulated production | Phase 8 production gate |
| CF-07 | Legacy Infomentica workspaces | Deferred | No reparent/merge; remove only with safe dev reset |
| CF-08 | Billing data model design and provisioning coupling | P1 architecture now, product later | Design during 5B/6, implement 11 |

## 5. Sequenced combined delivery batches

| Batch | Combined phases | Content | Checkpoint |
|---|---|---|---|
| **B0** | Phase 5A closure + foundation | Verify live export negative tests, actual CSV, audit instrumentation matrix; database backup/reset plan; minimal CI smoke pipeline; establish new repo baseline | Clean development test environment and known security evidence |
| **B1** | **Phase 5B runtime + Phase 6 foundations** | Runtime state machine, start/stop/restart, logs/health, config, quotas, image identity, manual upgrade/rollback; job schema/durable queue | Two-tenant lifecycle smoke tests and failed-upgrade rollback |
| **B2** | **Phase 6 completion + Phase 7** | Scheduler, policy-aware automated upgrades, multi-asset static ZIP, AAPS validation/scans, published static and container examples | Automatic upgrade policies pass and real ZIP assets work |
| **B3** | **Phase 8 + Phase 9** | Shared session store, private networking, app isolation, provider/secrets hardening; full Actions/tests/staging promotion | Security gate and repeatable staging release |
| **B4** | Phase 10 | AI Builder publish → tenant subscribe → Techtango launch → favorite application | End-to-end tenant/user acceptance |
| **B5** | Phase 11 | Offer/price redesign, pricing meters, payment/invoicing, financial reconciliation, entitlements and admin screens | Real-plan fulfillment in payment-provider test environment |

**Constraint:** Do not delay necessary security controls until B3. Every earlier batch must be safe in its current network/exposure model.

## 6. Definition of done applied to every batch

- Baseline repository snapshot, explicit source compatibility and Alembic head recorded.
- Targeted changes only; no duplicate providers/AppShell/tenant context; immutable package and runtime boundaries maintained.
- Backwards-compatible migration or explicit tested migration plan with rollback strategy.
- API permissions and negative tests (including cross-tenant); never trust frontend visibility for security.
- Audit success/denial/failure and no secret leakage in audit or app logs.
- Unit/integration/adversarial tests, Python compile, TypeScript, ESLint, production Next build and package tests relevant to scope.
- At least one real-browser/API end-to-end scenario plus failure/recovery test, not merely a static source check.
- GitHub checkpoint only after tests pass, with staging and secrets reviewed; docs and current tracker updated.

## 7. Recommended immediate next action

**Start Batch B0 and B1 as one planned implementation request, but split it into two independently testable commits**: B0 establishes honest baseline/CI/data/reset/negative audit test evidence; B1 extends the current runtime implementations. Read the latest actual runtime routes/services and app/package/instance models first; the repository reference documents predate the October updates.

**Defer legacy Infomentica reconciliation** explicitly, because test data will be reset. Do not undertake migration or deletion of publisher applications while production retention and tenant ownership policies remain unresolved.
