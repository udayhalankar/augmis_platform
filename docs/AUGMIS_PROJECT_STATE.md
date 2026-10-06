# AUGMIS Project State

_Last updated: 2026-10-06_

## Current focus

Phase 4 — Tenant Users & RBAC Administration: COMPLETE

Next:
Phase 5 — Audit & Governance

## Phase 4 completion summary

Implemented and verified:

- Tenant member listing and administration
- Add existing AUGMIS users
- Tenant membership activate / suspend / revoke
- Tenant role assignment
- Tenant invitation create / list / revoke / reissue
- Existing-user and new-account invitation acceptance
- Invitation wrong-account / expired / revoked protections
- Invitation email delivery
- DB-backed encrypted SMTP configuration
- Resend webhook verification and delivery-event persistence
- Canonical permission catalogue
- Platform / tenant / publisher role catalogue
- Platform RBAC administration API
- Role-permission administration
- `/settings/rbac`
- Current-user platform and tenant permission APIs
- Permission-aware administrative pages/actions
- Tenant view/manage permission split
- Protected Platform Owner / Tenant Owner / Publisher Owner roles
- Tenant Admin cannot assign or invite Tenant Owner
- Last-active-Tenant-Owner protection
- Tenant Owner self-demotion / self-suspend / self-revoke protection
- Tenant-owner mutation row locking
- Controlled orphan Tenant Owner recovery
- Platform / Publisher / Tenant administrative boundary hardening
- Route-by-route authorization audit
- Application/build route authorization hardening
- Platform-controlled tenant/publisher creation
- Public readiness error sanitization
- Full RBAC behavioral matrix verification

## Phase 4 application-access decision

AUGMIS does not introduce a separate per-user application ACL in Phase 4.

Application access is governed by:

1. tenant membership,
2. effective tenant role permissions,
3. subscription state,
4. subscription entitlements,
5. application/deployment/runtime-specific permission checks.

This avoids a parallel authorization system while preserving backend-authoritative access control.

## Phase 4 verification

- Structural RBAC integrity: PASS
- Behavioral RBAC matrix: PASS — 120 assertions
- Protected role mutation checks: PASS
- Tenant self-lockout protection: PASS
- Last-active-Tenant-Owner protection: PASS
- Cross-tenant isolation: PASS
- Cross-publisher isolation: PASS
- Suspended/revoked tenant membership denial: PASS
- Suspended/revoked publisher membership denial: PASS
- Alembic current: `f2a7c4d91e60`
- Alembic head: `f2a7c4d91e60`
- Backend compile: PASS
- Frontend production build: PASS
- Next.js: 16.3.5

## Current architecture rules

- Next.js / React / MUI frontend
- FastAPI control plane
- PostgreSQL persistence
- SQLAlchemy + Alembic
- Backend authorization is authoritative
- Routes → schemas/services → models/db
- Reuse `ProtectedRoute` + `AppShell`
- Reuse global `TenantProvider`
- Frontend API helpers live under `apps/web/src/lib/`
- Runtime/static-runtime security remains a separate security boundary
- Do not weaken runtime security as a side effect of control-plane work

## Repository closure

- Repository: `udayhalankar/augmis_platform`
- Branch: `main`
- Pre-closure base: `fd88176eaabbdb6952463332f0bd13bed55ac6f3`
- Phase-4 closure tag: `phase4-rbac-complete-2026-10-06`
- Closure commit: resolved by the Phase-4 closure tag

## Next implementation block

Phase 5 — Audit & Governance

Initial scope:

- Audit administration UX
- Platform-level audit visibility where appropriate
- Tenant audit filtering/search
- Security-event coverage review
- RBAC and lifecycle mutation audit completeness
- Audit metadata consistency
- Export/reporting requirements
- Retention/governance policy
- Administrative event taxonomy

Containerized Application Runtime moves to Phase 6.

Phase 6 will include container lifecycle, routing, logs, configuration,
secrets, quotas, upgrades/rollback and the dedicated Container Sandbox
security sub-phase.