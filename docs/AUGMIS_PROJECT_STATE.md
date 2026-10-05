# AUGMIS Project State

_Last updated: 2026-10-04_

## Current focus
Phase 4 — Tenant Users & RBAC Administration

## Recently completed
- Invitation create/list/revoke/reissue
- New-user and existing-user invitation acceptance
- Invitation acceptance security checks
- `/users` tenant member and invitation administration
- Tenant membership suspend/activate/revoke
- Last-active Tenant Owner protection
- Platform email settings UI and encrypted credential storage
- Resend SMTP delivery
- Resend webhook verification and event persistence
- Real invitation delivery states including Submitted, Delivered and Delayed
- Audit events for invitation and email-delivery lifecycle

## Current architecture rules
- Next.js / React / MUI frontend
- FastAPI control plane
- PostgreSQL persistence
- Backend authorization is authoritative
- Routes → schemas/services → models/db
- Reuse `ProtectedRoute` + `AppShell`
- Reuse global `TenantProvider`
- Frontend API helpers live under `apps/web/src/lib/`
- Runtime security is a separate boundary from normal RBAC/UI work

## Current Phase-4 gap summary
- Formal Tenant lifecycle review
- Administrative role catalogue
- Permission catalogue UX/API
- Role-permission assignment
- Application-level permission model
- Central frontend permission-awareness
- Platform / Publisher / Tenant administrative boundary completion
- Full RBAC audit and automated test matrix

## Repository checkpoint
Populate after backup:

- Repository: `udayhalankar/augmis_platform`
- Branch:
- Commit SHA:
- Tag:
- Alembic current:
- Alembic head:
- Backend compile:
- Frontend build:
- Working tree clean:

## Next implementation block
After repository review, continue at the earliest incomplete Phase-4 dependency rather than adding parallel RBAC structures.
