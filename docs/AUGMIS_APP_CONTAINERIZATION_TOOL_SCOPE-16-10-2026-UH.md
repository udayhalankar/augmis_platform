# AUGMIS — App Containerization Tool (ACT)

**Status:** **NEW APPROVED SCOPE REQUEST / NOT YET IMPLEMENTED** (16 October 2026)  
**Owner:** AUGMIS Publisher Center / Control Plane / runtime build services  
**Goal:** Turn suitable source applications (including compatible Techtango AI App Builder exports) into reproducible, signed-off **AAPS container application packages and OCI images**, safely and repeatably, without hand-authoring a bespoke Dockerfile for every application.

## 1. User objective

The publisher should be able to choose an app, review an automated dependency/readiness analysis, configure its runtime, **containerize**, validate and smoke-test it, then submit the resulting package to the **existing** Publisher Center upload/build/publish lifecycle. This is a workflow/tool, not an alternative platform or security bypass.

A successful outcome is a reusable **"Containerize App"** wizard/CLI with saved templates and detailed compatibility feedback. The tool should help with frontend-only, frontend+backend, supported data-dependent apps, and exported Techtango applications. It must not promise automatic conversion for unsupported platforms or external services without source code.

## 2. Input modes (phased)

| Source | Scope | Notes |
|---|---|---|
| Source ZIP / directory | Phase 1 | Detect application frameworks; enforce archive-path, size and symlink safety |
| Git repository / commit | Phase 1 (after safe clone/isolation) | Pin commit SHA and allowlist authorized hosts; do not embed credentials |
| Existing Dockerfile + AAPS manifest | Phase 1 | Validate, review, build and attest rather than blindly rewriting |
| Existing pre-built OCI image reference | Phase 2 | Inspect immutable digest, provenance, supported runtime and image policy |
| Techtango AI App Builder export | Phase 2 | Require **real portable export contract**; metadata snapshot by itself is insufficient |
| Other no-code/low-code builders | Future | Plugin/adapter architecture with verified export contracts; no undocumented DB scraping |

## 3. Main workflow

1. **Choose source** under existing Publisher Center; authenticate publisher and verify RBAC/ownership.
2. **Inspect** files and app mode (static, API, full-stack, dashboard) in a sandbox without executing untrusted source on the control plane; identify language/framework, routes, assets, data dependencies, migrations, network and secrets requirements.
3. **Classify** as `supported automatic`, `guided/manual mapping`, or `unsupported`, with explicit reasons. Produce a human-readable readiness report and structured dependency graph.
4. **Configure** non-secret env var names, health path, internal port, user UID/GID, data isolation strategy, storage/migrations, front/back separation and runtime permissions. Select reusable base templates.
5. **Generate** Dockerfile/entrypoint when supported, locked dependency manifest, `.dockerignore`, AAPS manifest, build/test contracts, schema/migration descriptors as needed. No secret literals.
6. **Security preflight:** block embedded secrets, unsafe user/root configuration, host mounts, privileged flags, internet exposure assumptions, vulnerable or unpinned critical components according to policy. Produce SBOM and scan/provenance reports where supported.
7. **Build** inside isolated worker with bounded CPU/memory/time/network; pin dependency/base image versions and record OCI immutable digest, logs (redacted), provenance and build outputs.
8. **Smoke-test** health and minimal API/static routes in an isolated ephemeral runtime, using synthetic identities and data. Negative security tests appropriate to supplied runtime adapter; no production credentials.
9. **Export** an AAPS ZIP and validation report; run `tools/validate_package.py`/AAPS contract, then use existing upload API for registration. The publisher explicitly approves subsequent build, publish, offer and deployment actions separately.
10. **Lifecycle:** versioned build history, reproducible artifact hashes, comparison, reasoned failure reports, controlled regeneration, archival and audit. Do not mutate an immutable published version.

## 4. Required functionality

### Detection and dependency inventory
- Detect React/Next.js/Vite/static HTML, Python FastAPI/Flask, Node/Express and supported backend/database patterns initially; add frameworks via vetted templates.
- Determine if app needs separate frontend/backend containers or one service. Detect hard-coded `localhost`, port conflicts, client-side secrets, filesystem assumptions, process managers, native libraries, background workers and schedule jobs.
- Identify DB schema and SQL dialect dependencies, migrations, RLS/tenant filters, secret needs and data residency. Produce `unsupported`/manual result if dependencies cannot be safely exported.
- For Techtango `advanced-dashboard`, inspect UI schema/renderer data bindings, supported source aliases, backend fields/forms and database source schema; export allowlisted schema definitions only. Never copy live Techtango source rows by default.

### Security and tenancy
- Rootless container runtime, read-only filesystem where possible, dropped Linux capabilities, no-new-privileges, pinned image IDs, health endpoints and resource quotas.
- Runtime auth through the existing AUGMIS gateway and short-lived assertions; do not trust passed headers/tenant IDs. Keep Techtango proof signing domain separate from AUGMIS runtime signing.
- Runtime secrets created/injected by trusted deployment process, per tenant/application/instance; no secrets in ZIP/image/logs/config examples.
- Database isolation plan must be explicit: dedicated per-tenant/per-app DB when selected, or reviewed shared DB with enforced RLS. Avoid implicit connection to builder development database.
- No arbitrary-code execution inside control-plane FastAPI worker; use isolated build workers and container security profiles. Govern egress, dependencies and package sources.
- Preserve `application.upload`, build, publish, entitlement, billing, tenant membership and B3 release gates. Keep audit logs.

### User experience
- Add a **"Containerize App"** action in existing Publisher Center. Reuse `ProtectedRoute`, `AppShell`, global `TenantProvider`, existing publisher membership and domain API helpers. Do **not** add duplicate root providers or a parallel marketplace.
- Suggested compact steps: **Source → Analyze → Configure → Generate → Build & Test → Review & Export**.
- Display compatibility score with concrete blockers, editable mapping grid, proposed environment variable *names* (not values), Docker service topology, memory/CPU targets, dependency list, security findings, status and remediation.
- Require explicit user confirmation before registry registration, image build, publish, offer activation or tenant launch. Keep read-only analysis separate from writes.
- Let user download AAPS ZIP, Dockerfile/source changes, SBOM, sanitized build logs and readiness/acceptance report; identify whether generated output is a *draft* or an *approved deployable* package.

## 5. Placement in current AUGMIS codebase

Before creating new files, inspect canonical existing implementation:
- Frontend: `apps/web/src/app/publisher/page.tsx`, `apps/web/src/components/application-upload-dialog.tsx`, `apps/web/src/lib/publisher-center.ts`.
- Backend: `services/api/app/routes/applications.py`, existing `build_engine.py`, `deployment_engine.py`, package validation/import services, `services/api/app/schemas/`, `services/api/app/models/` and migrations only if persistence is required.
- Contracts/CLI: existing `packages/contracts/aaps-v1.schema.json`, `tools/validate_package.py`, `tools/techtango_export_contract.py`, and `tools/` for a CLI entrypoint if required.
- Techtango integration: existing attestation/snapshot routes/services. Build **new export adapter capability** only when a portable source contract is validated; do not equate `staged_metadata_only` with container-ready source.
- Use existing protected app access and gateway runtime controls, not a parallel router/provider or bypass endpoints.

**Potential abstractions, subject to repo review:** `ContainerizationAnalysis`, `ContainerizationPlan`, `ContainerizationBuildJob`, `ContainerizationValidationReport`; exact storage/schema should be decided after inspecting existing build/validation models to avoid duplicate tables.

## 6. MVP delivery plan

| Milestone | Deliverable | Acceptance evidence |
|---|---|---|
| ACT-0 | Inventory existing package/build/publisher workflow, define supported app types and threat model | Approved spec, input validation rules, reuse map |
| ACT-1 | Read-only source analyzer + dependency report (ZIP and supported repo) | Safe archive tests, predictable unsupported reasons, no untrusted source execution |
| ACT-2 | AAPS + Dockerfile generator from vetted templates | Reproducible digest; validator passes; no secret embedding |
| ACT-3 | Isolated build worker + test harness | Non-root, limited resources/network, sanitized logs, digest and SBOM |
| ACT-4 | Publisher Center Containerize wizard | Uses existing AppShell/provider/API helpers; RBAC; explicit publish gates |
| ACT-5 | Techtango portable export adapter for supported `dashboard` apps | End-to-end schema-only export to runnable sample without customer data; signed association |
| ACT-6 | Production hardening (attestation, signed artifacts, scanning policy, upgrades/rollback) | Security review and staging-to-prod release gate |

## 7. First pilot acceptance scenarios

**Positive:** (1) Static HTML SPA becomes valid AAPS/static or containerized app; (2) FastAPI dashboard with declared DB schema becomes AAPS image; (3) Techtango `21augdashboard` source export produces a **reviewed** runtime package matching the known read-only behavior (not a DB clone); (4) image runs under non-root and responds to a health probe; (5) application registers as Draft without automatic publish/deploy.

**Negative:** reject archive traversal and symlink escape, malicious Dockerfile directives, private keys/API tokens, unspecified host privilege, unsupported DB schema, external DB credentials, wrong tenant/source ownership, unpinned runtime image where mandatory, Docker health failure, oversized zip, invalid AAPS manifest, and repeated immutable version ID.

**Contract correctness:** Differentiate these artifacts: **Techtango source metadata snapshot** vs **portable builder export** vs **AAPS registration ZIP** vs **OCI image digest** vs **AUGMIS instance runtime**. The tool must show independent readiness/approval status for each.

## 8. Priority and dependencies

The user requested inclusion in scope now, not immediate implementation. The current critical path remains: finish **B4 3H-5I private database preflight**, then real reserved instance activation and authenticated gateway acceptance. Containerization tool discovery/spec can start in parallel; do not let it alter the proven pilot without separate version and tests.

**Success definition:** A publisher can move a *supported* application source through analysis → generated AAPS → isolated build/test → draft registration with provenance, without manual Docker engineering, without embedding credentials, and without bypassing AUGMIS RBAC, subscription or runtime-security controls.
