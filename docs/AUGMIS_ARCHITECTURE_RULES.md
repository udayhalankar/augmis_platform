# AUGMIS Architecture Rules

## Purpose
These are the working architecture rules for AUGMIS development. They are intentionally project-specific.

## 1. Control-plane split

AUGMIS is divided into:

```text
Next.js / React / MUI frontend
        ↓
FastAPI Control Plane API
        ↓
PostgreSQL / runtime / package services
```

Frontend presentation belongs in `apps/web`. Control-plane routing, authorization, persistence, package/runtime orchestration, and lifecycle logic belong under `services/api`.

## 2. Frontend provider hierarchy

The canonical provider composition is:

```text
ThemeProvider
└── AuthProvider
    └── TenantProvider
        └── Application
```

Rules:
- `TenantProvider` must stay inside `AuthProvider` because tenant context depends on authenticated user state.
- Use only `apps/web/src/app/providers.tsx` as the provider composition source.
- Do not create another root `providers.tsx` elsewhere.

## 3. Authentication and tenant context

Authentication state is global.

Tenant context is global and tenant-scoped pages should consume:

```ts
const {
  tenants,
  selectedTenant,
  selectedTenantId,
  loading,
  error,
  selectTenant,
  refreshTenants,
} = useTenant();
```

Tenant pages must not independently:
- read or write a competing tenant ID,
- create a second tenant selector,
- own a duplicate selected-tenant localStorage mechanism,
- trust a manually typed tenant UUID as authorization.

The current selected tenant is persisted under:

```text
augmis.platform.selectedTenantId
```

The frontend tenant list is a UX boundary only. Backend RBAC remains authoritative.

## 4. AppShell is global platform chrome

All authenticated platform pages should use:

```tsx
<ProtectedRoute>
  <AppShell>
    {/* page content */}
  </AppShell>
</ProtectedRoute>
```

Do not recreate:
- AUGMIS branding,
- primary navigation,
- tenant selector,
- environment indicator,
- user identity/logout,
- health/status strip,
- workspace padding.

## 5. Frontend API organization

Domain-specific API calls belong under `apps/web/src/lib/`.

Current domains include:
- control center
- marketplace
- publisher center
- runtime gateway
- subscriptions
- tenant applications
- tenant context
- tenants

When adding a new domain such as tenant-user administration, prefer:

```text
apps/web/src/lib/tenant-users.ts
```

rather than embedding request URLs throughout the page.

## 6. Backend layering

Use the existing layers consistently:

```text
routes/      HTTP contract + dependency wiring
schemas/     request/response validation
services/    business rules, authorization orchestration, lifecycle logic
models/      persistence mapping
db/          SQLAlchemy base/session
core/        auth/config infrastructure
```

A route should remain thin when logic can be placed in a service.

## 7. Authorization

Authorization checks are backend responsibilities.

Frontend role/permission information may hide or disable controls for UX, but it must never be treated as the security boundary.

When adding new tenant-scoped actions:
1. Resolve authenticated user.
2. Validate tenant membership/scope.
3. Check the required permission.
4. Perform the action.
5. Audit security-sensitive changes where appropriate.

Avoid hard-coding authorization behavior around display role names when an existing permission model can represent the capability.

## 8. Runtime boundary

The static runtime route is:

```text
apps/web/src/app/runtime/[runtimeId]/[[...assetPath]]/route.ts
```

Runtime security behavior is a separate boundary from normal control-plane UI.

Do not casually modify runtime-gateway or static-runtime security code while working on ordinary tenant/user/RBAC UI.

Container runtime hardening remains a dedicated runtime-security concern.

## 9. Package lifecycle

Package state is stored under:

```text
data/packages/quarantine/
data/packages/rejected/
data/packages/validated/
```

These directories are runtime/package artifacts, not normal source modules.

## 10. Change discipline

Before changing code:
1. Identify the canonical existing file.
2. Inspect related reusable components/helpers.
3. Prefer a targeted edit.
4. Use a full drop-in only when the file is already damaged, the user explicitly requests one, or a full replacement is materially safer.
5. Preserve working behavior outside the requested scope.
6. After structural changes, regression-test the previously working flow.

## 11. Naming and duplication guardrail

Never create a parallel file simply because its location is uncertain.

Examples:
- check `src/app/providers.tsx` before creating `src/providers.tsx`;
- check `src/components/` before creating a new dialog;
- check `src/lib/` before embedding a duplicate API helper;
- check existing FastAPI routes/services before adding a second implementation.
