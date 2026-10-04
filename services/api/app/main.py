# services/api/app/main.py

from fastapi import FastAPI

from fastapi.middleware.cors import (
    CORSMiddleware,
)

from services.api.app.core.config import (
    settings,
)

from services.api.app.routes import (
    applications,
    audit,
    auth,
    health,
    instances,
    invitations,
    memberships,
    offers,
    operations,
     platform_settings,
    publishers,
    subscriptions,
    tenants,
    tenant_users,
    webhooks,
)


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "AUGMIS SaaS Platform "
        "Control Plane API"
    ),
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        settings.cors_origin_list
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(
    auth.router
)

app.include_router(
    health.router
)

app.include_router(
    operations.router
)

app.include_router(
    audit.router
)

app.include_router(
    platform_settings.router
)

app.include_router(
    publishers.router
)

app.include_router(
    tenants.router
)

app.include_router(
    tenant_users.router
)

app.include_router(
    invitations.router
)

app.include_router(
    webhooks.router
)

app.include_router(
    memberships.router
)

app.include_router(
    applications.router
)

app.include_router(
    offers.router
)

app.include_router(
    subscriptions.router
)

app.include_router(
    instances.router
)


@app.get("/")
def root():

    return {
        "platform":
            "AUGMIS SaaS Platform",

        "component":
            "Control Plane API",

        "version":
            "0.1.0",

        "docs":
            "/docs",
    }