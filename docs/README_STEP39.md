# AUGMIS Step 39 — Administrative Boundary Hardening

This pack is based on the latest files supplied in the current AUGMIS thread.

## Scope covered

- Tenant Admin can continue normal tenant-user administration.
- Only an active Tenant Owner can:
  - assign Tenant Owner access,
  - remove/change Tenant Owner access,
  - suspend/revoke/activate a Tenant Owner membership,
  - create an invitation containing a protected tenant-owner role,
  - reissue or revoke an invitation containing a protected tenant-owner role.
- Existing last-active-Tenant-Owner protection remains in force.
- Frontend hides Tenant Owner assignment/manipulation controls from non-owners.
- Backend remains authoritative.
- Protected-role detection uses the canonical `role_is_protected()` catalogue rule rather than display-name checks.

## Files changed

1. services/api/app/services/authorization_service.py
2. services/api/app/services/tenant_user_service.py
3. services/api/app/services/invitation_service.py
4. services/api/app/routes/invitations.py
5. apps/web/src/app/users/page.tsx

No Alembic migration is required.
No RBAC reseed is required.

## Before replacement

From repository root, confirm call sites:

```powershell
rg "reissue_tenant_invitation|revoke_tenant_invitation" .\services\api -n
```

The normal expected application callers are in `routes/invitations.py`.

## Backend compile gate

```powershell
python -m py_compile `
  .\services\api\app\services\authorization_service.py `
  .\services\api\app\services\tenant_user_service.py `
  .\services\api\app\services\invitation_service.py `
  .\services\api\app\routes\invitations.py
```

Then restart API:

```powershell
python -m uvicorn `
  services.api.app.main:app `
  --host 127.0.0.1 `
  --port 8001
```

## Frontend build gate

```powershell
cd .\apps\web
npm run build
cd ..\..
```

## Security regression matrix

Use a Tenant Admin account and a Tenant Owner account.

### Tenant Admin — must be blocked

1. Add existing user with `roleCodes=["tenant_owner"]` -> 403.
2. Invite user with `roleCodes=["tenant_owner"]` -> 403.
3. Replace roles on an existing Tenant Owner -> 403.
4. Suspend an existing Tenant Owner -> 403.
5. Revoke an existing Tenant Owner -> 403.
6. Activate a suspended/revoked Tenant Owner -> 403.
7. Reissue a pending/expired Tenant Owner invitation -> 403.
8. Revoke a pending Tenant Owner invitation -> 403.

### Tenant Admin — must still work

9. Add/invite normal roles such as `support`, `auditor`, `standard_user`, or `tenant_user`.
10. Replace roles between non-protected tenant roles.
11. Suspend/revoke/activate non-owner memberships.

### Tenant Owner — must work subject to last-owner lockout

12. Assign Tenant Owner to another user -> allowed.
13. Create Tenant Owner invitation -> allowed.
14. Modify another Tenant Owner -> allowed.
15. Reissue/revoke Tenant Owner invitation -> allowed.
16. Remove/suspend/revoke the final active Tenant Owner -> 409.

### Existing boundaries to re-check

17. Non-platform user -> `/api/v1/rbac/*` administration -> 403.
18. Protected Platform Owner role permission mutation -> 409.
19. Protected Publisher Owner role permission mutation -> 409.

## Frontend UX expectations

For Tenant Admin:
- Tenant Owner is absent from Add Existing User role choices.
- Tenant Owner is absent from Invite User role choices.
- Tenant Owner rows do not expose role/status mutation actions.
- Tenant Owner invitations do not expose Reissue/Revoke actions.

For Tenant Owner:
- Tenant Owner remains available in role selectors.
- Owner-management actions remain visible.
- Last-active-owner controls remain blocked.

## Publisher boundary note

The current codebase does not yet expose Publisher membership/user-administration mutation endpoints. Therefore there is no current Publisher Admin -> Publisher Owner assignment surface to harden. The canonical Publisher Owner role is already protected by the RBAC catalogue. When Publisher membership administration is added, it should use the same protected-role boundary pattern rather than inventing a parallel rule.
