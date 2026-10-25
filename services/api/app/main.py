# services/api/app/main.py

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from fastapi.middleware.cors import (
    CORSMiddleware,
)

from services.api.app.core.config import (
    settings,
    validate_production_ingress_config,
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
    rbac_admin,
    subscriptions,
    runtime_control,
    tenants,
    tenant_users,
    techtango_integration,
    webhooks,
)


from services.api.app.services.security_release_gate import require_safe_runtime_exposure

require_safe_runtime_exposure()

# Invoked once the independent production-release gate is legitimately opened.
# Its validation can also be exercised independently while the gate is closed.
if settings.app_env.strip().lower() in ("production", "prod"):
    validate_production_ingress_config(settings)
    if not (1 <= settings.runtime_gateway_request_max_mb <= 250
            and 1 <= settings.runtime_gateway_response_max_mb <= 250
            and 3 <= settings.runtime_gateway_socket_timeout_seconds <= 60):
        raise RuntimeError("R04_GATEWAY_RESOURCE_CONFIG_INVALID")

app = FastAPI(
    title=settings.app_name,

    version="0.1.0",

    description=(
        "AUGMIS SaaS Platform "
        "Control Plane API"
    ),
)


# ============================================================
# CORS
# ============================================================


app.add_middleware(
    CORSMiddleware,

    allow_origins=(
        settings.cors_origin_list
    ),

    allow_credentials=True,

    allow_methods=[
        "*"
    ],

    allow_headers=[
        "*"
    ],
)


# Production API accepts only the explicitly approved public/private Hosts.
# Do not grant authority to X-Forwarded-*; trusted proxy peers must be
# configured at the ALB/network and Uvicorn launch boundaries separately.
if settings.app_env.strip().lower() in ("production", "prod"):
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.api_trusted_host_list,
        www_redirect=False,
    )

# R04: API control-plane hardening. Do not apply a universal CSP to
# untrusted static applications or publisher-hosted gateway responses.
# Their existing per-route policies remain authoritative.
@app.middleware("http")
async def _r04_control_plane_headers(request, call_next):
    response = await call_next(request)
    if settings.app_env.strip().lower() not in ("prod", "production"):
        return response  # No change to existing development response behavior.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if not request.url.path.startswith(("/api/v1/runtime-gateway/", "/api/v1/static-runtime/")):
        response.headers.setdefault("X-Frame-Options", "DENY")
    return response

# ============================================================
# AUTHENTICATION
# ============================================================


app.include_router(
    auth.router
)


# ============================================================
# PLATFORM HEALTH / OPERATIONS
# ============================================================


app.include_router(
    health.router
)


app.include_router(
    operations.router
)


# ============================================================
# AUDIT
# ============================================================


app.include_router(
    audit.router
)


# ============================================================
# PLATFORM SETTINGS
# ============================================================


app.include_router(
    platform_settings.router
)


# ============================================================
# PUBLISHER
# ============================================================


app.include_router(
    publishers.router
)


# ============================================================
# TENANTS
# ============================================================


app.include_router(
    tenants.router
)

app.include_router(techtango_integration.router)


# ============================================================
# TENANT USERS
# ============================================================


app.include_router(
    tenant_users.router
)


# ============================================================
# TENANT INVITATIONS
# ============================================================


app.include_router(
    invitations.router
)


# ============================================================
# EXTERNAL WEBHOOKS
# ============================================================


app.include_router(
    webhooks.router
)


# ============================================================
# CURRENT USER MEMBERSHIPS
# ============================================================


app.include_router(
    memberships.router
)


# ============================================================
# RBAC ADMINISTRATION
# ============================================================


app.include_router(
    rbac_admin.router
)


# ============================================================
# APPLICATIONS
# ============================================================


app.include_router(
    applications.router
)


# ============================================================
# MARKETPLACE OFFERS
# ============================================================


app.include_router(
    offers.router
)


# ============================================================
# SUBSCRIPTIONS
# ============================================================


app.include_router(
    subscriptions.router
)


# ============================================================
# APPLICATION INSTANCES / RUNTIME
# ============================================================


app.include_router(
    instances.router
)


# ============================================================
# ROOT
# ============================================================


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

# B1/B2 runtime control routes with backend authorization.
app.include_router(runtime_control.router)


# C1-D1: observe host readiness at startup; do not take the entire management
# API offline merely because Docker is temporarily unavailable. Each generic
# deployment rechecks readiness before reserving any database resources.
def _c1d_record_runtime_host_readiness():
    import logging
    from services.api.app.services.runtime_host_readiness import check_runtime_host
    result = check_runtime_host()
    app.state.runtime_host_readiness = result
    logging.getLogger('uvicorn.error').info('runtime_host_state=%s code=%s', result.state, result.code)

from contextlib import asynccontextmanager

# Preserve existing application startup and shutdown handlers.
_c1d_previous_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _c1d_lifespan(asgi_app: FastAPI):
    async with _c1d_previous_lifespan(asgi_app) as state:
        _c1d_record_runtime_host_readiness()
        yield state


app.router.lifespan_context = _c1d_lifespan

# C1-D4: reuse existing FastAPI auth dependency; add session lifecycle and admin settings.
from services.api.app.routes import session_security as c1d4_session_routes
# Fail startup rather than silently set an insecure production session cookie.
c1d4_session_routes.cookie_name()
if settings.app_env.lower() in ("production", "prod"):
    if settings.jwt_algorithm not in ("HS256", "HS384", "HS512") or len(settings.jwt_secret) < 32:
        raise RuntimeError("Production JWT configuration requires an approved HMAC algorithm and 32+ byte secret")
app.include_router(c1d4_session_routes.router)
