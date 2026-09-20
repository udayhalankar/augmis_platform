from fastapi import FastAPI

from services.api.app.core.config import settings

from services.api.app.routes import (
    applications,
    audit,
    auth,
    health,
    instances,
    memberships,
    offers,
    operations,
    publishers,
    subscriptions,
    tenants,
)


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="AUGMIS SaaS Platform Control Plane API",
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
    publishers.router
)

app.include_router(
    tenants.router
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
        "platform": "AUGMIS SaaS Platform",
        "component": "Control Plane API",
        "version": "0.1.0",
        "docs": "/docs",
    }