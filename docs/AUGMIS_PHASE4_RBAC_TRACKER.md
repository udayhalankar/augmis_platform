# AUGMIS Phase 4 — Tenant Users & RBAC Administration Tracker

_Last updated: 2026-10-06_

## Status

**PHASE 4 COMPLETE**

## Exit condition

Tenant administrators can manage tenant users, roles, permissions and
application-related access without direct database work.

Frontend hides/disables unauthorized administrative actions where appropriate.
Backend authorization remains authoritative.

## Completion matrix

| Phase | Scope | Status | Completion evidence |
|---|---|---|---|
| 4A | User lifecycle | ✅ Complete | Member listing, add existing user, invitations, acceptance, suspend/activate/revoke |
| 4A3-C1 | Invitation backend | ✅ Complete | Create/list/revoke/reissue, validation and auditing |
| 4A3-C2 | Invitation onboarding | ✅ Complete | Existing/new account acceptance plus wrong-account/expired/revoked protections |
| 4A3-C3 | Invitations UI | ✅ Complete | Pending/accepted/expired/revoked states and administration |
| 4A3-C4 | Email delivery | ✅ Complete | Encrypted SMTP configuration, Resend delivery and webhook status tracking |
| 4B | Tenant lifecycle boundary | ✅ Complete for Phase 4 | Tenant creation restricted by `platform.tenants.manage`; tenant scope reviewed |
| 4C | Tenant membership | ✅ Complete | Listing, lifecycle, active-membership enforcement, last-owner protection |
| 4D | Roles | ✅ Complete | Canonical platform/tenant/publisher roles and protected ownership roles |
| 4E | Permissions | ✅ Complete | Canonical permission catalogue and effective permission APIs |
| 4F | Role-permission assignment | ✅ Complete | Platform RBAC administration and role-permission editing |
| 4G | User-role assignment | ✅ Complete | Tenant member role replacement with protected-role and self-lockout controls |
| 4H | API authorization enforcement | ✅ Complete | Route-by-route authorization audit and identified gaps hardened |
| 4I | Frontend permission awareness | ✅ Complete for Phase 4 | Permission-aware administrative pages/actions; backend remains security boundary |
| 4J | Platform / Publisher / Tenant boundaries | ✅ Complete | Scope isolation and administrative boundary protections verified |
| 4K | RBAC audit/testing | ✅ Complete | Structural verifier plus 120-assertion behavioral RBAC matrix |
| APP-PERM | Application access model | ✅ Complete by design | Tenant RBAC + subscription/entitlement model; no parallel per-user application ACL |

## Canonical role families

Platform:
- Platform Owner

Tenant:
- Tenant Owner
- Tenant Admin
- Subscription Admin
- Operations Admin
- Support
- Auditor
- Standard User
- Tenant User

Publisher:
- Publisher Owner
- Publisher Admin
- Publisher Developer

## Security controls verified

- Backend permission checks are authoritative.
- Protected ownership-role definitions cannot be modified through normal RBAC administration.
- Tenant Admin cannot grant/remove/invite Tenant Owner.
- Only an active Tenant Owner can normally manage Tenant Owner access.
- Tenant Owner cannot change their own tenant roles.
- Tenant Owner cannot suspend or revoke their own membership.
- Last-active-Tenant-Owner removal is blocked.
- Tenant-owner-sensitive mutations lock the tenant row.
- Platform Owner does not automatically bypass tenant scope.
- Tenant Owner does not automatically gain platform permissions.
- Cross-tenant access is denied.
- Cross-publisher access is denied.
- Suspended/revoked tenant memberships cannot authorize.
- Suspended/revoked publisher memberships cannot authorize.
- Controlled orphan-owner recovery requires `platform.rbac.manage`.
- Owner recovery succeeds only when no active Tenant Owner exists.
- Runtime/static-runtime security remains separate from ordinary RBAC administration.

## Automated verification

### Structural verifier

```text
python -m tools.verify_phase4_rbac
PHASE 4 RBAC INTEGRITY CHECK: PASSED