# AUGMIS Phase 4 — Tenant Users & RBAC Administration Tracker

_Last updated: 2026-10-04_

## Exit condition
Tenant administrators can manage tenant users, roles, permissions, and application access without direct database work. Frontend hides unauthorized actions, while backend authorization remains authoritative.

## Current working assessment
This is a preliminary status based on the implemented flows verified in the current development thread. Final status should be reconciled against the latest GitHub backup.

| Phase | Scope | Status | Current evidence / remaining work |
|---|---|---|---|
| 4A | User lifecycle | 🟢 Substantially complete | User/member listing, add existing user, invite user, accept existing/new account, suspend/activate/revoke, invitation lifecycle, email delivery, reissue, delivery tracking |
| 4A3-C1 | Invitation model + backend API | ✅ Complete | Create/list/revoke/reissue, validation, auditing |
| 4A3-C2 | Invitation acceptance / onboarding | ✅ Complete | Existing-account and new-account acceptance; wrong-account/expired/revoked protections |
| 4A3-C3 | `/users` pending invitations UI | ✅ Complete | Pending/accepted/expired/revoked display, revoke/reissue UX |
| 4A3-C4 | Actual email delivery | ✅ Complete | DB-backed SMTP settings, Resend, test delivery, webhook delivery tracking, Delivered/Delayed states |
| 4B | Tenant lifecycle | 🟡 Existing foundation; Phase-4 review pending | Tenant model/routes exist; administrative lifecycle and authorization boundaries need formal review |
| 4C | Tenant membership | 🟢 Mostly complete | Membership listing and lifecycle actions exist; last-active-owner protection verified; full permission matrix still needs testing |
| 4D | Roles | 🟡 Partial | Role model/seed/listing exist; tenant-facing role administration policy/UI needs review |
| 4E | Permissions | 🟡 Partial | Permission model and backend checks exist; permission catalogue/admin UX not complete |
| 4F | Role-permission assignment | 🟠 Incomplete | Seeded/static mappings exist; administrative assignment layer still required |
| 4G | User-role assignment | 🟢 Mostly complete | Tenant member role replacement UI/backend exists; needs matrix/edge-case verification |
| 4H | API authorization enforcement | 🟡 Partial | Strong enforcement exists on several current routes; route-by-route RBAC audit still required |
| 4I | Frontend permission-aware navigation/actions | 🟠 Incomplete | Backend blocks unauthorized access; frontend still needs centralized permission-aware hide/disable behavior |
| 4J | Platform / Publisher / Tenant Admin boundaries | 🟠 Incomplete | Platform Owner foundation exists; Publisher Admin / Tenant Admin / support/auditor boundaries need completion |
| 4K | RBAC audit/testing | 🟡 Partial | Security-sensitive audit events exist; full role × permission × route test matrix remains |
| APP-PERM | Application permissions | 🔴 Not yet complete | Need explicit user/role → application access model, API and UI or a deliberate entitlement-based alternative |

## Proposed role families
- Platform Owner
- Publisher Admin
- Tenant Admin
- Subscription Admin
- Operations Admin
- Support
- Auditor
- Standard User

## Immediate next review block
1. Freeze current code in GitHub.
2. Reconcile migrations, models, routes, services, frontend helpers and pages.
3. Build a canonical permission catalogue.
4. Build a role × permission matrix.
5. Decide application-permission model.
6. Complete frontend permission-aware navigation/actions.
7. Run backend authorization matrix tests.
8. Close Phase 4 only when tenant administration no longer requires DB access.

## Security principles
- Backend permission checks are authoritative.
- Frontend hiding/disabling is UX only.
- Avoid authorization based on display role names where permission codes can express the capability.
- All sensitive RBAC mutations should be auditable.
- Preserve last-owner / lockout protections.
- Invitations and external-provider webhooks must remain idempotent and securely verified.
