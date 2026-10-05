# AUGMIS Reusable Components Catalogue

## Purpose
Consult this catalogue before creating a new frontend component. Reuse or extend existing components first.

## Existing shared components

### `AppShell`
**File:** `apps/web/src/components/app-shell.tsx`

Use for all authenticated platform pages.

Owns:
- AUGMIS platform chrome
- top brand bar
- global tenant selector
- primary navigation
- environment indicator
- user identity/logout
- health/status strip
- main workspace wrapper

Do not duplicate this structure in a page.

---

### `ProtectedRoute`
**File:** `apps/web/src/components/protected-route.tsx`

Use as the authenticated-page boundary around AppShell/pages.

Expected page pattern:

```tsx
<ProtectedRoute>
  <AppShell>
    {/* page */}
  </AppShell>
</ProtectedRoute>
```

Inspect its current API before changing authentication behavior.

---

### `TenantSelector`
**File:** `apps/web/src/components/tenant-selector.tsx`

Global tenant selection UI.

Depends on:
```text
TenantProvider → useTenant()
```

Provides:
- loading state
- error state
- no-access state
- tenant dropdown
- tenant name + slug

Mounted by `AppShell`; tenant-scoped pages should consume context, not render another selector.

---

### `ApplicationUploadDialog`
**File:** `apps/web/src/components/application-upload-dialog.tsx`

Existing application-upload dialog. Inspect and extend this component before creating a second application upload flow.

---

### `OfferEditorDialog`
**File:** `apps/web/src/components/offer-editor-dialog.tsx`

Existing offer create/edit UI. Reuse it for offer editing rather than introducing a second editor.

---

### `OfferLifecycleDialog`
**File:** `apps/web/src/components/offer-lifecycle-dialog.tsx`

Existing lifecycle UI for offer state changes. Reuse/extend for offer lifecycle operations.

---

### `StaticAppPreviewDialog`
**File:** `apps/web/src/components/static-app-preview-dialog.tsx`

Existing static-application preview UI. Reuse it for preview behavior rather than implementing preview ad hoc.

## Existing global contexts

### `AuthProvider` / `useAuth`
**File:** `apps/web/src/context/auth-context.tsx`

Global authentication state.

Do not create page-specific parallel authentication state.

### `TenantProvider` / `useTenant`
**File:** `apps/web/src/context/tenant-context.tsx`

Global tenant context.

Exposes:
```ts
tenants
selectedTenant
selectedTenantId
loading
error
selectTenant()
refreshTenants()
```

Selected tenant storage key:
```text
augmis.platform.selectedTenantId
```

Only active memberships are exposed by the current provider.

## Provider composition

Canonical file:

```text
apps/web/src/app/providers.tsx
```

Current hierarchy:

```text
ThemeProvider
└── AuthProvider
    └── TenantProvider
        └── children
```

Do not create a second providers file in another directory.

## Existing frontend domain helpers

Before writing raw API calls in a page, inspect:

| Helper | Domain |
|---|---|
| `src/lib/api.ts` | shared API client |
| `src/lib/auth-storage.ts` | auth token/session storage |
| `src/lib/control-center.ts` | control-center API helpers |
| `src/lib/marketplace.ts` | marketplace |
| `src/lib/publisher-center.ts` | publisher workspace |
| `src/lib/runtime-gateway.ts` | runtime URL/gateway helpers |
| `src/lib/subscriptions.ts` | tenant subscriptions |
| `src/lib/tenant-applications.ts` | tenant application catalogue/open |
| `src/lib/tenant-context-api.ts` | current user's tenant memberships |
| `src/lib/tenants.ts` | tenant creation/list-related helper |

## New reusable components: decision rule

Create a new component only when at least one is true:
- it is reused by two or more pages,
- it owns a coherent interaction (dialog, picker, table toolbar, etc.),
- extracting it materially reduces duplicated complex code,
- it is part of the global shell/design system.

Otherwise keep page-specific JSX in the page.

## Recommended future reusable components

Do not create these prematurely; add them only when repeated usage appears.

Potential candidates:
- `PageHeader`
- `CurrentTenantPanel`
- `StatusChip`
- `EmptyState`
- `ConfirmActionDialog`
- `SearchField`
- `DataSection`
- permission-aware action wrapper / guard

## Before creating a new component

1. Search `apps/web/src/components/`.
2. Search current page implementations.
3. Search `apps/web/src/lib/` for matching logic.
4. Check AppShell and global contexts.
5. Extend existing implementation if the role is already covered.
