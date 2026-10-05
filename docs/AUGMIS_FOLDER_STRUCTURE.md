# AUGMIS Folder Structure Reference

## Purpose
This file is the canonical project-only reference for where AUGMIS code belongs. Consult it before creating a new file, route, component, context, helper, model, schema, service, migration, or runtime artifact.

## Repository roots

```text
AUGMIS_PLATFORM/
├── apps/
│   └── web/                  # Next.js / React / MUI frontend
├── services/
│   └── api/                  # FastAPI control-plane backend
├── data/
│   └── packages/             # Package quarantine/rejected/validated storage
├── examples/                 # Sample application packages
├── packages/
│   └── contracts/            # Shared package/contracts schemas
├── tools/                    # CLI / seed / validation utilities
├── alembic.ini
└── requirements.txt
```

## Frontend: `apps/web`

```text
apps/web/
├── src/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── providers.tsx             # CANONICAL provider composition
│   │   ├── page.tsx                  # Control Center
│   │   ├── login/page.tsx
│   │   ├── marketplace/page.tsx
│   │   ├── publisher/page.tsx
│   │   ├── subscriptions/page.tsx
│   │   ├── tenant-applications/page.tsx
│   │   ├── tenants/page.tsx
│   │   ├── static-test/page.tsx
│   │   └── runtime/
│   │       └── [runtimeId]/
│   │           └── [[...assetPath]]/
│   │               └── route.ts      # Static runtime gateway route
│   │
│   ├── components/
│   │   ├── app-shell.tsx
│   │   ├── application-upload-dialog.tsx
│   │   ├── offer-editor-dialog.tsx
│   │   ├── offer-lifecycle-dialog.tsx
│   │   ├── protected-route.tsx
│   │   ├── static-app-preview-dialog.tsx
│   │   └── tenant-selector.tsx
│   │
│   ├── context/
│   │   ├── auth-context.tsx
│   │   └── tenant-context.tsx
│   │
│   ├── lib/
│   │   ├── api.ts
│   │   ├── auth-storage.ts
│   │   ├── control-center.ts
│   │   ├── marketplace.ts
│   │   ├── publisher-center.ts
│   │   ├── runtime-gateway.ts
│   │   ├── subscriptions.ts
│   │   ├── tenant-applications.ts
│   │   ├── tenant-context-api.ts
│   │   └── tenants.ts
│   │
│   └── theme.ts
│
├── public/
├── next.config.ts
├── package.json
└── tsconfig.json
```

## Backend: `services/api`

```text
services/api/
├── alembic/
│   ├── env.py
│   └── versions/                     # Database migrations only
│
└── app/
    ├── main.py
    │
    ├── core/
    │   ├── auth.py
    │   └── config.py
    │
    ├── db/
    │   ├── base.py
    │   └── session.py
    │
    ├── models/
    │   ├── audit.py
    │   ├── commerce.py
    │   ├── iam.py
    │   └── platform.py
    │
    ├── routes/
    │   ├── applications.py
    │   ├── audit.py
    │   ├── auth.py
    │   ├── health.py
    │   ├── instances.py
    │   ├── memberships.py
    │   ├── offers.py
    │   ├── operations.py
    │   ├── publishers.py
    │   ├── subscriptions.py
    │   └── tenants.py
    │
    ├── schemas/
    │   ├── auth.py
    │   ├── instance.py
    │   ├── offer.py
    │   ├── publisher.py
    │   ├── subscription.py
    │   └── tenant.py
    │
    └── services/
        ├── audit_service.py
        ├── auth_service.py
        ├── authorization_service.py
        ├── build_engine.py
        ├── deployment_engine.py
        ├── entitlement_service.py
        ├── instance_limit_service.py
        ├── membership_service.py
        ├── static_package_service.py
        ├── subscription_lifecycle_service.py
        └── version_policy_service.py
```

## Other important roots

```text
data/packages/
├── quarantine/
├── rejected/
└── validated/

examples/
├── hello-app/
├── hello-app-1.1.0/
├── hello-app-2.0.0/
└── hello-app-3.0.0/

packages/contracts/
└── aaps-v1.schema.json

tools/
├── seed_rbac.py
└── validate_package.py
```

## Placement rules

| Need | Canonical location |
|---|---|
| New frontend route/page | `apps/web/src/app/<route>/page.tsx` |
| Shared frontend component | `apps/web/src/components/` |
| Cross-page React state/context | `apps/web/src/context/` |
| Frontend API/helper module | `apps/web/src/lib/` |
| Global MUI design tokens | `apps/web/src/theme.ts` |
| Root provider composition | `apps/web/src/app/providers.tsx` |
| FastAPI router | `services/api/app/routes/` |
| SQLAlchemy model | `services/api/app/models/` |
| Pydantic schema | `services/api/app/schemas/` |
| Business/security logic | `services/api/app/services/` |
| Authentication/config plumbing | `services/api/app/core/` |
| DB connection/base | `services/api/app/db/` |
| Schema migration | `services/api/alembic/versions/` |
| Utility/seed script | `tools/` |

## Guardrails

1. **Do not create a second provider root.** `apps/web/src/app/providers.tsx` is canonical.
2. **Do not recreate AppShell per page.** Use `apps/web/src/components/app-shell.tsx`.
3. **Do not create page-local tenant selectors.** Tenant selection belongs to `TenantProvider` + `TenantSelector`.
4. **Do not put API request logic directly into reusable UI when an existing `src/lib/*.ts` helper already owns that domain.**
5. **Do not put business authorization logic in FastAPI route bodies when it belongs in an existing service.**
6. **Do not edit runtime package data under `data/packages/validated` as application source code.**
7. Before creating a new file, search this structure for an existing equivalent first.
8. Prefer extending an existing file/module over creating a parallel implementation.
