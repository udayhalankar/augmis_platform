# AUGMIS AppShell Reference

## Canonical implementation

```text
apps/web/src/components/app-shell.tsx
```

Do not recreate this shell in individual pages.

## Props

```ts
type PlatformHealth = {
  api: boolean;
  database: boolean;
  docker: boolean;
};

type AppShellProps = {
  children: ReactNode;
  platformHealth?: PlatformHealth;
};
```

## Shell composition

```text
AppShell
├── Top Brand Bar
│   ├── Menu button
│   ├── AU brand mark
│   ├── AUGMIS / PLATFORM CONTROL PLANE
│   ├── TenantSelector
│   ├── Environment: Development
│   ├── Notifications
│   ├── Settings
│   ├── User avatar
│   ├── User name/email
│   └── Logout
│
├── Horizontal Navigation
│   ├── Control Center
│   ├── Applications
│   ├── Marketplace
│   ├── Subscriptions
│   ├── Tenants
│   ├── Runtime
│   ├── Users
│   └── Audit
│
├── Status Strip
│   ├── API health
│   ├── Database health
│   ├── Runtime/Docker health
│   └── Environment: Development
│
└── Main Workspace
    └── children
```

## Current navigation contract

| Label | Route | Icon |
|---|---|---|
| Control Center | `/` | `DashboardOutlined` |
| Applications | `/publisher` | `AppsOutlined` |
| Marketplace | `/marketplace` | `StorefrontOutlined` |
| Subscriptions | `/subscriptions` | `Inventory2Outlined` |
| Tenants | `/tenants` | `DomainOutlined` |
| Runtime | `/runtime` | `GridViewOutlined` |
| Users | `/users` | `PeopleOutlined` |
| Audit | `/audit` | `HistoryOutlined` |

The active route is determined from `usePathname()`. Root is exact-match; other routes use `pathname.startsWith(item.href)`.

## Top brand bar

Key behavior:
- 64px high.
- White background.
- Divider bottom border.
- `AU` square uses the theme primary color.
- Shows authenticated user's initials, full name and email.
- Logout calls `logout()` and redirects to `/login`.
- Global `TenantSelector` is mounted here.

## TenantSelector contract

Canonical component:

```text
apps/web/src/components/tenant-selector.tsx
```

It reads from `useTenant()`:
- `tenants`
- `selectedTenantId`
- `loading`
- `error`
- `selectTenant`

States:
- loading → “Loading tenants”
- error → “Tenant unavailable”
- zero tenants → “No tenant access”
- normal → tenant dropdown with name and slug

Do not add a page-level competing tenant selector.

## Health strip behavior

If `platformHealth` is absent:
- API Checking
- Database Checking
- Runtime Checking

If present:
- API Healthy / API Unavailable
- Database Up / Database Down
- Runtime Ready / Runtime Unavailable

The strip also shows `Environment: Development`.

## Standard usage

```tsx
import AppShell from "@/components/app-shell";
import ProtectedRoute from "@/components/protected-route";

export default function ExamplePage() {
  return (
    <ProtectedRoute>
      <AppShell>
        {/* page-specific content only */}
      </AppShell>
    </ProtectedRoute>
  );
}
```

## Rules for new pages

1. Keep platform chrome in AppShell.
2. Do not copy the navigation array into pages.
3. Do not copy the user/logout controls into pages.
4. Do not add another environment indicator.
5. Do not add another global tenant selector.
6. Page-specific controls belong inside the workspace.
7. If navigation visibility later becomes permission-aware, modify AppShell centrally rather than patching every page.
