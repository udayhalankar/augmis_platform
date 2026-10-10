# AUGMIS — Combined B1 + B2 Delivery Contract

**Baseline:** 10 October 2026. **Status:** Plan; implementation and live acceptance not yet complete. **Source basis:** `b0b1-runtime-review.zip` plus B1A runtime safety package. Revalidate current source hashes/Alembic head before applying changes.

## Non-negotiable compatibility boundaries

- Retain FastAPI + SQLAlchemy/Alembic/PostgreSQL, Next.js + MUI, canonical AuthProvider → TenantProvider, ProtectedRoute + AppShell and domain API helpers.
- Backend authorization and commercial entitlements remain authoritative. No system-worker user impersonation or platform-owner tenant-scope bypass.
- No automatic destructive tenant reset, container deletion, retired-version reactivation, cross-tenant data movement or billing changes.
- Gateway access remains ticket/cookie, short-lived, tenant/user/instance/version-bound; no disabling `nosniff`, CORS or authorization to make test assets load.
- Use additive schemas and backward-compatible migrations; keep old data intact.

## Confirmed baseline

1. `deploy_application`, stop, restart, manual upgrade, rollback, health and logs routes exist. Presence alone does not prove E2E correctness.
2. B1A source package implements best-effort archived logs, resource caps, stop-intent and candidate recovery checkpoints. Local installation/DB migration state must be verified; current release state is not established by the browser screenshots.
3. Multiple container versions of `AUGMIS Runtime Lab` built and published. Browser launched HTML through gateway, **but CSS and JavaScript loaded as JSON error responses and were blocked by `nosniff`**. Root cause (401/403 vs 404 vs other) is not confirmed until asset response body/status is inspected.
4. Existing static-package service already supports multi-file ZIP with `index.html`, path/symlink/type/file-count/extracted-size limits, and immutable sealing. B2 should extend/check it, not build a competing upload mechanism.
5. Version policies `same_major`, `pinned`, `any` and `auto_upgrade` storage exist. No proven durable scheduler that upgrades instances unattended.
6. Existing subscriptions may include duplicate app subscriptions through different offers, so isolated fixtures and cleanup checks are required for reproducible acceptance.

## Single combined implementation scope

| Workstream | Required code changes | Acceptance |
|---|---|---|
| B1-01 Gateway correctness | Investigate JSON asset errors; preserve per-request authorization; proxy exact paths, methods, content types and safe headers; improve safe diagnostics, not token logging | HTML/CSS/JS/health/API all load through gateway; denied user still denied |
| B1-02 Lifecycle & recovery | Durable state transitions, interrupted candidate reconciliation, retry states, idempotency and recovery worker; retain B1A log archival | restart/stop/upgrade/rollback survive forced interruption on disposable instances |
| B1-03 Runtime configuration | Tenant/instance-scoped typed config with validation, versioning and audit; safe env injection in Docker startup; immutable deployment config snapshots | config changes scoped/validated; old deployment config reproducible |
| B1-04 Secrets | Store secret **references** rather than raw values; integrate scoped secret provider/resolver before container startup; deny retrieval through API/logs | cross-tenant refs denied; no secret values in DB/audit/logs |
| B1-05 Quotas | Transactional tenant resource accounting for instance counts, CPU/RAM/PIDs and build concurrency; enforce Docker limits | concurrent creation cannot exceed entitlements; negative tests |
| B1-06 Image identity | Resolve/persist immutable image digest, validate before run and upgrade; reject moved tags | build/deploy image identity is stable and auditable |
| B1-07 Durable jobs | PostgreSQL-backed outbox/jobs, lease/retry/idempotency/heartbeat and fail-safe reclaim; dedicated service principal/system actor semantics | worker restart does not duplicate a running upgrade |
| B2-01 Upgrade selection | Find eligible active subscriptions/instances on published ready version; enforce consent, auto_upgrade and version policy | same_major 1.0→1.1 allowed / 1.x→2 blocked; pinned blocked; any allowed |
| B2-02 Upgrade worker | Execute upgrade via a shared internal lifecycle service, **not by invoking HTTP route as an impersonated user**; health-gate cutover and rollback | failure leaves previous healthy runtime active, audited |
| B2-03 Packaging | Extend canonical static ZIP + AAPS validators; malware scan provider hook, fail-closed for required policy, manifest/entrypoint/digest checks | good multi-file static and container bundles work; malicious fixtures denied |
| B2-04 Examples/tests | Healthy 1.0/1.1, unhealthy 1.2, major 2.0, real multi-file static ZIP, two isolated tenants; CI integration | end-to-end run + negative authorization matrix and reproducible fixture reset |

## Implementation order **inside the one batch**

1. **Gate A:** current source/migration snapshot and asset gateway diagnosis. Require actual response for `style.css` and `app.js` before choosing a fix.
2. **Gate B:** additive migrations for config/secrets references, digest identity, quota reservation, durable jobs/outbox; dry-run and rollback tests.
3. **Gate C:** shared lifecycle services with no RBAC shortcuts; manual API paths remain unchanged externally; B1A compatibility tests.
4. **Gate D:** publisher-triggered/scheduled auto-upgrade planner and worker; health-gated cutover and cancellation/retry behavior.
5. **Gate E:** packaging and malicious-fixture tests; full backend/frontend/CI, 2-tenant live smoke, tagged GitHub checkpoint only after acceptance.

## Mandatory regression and security tests

- Two tenants A/B and two users with explicit memberships; deny B reading A's logs/config, starting/stopping A's instance, upgrading A, or obtaining A's secret refs.
- No authorization inferred from publisher membership or email domain; use `application.deploy` and entitlements separately.
- Check parallel deploy resource reservations and crash reclaim; no double-counting.
- Verify `auto_upgrade=false`, `pinned`, `same_major` and `any` including withdrawn/retired/current versions; published version never mutated in place.
- Force unhealthy candidate; verify old version remains healthy, traffic stays on old deployment, candidate logs saved, audit failure recorded.
- Check external HTTP app relative CSS/JS, POST, redirects, 404, content-type, cookies, WebSocket/SSE scoped to explicit support (Phase 8 if not implemented).
- Never waive TLS/private network/host-port isolation requirements for production due to successful local tests.

## Browser diagnostic for current blocker

On the already authenticated *runtime gateway page* (not `localhost:3000`), open Developer Tools → Console. Paste:

```javascript
(async () => {
  for (const name of ["style.css", "app.js", "health", "api/status"]) {
    try {
      const u = new URL(name, location.href);
      const r = await fetch(u, { credentials: "same-origin", cache: "no-store" });
      const body = (await r.text()).slice(0, 180);
      console.log(name, { status: r.status, type: r.headers.get("content-type"), body });
    } catch (e) { console.log(name, String(e)); }
  }
})();
```

Share **status, content type and error detail** only; omit cookies, tickets and bearer tokens. This identifies whether the fault is gateway authorization, upstream path resolution or content delivery. It is not safe to remove `nosniff` as a fix.

## Acceptance exit

B1 + B2 is **complete only when** all gates A–E and the real two-tenant/manual+automated upgrade tests pass. Do not interpret route presence, a green unit test or HTML-only gateway launch as completion.

## Follow-on combined wave: B3 + B4 + B5

Plan these under one program, but deploy behind three independent gates: **B3 security+CI/CD**, then **B4 Techtango integration**, then **B5 commercial billing**. Payment fulfillment is not production-ready until B3 security sign-off and B4 tenant launch/entitlement flows pass. A single source push cannot substitute for staging, provider sandbox and security acceptance.
