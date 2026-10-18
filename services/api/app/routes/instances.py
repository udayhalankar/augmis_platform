from __future__ import annotations

import re
import uuid
import hashlib
import http.client
import ipaddress
import secrets
import socket
import threading
import time

from urllib.parse import (
    quote,
    urlencode,
    urlparse,
)

from datetime import (
    datetime,
    timezone,
)

# from services.api.app import db
from services.api.app.services.audit_service import (
    record_audit_event,
)

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)

from fastapi.responses import (
    RedirectResponse,
    Response,
)


from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.core.auth import (
    get_current_user,
)

from services.api.app.db.session import (
    get_db,
)

from services.api.app.models.iam import (
    User,
)

from services.api.app.models.platform import (
    Application,
    ApplicationBuild,
    ApplicationDeployment,
    ApplicationInstance,
    ApplicationVersion,
    Tenant,
)

from services.api.app.schemas.instance import (
    InstanceDeployRequest,
    InstanceUpgradeRequest,
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_tenant_permission,
)

from services.api.app.services.crud_runtime_assertions import make_crud_request_assertion
from services.api.app.services.private_crud_runtime import CrudRuntimeError
from services.api.app.services.dashboard_runtime_assertions import (
    ASSERTION_HEADER,
    AssertionIssuanceError,
    make_dashboard_request_assertion,
    should_forward_request_header,
    should_forward_response_header,
)

from services.api.app.services.tenant_application_runtime_control import (
    get_runtime_launch_epoch, require_runtime_launch_allowed, set_runtime_desired_state,
)
from services.api.app.services.runtime_controls_service import start_scoped_container
from services.api.app.services.deployment_engine import (
    DeploymentError,
    start_container,
    stop_container,
)
from services.api.app.services.runtime_log_archive import (
    archive_before_removal,
    archive_failed_start,
)

from services.api.app.services.entitlement_service import (
    EntitlementError,
    require_active_entitlement,
    require_active_subscription,
)

from services.api.app.services.instance_limit_service import (
    InstanceLimitError,
    acquire_instance_limit_lock,
    require_instance_capacity,
)

from services.api.app.services.version_policy_service import (
    VersionPolicyError,
    require_subscription_version_allowed,
)


from services.api.app.services.dashboard_instance_reservation import (
    is_two_phase_app, reserve_dashboard_instance, activate_reserved_dashboard,
    cancel_reserved_dashboard,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["Runtime"],
)


def safe_name(
    value: str,
) -> str:

    value = value.lower()

    value = re.sub(
        r"[^a-z0-9-]",
        "-",
        value,
    )

    value = re.sub(
        r"-+",
        "-",
        value,
    )

    return value.strip("-")

# =========================================================
# STEP 3C-3A.1 — SECURE RUNTIME GATEWAY
# =========================================================

_RUNTIME_GATEWAY_SESSION_SECONDS = (
    8 * 60 * 60
)

_RUNTIME_GATEWAY_TICKET_SECONDS = 60

from services.api.app.services.shared_runtime_sessions import RedisSessionMap, shared_session_map

_RUNTIME_GATEWAY_SESSIONS = shared_session_map("container")

_RUNTIME_GATEWAY_LOCK = (
    threading.Lock()
)


_RUNTIME_GATEWAY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def _gateway_cookie_name(
    gateway_id: str,
) -> str:

    safe = re.sub(
        r"[^A-Za-z0-9_-]",
        "",
        gateway_id,
    )

    return (
        "augmis_rt_"
        + safe[:24]
    )


def _runtime_gateway_cleanup() -> None:

    now = time.time()

    with _RUNTIME_GATEWAY_LOCK:

        expired = [
            gateway_id

            for gateway_id, session
            in _RUNTIME_GATEWAY_SESSIONS.items()

            if float(
                session.get(
                    "expires_at",
                    0,
                )
            )
            <= now
        ]

        for gateway_id in expired:

            _RUNTIME_GATEWAY_SESSIONS.pop(
                gateway_id,
                None,
            )


def _hash_gateway_secret(
    value: str,
) -> str:

    return hashlib.sha256(
        value.encode(
            "utf-8"
        )
    ).hexdigest()


def _issue_runtime_gateway_url(
    *,
    db: Session,
    request: Request,
    current_user: User,
    tenant: Tenant,
    application: Application,
    instance_id: uuid.UUID,
) -> str:

    _runtime_gateway_cleanup()

    gateway_id = (
        secrets.token_urlsafe(
            24
        )
    )

    ticket = (
        secrets.token_urlsafe(
            32
        )
    )

    now = time.time()

    with _RUNTIME_GATEWAY_LOCK:

        _RUNTIME_GATEWAY_SESSIONS[
            gateway_id
        ] = {
            "user_id":
                current_user.id,

            "tenant_id":
                tenant.id,

            "application_id":
                application.id,

            "instance_id":
                instance_id,

            "launch_epoch": get_runtime_launch_epoch(db, tenant.id, application.id),

            # The launch ticket becomes the HttpOnly gateway
            # cookie after the one-time URL exchange. Only its
            # SHA-256 hash is retained server-side.
            "session_hash":
                _hash_gateway_secret(
                    ticket
                ),

            "ticket_used":
                False,

            "ticket_expires_at":
                now
                + _RUNTIME_GATEWAY_TICKET_SECONDS,

            "expires_at":
                now
                + _RUNTIME_GATEWAY_SESSION_SECONDS,
        }

    base_url = str(
        request.base_url
    ).rstrip("/")

    return (
        f"{base_url}"
        f"/api/v1/runtime-gateway/"
        f"{gateway_id}/"
        f"?ticket={quote(ticket)}"
    )


def _validate_private_runtime_url(
    runtime_url: str,
):

    parsed = urlparse(
        runtime_url
    )

    if parsed.scheme not in {
        "http",
        "https",
    }:
        raise HTTPException(
            status_code=502,
            detail=(
                "Runtime gateway rejected "
                "an unsupported internal URL."
            ),
        )

    hostname = str(
        parsed.hostname or ""
    ).strip()

    if not hostname:
        raise HTTPException(
            status_code=502,
            detail=(
                "Runtime gateway received "
                "an invalid internal host."
            ),
        )

    if hostname.lower() == "localhost":
        return parsed

    try:
        addresses = {
            item[4][0]

            for item in socket.getaddrinfo(
                hostname,
                parsed.port
                or (
                    443
                    if parsed.scheme
                    == "https"
                    else 80
                ),
            )
        }

    except socket.gaierror as error:

        raise HTTPException(
            status_code=502,
            detail=(
                "Runtime gateway could not "
                "resolve the internal runtime."
            ),
        ) from error

    if not addresses:
        raise HTTPException(
            status_code=502,
            detail=(
                "Runtime gateway could not "
                "resolve the internal runtime."
            ),
        )

    for address in addresses:

        try:
            ip = ipaddress.ip_address(
                address
            )

        except ValueError:

            raise HTTPException(
                status_code=502,
                detail=(
                    "Runtime gateway resolved "
                    "an invalid internal address."
                ),
            )

        if not (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
        ):
            raise HTTPException(
                status_code=502,
                detail=(
                    "Runtime gateway refused "
                    "to proxy to a public host."
                ),
            )

    return parsed


def _get_runtime_gateway_context(
    *,
    db: Session,
    gateway_id: str,
    cookie_secret: str,
):

    _runtime_gateway_cleanup()

    with _RUNTIME_GATEWAY_LOCK:

        session = (
            _RUNTIME_GATEWAY_SESSIONS.get(
                gateway_id
            )
        )

        if session:
            session = dict(
                session
            )

    if not session:
        raise HTTPException(
            status_code=401,
            detail=(
                "Runtime gateway session "
                "is invalid or expired."
            ),
        )

    if (
        not cookie_secret
        or not secrets.compare_digest(
            _hash_gateway_secret(
                cookie_secret
            ),
            str(
                session.get(
                    "session_hash",
                    "",
                )
            ),
        )
    ):
        raise HTTPException(
            status_code=401,
            detail=(
                "Runtime gateway session "
                "cookie is invalid."
            ),
        )

    user = db.get(
        User,
        session["user_id"],
    )

    if not user:
        raise HTTPException(
            status_code=403,
            detail=(
                "Runtime gateway user "
                "no longer exists."
            ),
        )

    tenant = db.get(
        Tenant,
        session["tenant_id"],
    )

    if not tenant:
        raise HTTPException(
            status_code=404,
            detail="Tenant not found",
        )

    if tenant.status != "active":
        raise HTTPException(
            status_code=403,
            detail="Tenant is not active",
        )

    application = db.get(
        Application,
        session[
            "application_id"
        ],
    )

    if not application:
        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    try:
        require_tenant_permission(
            db=db,
            user=user,
            tenant_id=tenant.id,
            permission_code=(
                "application.instance.view"
            ),
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    try:
        subscription = (
            require_active_subscription(
                db=db,
                tenant_id=tenant.id,
                application_id=(
                    application.id
                ),
            )
        )

        require_active_entitlement(
            db=db,
            tenant_id=tenant.id,
            application_id=(
                application.id
            ),
            entitlement_code=(
                "application.deploy"
            ),
        )

    except EntitlementError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    require_runtime_launch_allowed(db, tenant.id, application.id)
    if int(session.get("launch_epoch", -1)) != get_runtime_launch_epoch(db, tenant.id, application.id):
        raise HTTPException(status_code=403, detail="Runtime gateway session was revoked by an application stop.")

    instance = db.get(
        ApplicationInstance,
        session["instance_id"],
    )

    if not instance:
        raise HTTPException(
            status_code=404,
            detail=(
                "Application instance "
                "no longer exists."
            ),
        )

    if (
        instance.tenant_id
        != tenant.id
        or instance.application_id
        != application.id
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Runtime gateway tenant "
                "boundary validation failed."
            ),
        )

    if instance.status != "running":
        raise HTTPException(
            status_code=409,
            detail=(
                "Application instance "
                "is not running."
            ),
        )

    active_version = db.get(
        ApplicationVersion,
        instance.active_version_id,
    )

    if not active_version:
        raise HTTPException(
            status_code=409,
            detail=(
                "Application instance "
                "references a missing version."
            ),
        )

    try:
        require_subscription_version_allowed(
            db=db,
            subscription=subscription,
            target_version=active_version,
        )

    except VersionPolicyError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    deployment = db.scalar(
        select(
            ApplicationDeployment
        )
        .where(
            ApplicationDeployment.instance_id
            == instance.id,

            ApplicationDeployment.status
            == "running",
        )
        .order_by(
            ApplicationDeployment
            .created_at
            .desc()
        )
    )

    if (
        not deployment
        or not deployment.runtime_url
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Running instance has "
                "no active runtime."
            ),
        )

    parsed_runtime = (
        _validate_private_runtime_url(
            deployment.runtime_url
        )
    )

    return {
        "session":
            session,

        "user":
            user,

        "tenant":
            tenant,

        "application":
            application,

        "subscription":
            subscription,

        "instance":
            instance,

        "version":
            active_version,

        "deployment":
            deployment,

        "parsed_runtime":
            parsed_runtime,
    }


def _rewrite_gateway_location(
    *,
    location: str,
    parsed_runtime,
    gateway_base: str,
) -> str:

    clean = str(
        location or ""
    ).strip()

    if not clean:
        return clean

    if clean.startswith(
        "/"
    ):
        return (
            gateway_base
            + clean.lstrip("/")
        )

    parsed = urlparse(
        clean
    )

    if (
        parsed.scheme
        and parsed.hostname
        and parsed.hostname
        == parsed_runtime.hostname
        and parsed.port
        == parsed_runtime.port
    ):

        rewritten = (
            gateway_base
            + parsed.path.lstrip("/")
        )

        if parsed.query:
            rewritten += (
                "?"
                + parsed.query
            )

        return rewritten

    return clean


def _rewrite_gateway_html(
    *,
    payload: bytes,
    gateway_base: str,
) -> bytes:

    try:
        html = payload.decode(
            "utf-8"
        )

    except UnicodeDecodeError:
        return payload

    html = re.sub(
        r'''(?i)\b(href|src|action)=([\"'])/(?!/)''',
        lambda match: (
            f"{match.group(1)}="
            f"{match.group(2)}"
            f"{gateway_base}"
        ),
        html,
    )

    html = re.sub(
        r'''(?i)url\(\s*([\"']?)/(?!/)''',
        lambda match: (
            "url("
            + match.group(1)
            + gateway_base
        ),
        html,
    )

    if "<base " not in html.lower():

        html = re.sub(
            r"(?i)<head([^>]*)>",
            lambda match: (
                match.group(0)
                + (
                    '<base href="'
                    + gateway_base
                    + '">'
                )
            ),
            html,
            count=1,
        )

    return html.encode(
        "utf-8"
    )


async def _proxy_runtime_gateway_request(
    *,
    request: Request,
    gateway_id: str,
    path: str,
    db: Session,
):

    cookie_name = (
        _gateway_cookie_name(
            gateway_id
        )
    )

    ticket = str(
        request.query_params.get(
            "ticket",
            "",
        )
    ).strip()

    if ticket:

        _runtime_gateway_cleanup()

        with _RUNTIME_GATEWAY_LOCK:

            session = (
                _RUNTIME_GATEWAY_SESSIONS.get(
                    gateway_id
                )
            )

            now = time.time()

            valid_ticket = (
                bool(session)
                and not bool(
                    session.get(
                        "ticket_used"
                    )
                )
                and float(
                    session.get(
                        "ticket_expires_at",
                        0,
                    )
                )
                > now
                and secrets.compare_digest(
                    _hash_gateway_secret(
                        ticket
                    ),
                    str(
                        session.get(
                            "session_hash",
                            "",
                        )
                    ),
                )
            )

            if valid_ticket:
                if isinstance(_RUNTIME_GATEWAY_SESSIONS, RedisSessionMap):
                    valid_ticket = _RUNTIME_GATEWAY_SESSIONS.consume_ticket(
                        gateway_id, expected_hash=_hash_gateway_secret(ticket), now=now,
                    )
                else:
                    session["ticket_used"] = True

        if not valid_ticket:
            raise HTTPException(
                status_code=401,
                detail=(
                    "Runtime gateway launch "
                    "ticket is invalid or expired."
                ),
            )

        clean_url = (
            f"/api/v1/runtime-gateway/"
            f"{gateway_id}/"
        )

        response = RedirectResponse(
            url=clean_url,
            status_code=303,
        )

        response.set_cookie(
            key=cookie_name,
            value=ticket,
            max_age=(
                _RUNTIME_GATEWAY_SESSION_SECONDS
            ),
            httponly=True,
            secure=(
                request.url.scheme
                == "https"
            ),
            samesite="lax",
            path=(
                f"/api/v1/runtime-gateway/"
                f"{gateway_id}"
            ),
        )

        return response

    cookie_secret = str(
        request.cookies.get(
            cookie_name,
            "",
        )
    ).strip()

    context = (
        _get_runtime_gateway_context(
            db=db,
            gateway_id=gateway_id,
            cookie_secret=(
                cookie_secret
            ),
        )
    )

    parsed_runtime = (
        context[
            "parsed_runtime"
        ]
    )

    if ".." in [
        segment

        for segment
        in str(
            path or ""
        ).split("/")
    ]:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid runtime path."
            ),
        )

    runtime_base_path = str(
        parsed_runtime.path
        or ""
    ).rstrip("/")

    requested_path = (
        "/"
        + str(
            path or ""
        ).lstrip("/")
    )

    upstream_path = (
        runtime_base_path
        + requested_path
    )

    if not upstream_path:
        upstream_path = "/"

    query_items = [
        (
            key,
            value,
        )

        for key, value
        in request.query_params.multi_items()

        if key not in {
            "ticket",
        }
    ]

    if query_items:
        upstream_path += (
            "?"
            + urlencode(
                query_items,
                doseq=True,
            )
        )

    outgoing_headers = {}

    # Never forward caller-controlled AUGMIS identity or assertion headers.
    # Keep ordinary request headers for existing applications.
    for key, value in request.headers.items():
        if not should_forward_request_header(
            key, _RUNTIME_GATEWAY_HOP_HEADERS
        ):
            continue
        outgoing_headers[key] = value

    outgoing_headers[
        "Accept-Encoding"
    ] = "identity"

    outgoing_headers[
        "X-Augmis-Tenant-Id"
    ] = str(
        context[
            "tenant"
        ].id
    )

    outgoing_headers[
        "X-Augmis-Application-Id"
    ] = str(
        context[
            "application"
        ].id
    )

    outgoing_headers[
        "X-Augmis-Instance-Id"
    ] = str(
        context[
            "instance"
        ].id
    )

    body = await request.body()
    # C1-B4: only signed gateway context may access the reference-app API.
    # There is no trusted browser-supplied tenant, identity or assertion.
    if (context["version"].manifest.get("metadata") or {}).get("id") == "augmis-crud-reference":
        try:
            # No general app-record permission catalogue exists yet. Require
            # tenant deployment permission for reference-app mutations.
            if request.method in {"POST", "PUT", "DELETE"}:
                require_tenant_permission(
                    db=db, user=context["user"], tenant_id=context["tenant"].id,
                    permission_code="application.deploy")
            crud_assertion = make_crud_request_assertion(
                context=context, method=request.method,
                relative_path=str(path or ""), body=body,
                raw_query=(upstream_path.split("?", 1)[1] if "?" in upstream_path else ""),
            ) if str(path or "").startswith("api/") else None
            if str(path or "").startswith("api/") and not crud_assertion:
                raise HTTPException(status_code=403, detail="Private CRUD assertion not enabled")
            if crud_assertion:
                outgoing_headers[ASSERTION_HEADER] = crud_assertion
        except AuthorizationError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except CrudRuntimeError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    # C1-C3: generic private database AAPS. The manifest route contract is
    # authoritative; never forward an unsigned /api/ request or trust a caller
    # supplied identity header. Existing C1-B4 CRUD assertions are unchanged.
    if ((context["version"].manifest.get("addons") or {}).get("database") or {}).get("schema") is not None and \
            (context["version"].manifest.get("metadata") or {}).get("id") != "augmis-crud-reference":
        from services.api.app.services.aaps_runtime_assertions import make_aaps_request_assertion
        if str(path or "").startswith("api/"):
            try:
                if request.method in {"POST","PUT","PATCH","DELETE"}:
                    require_tenant_permission(db=db,user=context["user"],
                        tenant_id=context["tenant"].id,permission_code="application.deploy")
                outgoing_headers[ASSERTION_HEADER]=make_aaps_request_assertion(
                    context=context,method=request.method,relative_path=str(path or ""),body=body,
                    raw_query=(upstream_path.split("?",1)[1] if "?" in upstream_path else ""))
            except AuthorizationError as error:
                raise HTTPException(status_code=403,detail=str(error)) from error
            except CrudRuntimeError as error:
                raise HTTPException(status_code=403,detail=str(error)) from error

    # Opt-in pilot: revalidated gateway context is the ONLY claims source.
    # For other AAPS apps this returns None and changes no behavior.
    try:
        assertion = make_dashboard_request_assertion(
            context=context,
            method=request.method,
            relative_path=str(path or "").lstrip("/"),
        )
    except AssertionIssuanceError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail="Dashboard runtime authorization unavailable.",
        ) from error
    if assertion is not None:
        outgoing_headers[ASSERTION_HEADER] = assertion

    port = (
        parsed_runtime.port

        or (
            443

            if parsed_runtime.scheme
            == "https"

            else 80
        )
    )

    connection_class = (
        http.client.HTTPSConnection

        if parsed_runtime.scheme
        == "https"

        else http.client.HTTPConnection
    )

    connection = connection_class(
        host=(
            parsed_runtime.hostname
        ),
        port=port,
        timeout=30,
    )

    try:

        connection.request(
            method=(
                request.method
            ),
            url=(
                upstream_path
            ),
            body=(
                body
                if body
                else None
            ),
            headers=(
                outgoing_headers
            ),
        )

        upstream = (
            connection.getresponse()
        )

        payload = (
            upstream.read()
        )

        status_code = (
            upstream.status
        )

        upstream_headers = (
            upstream.getheaders()
        )

    except (
        OSError,
        http.client.HTTPException,
    ) as error:

        raise HTTPException(
            status_code=502,
            detail=(
                "Runtime gateway could not "
                "reach the application."
            ),
        ) from error

    finally:

        connection.close()

    gateway_base = (
        f"/api/v1/runtime-gateway/"
        f"{gateway_id}/"
    )

    response_headers = {}

    content_type = ""

    for key, value in (
        upstream_headers
    ):

        lower_key = (
            key.lower()
        )

        if not should_forward_response_header(
            key, _RUNTIME_GATEWAY_HOP_HEADERS
        ):
            continue

        if lower_key == "location":

            value = (
                _rewrite_gateway_location(
                    location=value,
                    parsed_runtime=(
                        parsed_runtime
                    ),
                    gateway_base=(
                        gateway_base
                    ),
                )
            )

        if lower_key == "content-type":
            content_type = value

        response_headers[
            key
        ] = value

    if (
        "text/html"
        in content_type.lower()
        and payload
    ):

        payload = (
            _rewrite_gateway_html(
                payload=payload,
                gateway_base=(
                    gateway_base
                ),
            )
        )

    response_headers[
        "Cache-Control"
    ] = "no-store"

    response_headers[
        "X-Content-Type-Options"
    ] = "nosniff"

    return Response(
        content=payload,
        status_code=status_code,
        headers=response_headers,
    )


@router.api_route(
    "/runtime-gateway/{gateway_id}/{path:path}",
    methods=[
        "GET",
        "HEAD",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ],
)
async def runtime_gateway(
    gateway_id: str,
    path: str,
    request: Request,
    db: Session = Depends(
        get_db
    ),
):

    return await (
        _proxy_runtime_gateway_request(
            request=request,
            gateway_id=gateway_id,
            path=path,
            db=db,
        )
    )


@router.post(
    "/instances/{instance_id}/upgrade",
)
def upgrade_application_instance(
    instance_id: uuid.UUID,
    payload: InstanceUpgradeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # The HTTP route keeps authoritative user authorization; the trusted
    # auto-upgrade worker calls the shared service without impersonating a user.
    instance = db.get(ApplicationInstance, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    try:
        require_tenant_permission(db=db, user=current_user,
                                  tenant_id=instance.tenant_id,
                                  permission_code="application.deploy")
    except AuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    require_runtime_launch_allowed(db, instance.tenant_id, instance.application_id)
    from services.api.app.services.runtime_upgrade_executor import perform_instance_upgrade
    return perform_instance_upgrade(
        db=db, instance_id=instance_id, target_version_id=payload.target_version_id,
        actor_user_id=current_user.id, system_actor=False,
    )


# B4 Pass 3H-5F: development-only, entitlement-gated two-phase pilot.
# Requires explicit activation; never creates an offer or publishes a version.
@router.post(
    "/tenants/{tenant_id}/application-versions/{version_id}/reserve",
    status_code=201,
)
def reserve_dashboard_instance_route(
    tenant_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: InstanceDeployRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return reserve_dashboard_instance(
        db=db, tenant_id=tenant_id, version_id=version_id,
        name=payload.name, user=current_user,
    )


@router.post("/instances/{instance_id}/activate-reserved")
def activate_reserved_dashboard_route(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return activate_reserved_dashboard(db=db, instance_id=instance_id,
                                       user=current_user)


@router.post("/instances/{instance_id}/cancel-reservation")
def cancel_reserved_dashboard_route(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return cancel_reserved_dashboard(db=db, instance_id=instance_id,
                                     user=current_user)


@router.post(
    "/tenants/{tenant_id}/application-versions/{version_id}/deploy",
    status_code=201,
)


def deploy_application(
    tenant_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: InstanceDeployRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    # =====================================================
    # 1. TENANT
    # =====================================================

    tenant = db.get(
        Tenant,
        tenant_id,
    )

    if not tenant:

        raise HTTPException(
            status_code=404,
            detail="Tenant not found",
        )

    if tenant.status != "active":

        raise HTTPException(
            status_code=409,
            detail="Tenant is not active",
        )

    # =====================================================
    # 2. RBAC
    # =====================================================

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=tenant.id,
            permission_code="application.deploy",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 3. APPLICATION VERSION
    # =====================================================

    version = db.get(
        ApplicationVersion,
        version_id,
    )

    if not version:

        raise HTTPException(
            status_code=404,
            detail="Application version not found",
        )

    if version.status != "image_ready":

        raise HTTPException(
            status_code=409,
            detail=(
                "Application version does not "
                "have a ready image."
            ),
        )

    application = db.get(
        Application,
        version.application_id,
    )

    if not application:

        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    # Never use the immediate-deploy path for the opt-in dashboard pilot.
    # Keep normal applications unaffected and all entitlement checks intact.
    if is_two_phase_app(application.id):
        raise HTTPException(
            status_code=409,
            detail="Dashboard pilot requires reserve -> provision -> activate",
        )

    # =====================================================
    # 4. SUBSCRIPTION + ENTITLEMENT + VERSION POLICY
    # =====================================================

    try:

        subscription = require_active_subscription(
            db=db,
            tenant_id=tenant.id,
            application_id=application.id,
        )

        entitlement = require_active_entitlement(
            db=db,
            tenant_id=tenant.id,
            application_id=application.id,
            entitlement_code="application.deploy",
        )

        require_subscription_version_allowed(
            db=db,
            subscription=subscription,
            target_version=version,
        )

    except (
        EntitlementError,
        VersionPolicyError,
    ) as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    acquire_instance_limit_lock(db=db, tenant_id=tenant.id,
                                application_id=application.id)
    require_runtime_launch_allowed(db, tenant.id, application.id)

    # =====================================================
    # 5. INSTANCE LIMIT
    #
    # MUST happen before ApplicationInstance is created.
    # =====================================================

    try:

        require_instance_capacity(
            db=db,
            tenant_id=tenant.id,
            application_id=application.id,
            entitlement=entitlement,
        )

    except InstanceLimitError as error:

        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error

    require_runtime_launch_allowed(db, tenant.id, application.id)

    # =====================================================
    # 6. READY BUILD
    # =====================================================

    build = db.scalar(
        select(ApplicationBuild)
        .where(
            ApplicationBuild.application_version_id
            == version.id,

            ApplicationBuild.status
            == "ready",
        )
        .order_by(
            ApplicationBuild.created_at.desc(),
        )
    )

    if not build:

        raise HTTPException(
            status_code=409,
            detail="No ready build found",
        )

    if not build.image_ref:

        raise HTTPException(
            status_code=409,
            detail="Build has no image reference",
        )

    # =====================================================
    # 7. CREATE LOGICAL INSTANCE
    # =====================================================

    short_id = uuid.uuid4().hex[:8]

    instance_key = (
        f"{tenant.slug}-"
        f"{application.app_key}-"
        f"{short_id}"
    )

    instance_name = (
        payload.name
        or f"{application.name} - {tenant.name}"
    )

    instance = ApplicationInstance(
        tenant_id=tenant.id,
        application_id=application.id,
        active_version_id=version.id,
        instance_key=instance_key,
        name=instance_name,
        status="provisioning",
    )

    db.add(instance)

    db.flush()

    # =====================================================
    # 8. CREATE DEPLOYMENT RECORD
    # =====================================================

    container_name = safe_name(
        f"augmis-"
        f"{tenant.slug}-"
        f"{application.app_key}-"
        f"{short_id}"
    )

    deployment = ApplicationDeployment(
        instance_id=instance.id,
        application_version_id=version.id,
        build_id=build.id,
        status="deploying",
        container_name=container_name,
        health_status="starting",
    )

    db.add(deployment)

    # This commit releases the advisory transaction lock,
    # but the new instance is already persisted as
    # "provisioning", which is counted as active capacity.
    db.commit()

    db.refresh(instance)
    db.refresh(deployment)

    # =====================================================
    # 9. START CONTAINER
    # =====================================================

    try:

        result = start_scoped_container(
            db=db, instance=instance, deployment=deployment, build=build,
            manifest=version.manifest,
            container_name=container_name,
            labels={
                "augmis.managed": "true",

                "augmis.instance_id":
                    str(instance.id),

                "augmis.tenant_id":
                    str(tenant.id),

                "augmis.application_id":
                    str(application.id),
            },
        )

    except DeploymentError as error:

        instance.status = "failed"

        deployment.status = "failed"

        deployment.health_status = (
            "unhealthy"
        )

        deployment.error_message = (
            str(error)
        )
        archive_failed_start(deployment, error)

        db.commit()

        # Stable, user-safe quota error; preserve other deployment errors.
        if "tenant runtime container quota exceeded" in str(error).lower():
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "TENANT_CONTAINER_QUOTA_EXCEEDED",
                    "message": "The tenant's concurrent-container quota has been reached.",
                    "deploymentId": str(deployment.id),
                },
            ) from error

        raise HTTPException(
            status_code=422,
            detail={
                "message":
                    "Application deployment failed",

                "deploymentId":
                    str(deployment.id),

                "error":
                    str(error),
            },
        ) from error

        # =====================================================
        # 10. SUCCESS
        # =====================================================

    now = datetime.now(
        timezone.utc
    )

    deployment.container_id = (
        result["container_id"]
    )

    deployment.container_name = (
        result["container_name"]
    )

    deployment.host_port = (
        result["host_port"]
    )

    deployment.runtime_url = (
        result["runtime_url"]
    )

    deployment.status = "running"

    deployment.health_status = "healthy"

    deployment.deployed_at = now

    instance.status = "running"

    record_audit_event(
        db,
        action="application.deploy",
        resource_type="application_instance",
        resource_id=instance.id,
        actor_user_id=current_user.id,
        tenant_id=tenant.id,
        outcome="success",
        message="Application instance deployed successfully.",
        metadata={
            "applicationId":
                str(application.id),

            "versionId":
                str(version.id),

            "version":
                version.version,

            "deploymentId":
                str(deployment.id),

            "containerName":
                deployment.container_name,

            "hostPort":
                deployment.host_port,
        },
    )

    db.commit()

    db.refresh(instance)
    db.refresh(deployment)

    return {
        "status": "RUNNING",

        "tenant": {
            "id": str(tenant.id),
            "name": tenant.name,
        },

        "application": {
            "id": str(application.id),
            "name": application.name,
        },

        "instance": {
            "id": str(instance.id),

            "instanceKey":
                instance.instance_key,

            "name":
                instance.name,

            "status":
                instance.status,
        },

        "deployment": {
            "id":
                str(deployment.id),

            "containerId":
                deployment.container_id,

            "containerName":
                deployment.container_name,

            "hostPort":
                deployment.host_port,

            "url":
                deployment.runtime_url,

            "health":
                deployment.health_status,
        },
    }



@router.post(
    "/tenants/{tenant_id}/applications/{application_id}/open",
)
def open_containerized_application(
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Tenant-safe container application launcher.

    Reuses an existing running tenant/application instance.
    If none exists, deploys the subscription baseline version.

    Static web applications are intentionally excluded here and
    will be handled by Step 3C-3B.
    """

    # =====================================================
    # 1. TENANT + APPLICATION
    # =====================================================

    tenant = db.get(
        Tenant,
        tenant_id,
    )

    if not tenant:
        raise HTTPException(
            status_code=404,
            detail="Tenant not found",
        )

    if tenant.status != "active":
        raise HTTPException(
            status_code=409,
            detail="Tenant is not active",
        )

    application = db.get(
        Application,
        application_id,
    )

    if not application:
        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    # =====================================================
    # 2. TENANT RBAC
    #
    # Viewing/opening an existing runtime requires instance view.
    # First-time provisioning will still pass through the existing
    # deploy endpoint, which requires application.deploy.
    # =====================================================

    try:
        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=tenant.id,
            permission_code="application.instance.view",
        )

    except AuthorizationError as error:
        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 3. COMMERCIAL ACCESS
    # =====================================================

    try:
        subscription = require_active_subscription(
            db=db,
            tenant_id=tenant.id,
            application_id=application.id,
        )

        require_active_entitlement(
            db=db,
            tenant_id=tenant.id,
            application_id=application.id,
            entitlement_code="application.deploy",
        )

    except EntitlementError as error:
        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 4. SERIALIZE OPEN/DEPLOY FOR THIS TENANT + APP
    #
    # This prevents two simultaneous Open clicks from creating
    # two instances when the offer permits multiple instances.
    # =====================================================

    acquire_instance_limit_lock(
        db=db,
        tenant_id=tenant.id,
        application_id=application.id,
    )

    # An operator Stop overrides both reuse and first-time provisioning.
    require_runtime_launch_allowed(db, tenant.id, application.id)

    # =====================================================
    # 5. REUSE EXISTING RUNNING INSTANCE
    # =====================================================

    running_instance = db.scalar(
        select(ApplicationInstance)
        .where(
            ApplicationInstance.tenant_id
            == tenant.id,

            ApplicationInstance.application_id
            == application.id,

            ApplicationInstance.status
            == "running",
        )
        .order_by(
            ApplicationInstance.created_at.desc(),
        )
    )

    if running_instance:

        active_version = db.get(
            ApplicationVersion,
            running_instance.active_version_id,
        )

        if not active_version:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Running instance references a missing "
                    "application version."
                ),
            )

        if str(active_version.build_type or "").lower() == "static_web":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Static web applications are handled by "
                    "Step 3C-3B."
                ),
            )

        try:
            require_subscription_version_allowed(
                db=db,
                subscription=subscription,
                target_version=active_version,
            )

        except VersionPolicyError as error:
            raise HTTPException(
                status_code=403,
                detail=str(error),
            ) from error

        deployment = db.scalar(
            select(ApplicationDeployment)
            .where(
                ApplicationDeployment.instance_id
                == running_instance.id,

                ApplicationDeployment.status
                == "running",
            )
            .order_by(
                ApplicationDeployment.created_at.desc(),
            )
        )

        if (
            not deployment
            or not deployment.runtime_url
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Application instance is marked running but "
                    "has no active runtime URL."
                ),
            )

        gateway_url = _issue_runtime_gateway_url(
            db=db,
            request=request,
            current_user=current_user,
            tenant=tenant,
            application=application,
            instance_id=running_instance.id,
        )

        return {
            "status": "REUSED",
            "tenantId": str(tenant.id),
            "applicationId": str(application.id),
            "instanceId": str(running_instance.id),
            "versionId": str(active_version.id),
            "version": active_version.version,

            # IMPORTANT:
            # Never expose the direct container URL through Open Application.
            "runtimeUrl": gateway_url,
        }


    # =====================================================
    # 6. DO NOT CREATE A SECOND INSTANCE WHILE STARTING
    # =====================================================

    in_progress = db.scalar(
        select(ApplicationInstance)
        .where(
            ApplicationInstance.tenant_id
            == tenant.id,

            ApplicationInstance.application_id
            == application.id,

            ApplicationInstance.status.in_(
                (
                    "provisioning",
                    "upgrading",
                )
            ),
        )
        .order_by(
            ApplicationInstance.created_at.desc(),
        )
    )

    if in_progress:
        raise HTTPException(
            status_code=409,
            detail=(
                "Application runtime is already being prepared. "
                "Wait a moment and open it again."
            ),
        )

    # =====================================================
    # 7. RESOLVE SUBSCRIPTION BASELINE VERSION
    # =====================================================

    if not subscription.baseline_version_id:
        raise HTTPException(
            status_code=409,
            detail="Subscription has no baseline version.",
        )

    target_version = db.get(
        ApplicationVersion,
        subscription.baseline_version_id,
    )

    if not target_version:
        raise HTTPException(
            status_code=409,
            detail="Subscription baseline version not found.",
        )

    if target_version.application_id != application.id:
        raise HTTPException(
            status_code=409,
            detail=(
                "Subscription baseline version belongs to "
                "another application."
            ),
        )

    if str(target_version.build_type or "").lower() == "static_web":
        raise HTTPException(
            status_code=409,
            detail=(
                "Static web applications are handled by "
                "Step 3C-3B."
            ),
        )

    if target_version.status != "image_ready":
        raise HTTPException(
            status_code=409,
            detail=(
                "Application baseline version does not have "
                "a ready container image."
            ),
        )

    try:
        require_subscription_version_allowed(
            db=db,
            subscription=subscription,
            target_version=target_version,
        )

    except VersionPolicyError as error:
        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 8. DEPLOY THROUGH THE EXISTING, ALREADY-HARDENED
    #    DEPLOY ENDPOINT LOGIC
    # =====================================================

    result = deploy_application(
        tenant_id=tenant.id,
        version_id=target_version.id,
        payload=InstanceDeployRequest(
            name=(
                f"{application.name} - {tenant.name}"
            )
        ),
        db=db,
        current_user=current_user,
    )

    runtime_url = (
        result.get("deployment", {})
        .get("url")
    )

    instance_id = (
        result.get("instance", {})
        .get("id")
    )

    if not runtime_url or not instance_id:
        raise HTTPException(
            status_code=500,
            detail=(
                "Application deployment completed without a "
                "runtime URL or instance ID."
            ),
        )

    gateway_url = _issue_runtime_gateway_url(
    db=db,
    request=request,
    current_user=current_user,
    tenant=tenant,
    application=application,
    instance_id=uuid.UUID(
        str(instance_id)
    ),
)


    return {
        "status": "DEPLOYED",
        "tenantId": str(tenant.id),
        "applicationId": str(application.id),
        "instanceId": str(instance_id),
        "versionId": str(target_version.id),
        "version": target_version.version,
        "runtimeUrl": gateway_url,
    }



@router.get(
    "/tenants/{tenant_id}/instances",
)
def list_tenant_instances(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    tenant = db.get(
        Tenant,
        tenant_id,
    )

    if not tenant:

        raise HTTPException(
            status_code=404,
            detail="Tenant not found",
        )

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=tenant.id,
            permission_code="application.instance.view",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    instances = list(
        db.scalars(
            select(ApplicationInstance)
            .where(
                ApplicationInstance.tenant_id
                == tenant_id,
            )
            .order_by(
                ApplicationInstance
                .created_at
                .desc(),
            )
        )
    )

    return [
        {
            "id":
                str(instance.id),

            "applicationId":
                str(instance.application_id),

            "versionId":
                str(instance.active_version_id),

            "instanceKey":
                instance.instance_key,

            "name":
                instance.name,

            "status":
                instance.status,
        }

        for instance in instances
    ]



@router.get(
    "/instances/{instance_id}",
)
def get_application_instance(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    instance = db.get(
        ApplicationInstance,
        instance_id,
    )

    if not instance:

        raise HTTPException(
            status_code=404,
            detail="Instance not found",
        )

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=instance.tenant_id,
            permission_code="application.instance.view",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    application = db.get(
        Application,
        instance.application_id,
    )

    version = db.get(
        ApplicationVersion,
        instance.active_version_id,
    )

    deployment = db.scalar(
        select(ApplicationDeployment)
        .where(
            ApplicationDeployment.instance_id
            == instance.id,

            ApplicationDeployment.status
            == "running",
        )
        .order_by(
            ApplicationDeployment.created_at.desc(),
        )
    )

    return {
        "id": str(instance.id),

        "instanceKey":
            instance.instance_key,

        "name":
            instance.name,

        "status":
            instance.status,

        "tenantId":
            str(instance.tenant_id),

        "application": {
            "id": str(application.id)
            if application
            else None,

            "name": application.name
            if application
            else None,
        },

        "activeVersion": {
            "id": str(version.id)
            if version
            else None,

            "version": version.version
            if version
            else None,
        },

        "runtime": (
            {
                "deploymentId":
                    str(deployment.id),

                "containerId":
                    deployment.container_id,

                "containerName":
                    deployment.container_name,

                "hostPort":
                    deployment.host_port,

                "url":
                    deployment.runtime_url,

                "health":
                    deployment.health_status,

                "deployedAt":
                    deployment.deployed_at,
            }

            if deployment

            else None
        ),

        "createdAt":
            instance.created_at,
    }


@router.get(
    "/instances/{instance_id}/deployments",
)
def list_instance_deployments(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    # =====================================================
    # 1. LOAD INSTANCE
    # =====================================================

    instance = db.get(
        ApplicationInstance,
        instance_id,
    )

    if not instance:

        raise HTTPException(
            status_code=404,
            detail="Instance not found",
        )

    # =====================================================
    # 2. RBAC
    # =====================================================

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=instance.tenant_id,
            permission_code="application.instance.view",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 3. DEPLOYMENT HISTORY
    # =====================================================

    rows = db.execute(
        select(
            ApplicationDeployment,
            ApplicationVersion,
        )
        .join(
            ApplicationVersion,
            ApplicationVersion.id
            == ApplicationDeployment.application_version_id,
        )
        .where(
            ApplicationDeployment.instance_id
            == instance.id
        )
        .order_by(
            ApplicationDeployment.created_at.desc()
        )
    ).all()

    # =====================================================
    # 4. RESPONSE
    # =====================================================

    return [
        {
            "deploymentId":
                str(deployment.id),

            "version": {
                "id":
                    str(version.id),

                "version":
                    version.version,
            },

            "status":
                deployment.status,

            "health":
                deployment.health_status,

            "containerId":
                deployment.container_id,

            "containerName":
                deployment.container_name,

            "hostPort":
                deployment.host_port,

            "url":
                deployment.runtime_url,

            "error":
                deployment.error_message,

            "deployedAt":
                deployment.deployed_at,

            "stoppedAt":
                deployment.stopped_at,

            "createdAt":
                deployment.created_at,
        }

        for (
            deployment,
            version,
        ) in rows
    ]


# =========================================================
# ROLLBACK APPLICATION INSTANCE
# =========================================================

@router.post(
    "/instances/{instance_id}/rollback",
)
def rollback_application_instance(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    # =====================================================
    # 1. LOAD INSTANCE
    # =====================================================

    instance = db.scalar(
        select(ApplicationInstance)
        .where(ApplicationInstance.id == instance_id)
        .with_for_update()
    )

    if not instance:

        raise HTTPException(
            status_code=404,
            detail="Instance not found",
        )

    if instance.status != "running":

        raise HTTPException(
            status_code=409,
            detail=(
                "Only a running instance "
                "can be rolled back."
            ),
        )

    # =====================================================
    # 2. RBAC
    # =====================================================

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=instance.tenant_id,
            permission_code="application.deploy",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 3. CURRENT VERSION
    # =====================================================

    current_version = db.get(
        ApplicationVersion,
        instance.active_version_id,
    )

    if not current_version:

        raise HTTPException(
            status_code=409,
            detail="Current application version not found",
        )

    # =====================================================
    # 4. CURRENT RUNNING DEPLOYMENT
    # =====================================================

    current_deployment = db.scalar(
        select(ApplicationDeployment)
        .where(
            ApplicationDeployment.instance_id
            == instance.id,

            ApplicationDeployment.status
            == "running",
        )
        .order_by(
            ApplicationDeployment.created_at.desc()
        )
    )

    if not current_deployment:

        raise HTTPException(
            status_code=409,
            detail="Instance has no running deployment.",
        )

    if not current_deployment.container_name:

        raise HTTPException(
            status_code=409,
            detail="Current deployment has no container.",
        )

    # =====================================================
    # 5. PREVENT CONCURRENT DEPLOYMENT
    # =====================================================

    existing_candidate = db.scalar(
        select(ApplicationDeployment)
        .where(
            ApplicationDeployment.instance_id
            == instance.id,

            ApplicationDeployment.status
            == "deploying",
        )
    )

    if existing_candidate:

        raise HTTPException(
            status_code=409,
            detail=(
                "A deployment operation is already "
                "in progress for this instance."
            ),
        )

    # =====================================================
    # 6. FIND PREVIOUS SUCCESSFUL VERSION
    # =====================================================

    previous_deployment = db.scalar(
        select(ApplicationDeployment)
        .where(
            ApplicationDeployment.instance_id
            == instance.id,

            ApplicationDeployment.id
            != current_deployment.id,

            ApplicationDeployment.application_version_id
            != current_version.id,

            ApplicationDeployment.deployed_at.is_not(
                None
            ),

            ApplicationDeployment.error_message.is_(
                None
            ),
        )
        .order_by(
            ApplicationDeployment.deployed_at.desc()
        )
    )

    if not previous_deployment:

        raise HTTPException(
            status_code=409,
            detail=(
                "No previous successful deployment "
                "is available for rollback."
            ),
        )

    rollback_version = db.get(
        ApplicationVersion,
        previous_deployment.application_version_id,
    )

    if not rollback_version:

        raise HTTPException(
            status_code=409,
            detail="Rollback version no longer exists.",
        )

    if rollback_version.status != "image_ready":

        raise HTTPException(
            status_code=409,
            detail=(
                "Rollback version is not image_ready."
            ),
        )

    # =====================================================
    # 7. SUBSCRIPTION + ENTITLEMENT + VERSION POLICY
    # =====================================================

    try:

        subscription = require_active_subscription(
            db=db,
            tenant_id=instance.tenant_id,
            application_id=instance.application_id,
        )

        require_active_entitlement(
            db=db,
            tenant_id=instance.tenant_id,
            application_id=instance.application_id,
            entitlement_code="application.deploy",
        )

        require_subscription_version_allowed(
            db=db,
            subscription=subscription,
            target_version=rollback_version,
        )

    except (
        EntitlementError,
        VersionPolicyError,
    ) as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 8. READY BUILD FOR ROLLBACK VERSION
    # =====================================================

    rollback_build = db.scalar(
        select(ApplicationBuild)
        .where(
            ApplicationBuild.application_version_id
            == rollback_version.id,

            ApplicationBuild.status
            == "ready",
        )
        .order_by(
            ApplicationBuild.created_at.desc()
        )
    )

    if not rollback_build:

        raise HTTPException(
            status_code=409,
            detail=(
                "No ready build exists "
                "for rollback version."
            ),
        )

    if not rollback_build.image_ref:

        raise HTTPException(
            status_code=409,
            detail=(
                "Rollback build has no image reference."
            ),
        )

    # =====================================================
    # 9. CREATE FRESH ROLLBACK DEPLOYMENT
    # =====================================================

    short_id = uuid.uuid4().hex[:8]

    candidate_name = safe_name(
        f"augmis-rollback-"
        f"{instance.instance_key}-"
        f"{short_id}"
    )

    candidate = ApplicationDeployment(
        instance_id=instance.id,
        application_version_id=rollback_version.id,
        build_id=rollback_build.id,
        status="deploying",
        container_name=candidate_name,
        health_status="starting",
    )

    db.add(candidate)

    instance.status = "upgrading"

    db.commit()

    db.refresh(candidate)

    # =====================================================
    # 10. START ROLLBACK CANDIDATE
    #
    # Existing runtime remains alive until candidate
    # passes health check.
    # =====================================================

    try:

        result = start_scoped_container(
            db=db, instance=instance, deployment=candidate, build=rollback_build,
            manifest=rollback_version.manifest,
            container_name=candidate_name,
            labels={
                "augmis.managed": "true",

                "augmis.instance_id":
                    str(instance.id),

                "augmis.tenant_id":
                    str(instance.tenant_id),

                "augmis.application_id":
                    str(instance.application_id),

                "augmis.rollback_candidate":
                    "true",
            },
        )

    except DeploymentError as error:

        candidate.status = "failed"
        candidate.health_status = "unhealthy"
        candidate.error_message = str(error)
        archive_failed_start(candidate, error)

        instance.status = "running"

        db.commit()

        raise HTTPException(
            status_code=422,
            detail={
                "message":
                    "Rollback candidate failed health check",

                "candidateDeploymentId":
                    str(candidate.id),

                "error":
                    str(error),

                "rollback":
                    "Current deployment remains running",
            },
        ) from error

    # B1A: persist the healthy candidate reference before deleting the old
    # container. A crash now leaves enough DB metadata to reconcile safely.
    candidate.container_id = result["container_id"]
    candidate.container_name = result["container_name"]
    candidate.host_port = result["host_port"]
    candidate.runtime_url = result["runtime_url"]
    candidate.health_status = "healthy"
    db.commit()

    # Snapshot outgoing logs before their Docker container is deleted.
    archive_before_removal(current_deployment)
    db.commit()

    # =====================================================
    # 11. CANDIDATE HEALTHY — RETIRE CURRENT CONTAINER
    # =====================================================

    try:

        stop_container(
            current_deployment.container_name,
        )

    except DeploymentError as error:

        # Remove rollback candidate and preserve current
        # runtime if promotion cannot complete.
        archive_before_removal(candidate)
        db.commit()

        try:

            stop_container(
                result["container_name"],
            )

        except DeploymentError:
            pass

        candidate.status = "failed"
        candidate.health_status = "stopped"

        candidate.error_message = (
            "Rollback candidate was healthy but "
            "current deployment could not be stopped: "
            f"{error}"
        )

        instance.status = "running"

        db.commit()

        raise HTTPException(
            status_code=422,
            detail={
                "message":
                    "Rollback promotion failed",

                "error":
                    str(error),

                "rollback":
                    "Current deployment remains active",
            },
        ) from error

    now = datetime.now(
        timezone.utc
    )

    # =====================================================
    # 12. RETIRE PREVIOUS ACTIVE DEPLOYMENT
    # =====================================================

    current_deployment.status = "stopped"

    current_deployment.health_status = "stopped"

    current_deployment.stopped_at = now

    # =====================================================
    # 13. PROMOTE ROLLBACK DEPLOYMENT
    # =====================================================

    candidate.container_id = (
        result["container_id"]
    )

    candidate.container_name = (
        result["container_name"]
    )

    candidate.host_port = (
        result["host_port"]
    )

    candidate.runtime_url = (
        result["runtime_url"]
    )

    candidate.status = "running"

    candidate.health_status = "healthy"

    candidate.deployed_at = now

    instance.active_version_id = (
    rollback_version.id
)

    instance.status = "running"

    record_audit_event(
        db,
        action="application.rollback",
        resource_type="application_instance",
        resource_id=instance.id,
        actor_user_id=current_user.id,
        tenant_id=instance.tenant_id,
        outcome="success",
        message="Application instance rolled back successfully.",
        metadata={
        "deploymentId":
            str(candidate.id),

        "fromVersionId":
            str(current_version.id),

        "fromVersion":
            current_version.version,

        "toVersionId":
            str(rollback_version.id),

        "toVersion":
            rollback_version.version,

        "containerName":
            candidate.container_name,
        },
    )

    db.commit()

    db.refresh(instance)
    db.refresh(candidate)

    # =====================================================
    # 14. RESPONSE
    # =====================================================

    return {
        "status": "ROLLED_BACK",

        "instance": {
            "id": str(instance.id),
            "name": instance.name,
            "status": instance.status,
        },

        "fromVersion": {
            "id": str(current_version.id),
            "version": current_version.version,
        },

        "toVersion": {
            "id": str(rollback_version.id),
            "version": rollback_version.version,
        },

        "deployment": {
            "id": str(candidate.id),

            "containerId":
                candidate.container_id,

            "containerName":
                candidate.container_name,

            "hostPort":
                candidate.host_port,

            "url":
                candidate.runtime_url,

            "health":
                candidate.health_status,
        },
    }


# =========================================================
# STOP APPLICATION INSTANCE
# =========================================================

@router.post("/instances/{instance_id}/stop")
def stop_application_instance(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Operator Stop: block launches first, then stop ALL running copies for this app."""
    requested = db.get(ApplicationInstance, instance_id)
    if not requested:
        raise HTTPException(status_code=404, detail="Instance not found")
    try:
        require_tenant_permission(db=db, user=current_user,
                                  tenant_id=requested.tenant_id,
                                  permission_code="application.instance.stop")
    except AuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error

    # Consistent lock ordering with Open Application and Start.
    acquire_instance_limit_lock(db=db, tenant_id=requested.tenant_id,
                                application_id=requested.application_id)
    active = list(db.scalars(select(ApplicationInstance).where(
        ApplicationInstance.tenant_id == requested.tenant_id,
        ApplicationInstance.application_id == requested.application_id,
        ApplicationInstance.status.in_(("running", "provisioning", "upgrading", "stopping")),
    ).order_by(ApplicationInstance.id).with_for_update()))

    if any(i.status != "running" for i in active):
        raise HTTPException(status_code=409, detail=(
            "An application lifecycle operation is in progress. Wait for it to finish, then stop the application."
        ))

    targets = []
    for instance in active:
        deployment = db.scalar(select(ApplicationDeployment).where(
            ApplicationDeployment.instance_id == instance.id,
            ApplicationDeployment.status == "running",
        ).order_by(ApplicationDeployment.created_at.desc()))
        if not deployment or not deployment.container_name:
            raise HTTPException(status_code=409, detail=(
                "An active instance has no valid running deployment. Resolve its runtime state before stopping."
            ))
        targets.append((instance, deployment))

    # Fail closed. Existing launch tickets/sessions and new Open calls are now denied.
    # A failed Docker stop MUST NOT automatically re-enable launches.
    set_runtime_desired_state(db, requested.tenant_id, requested.application_id,
                              "stopped", current_user.id)
    for instance, _ in targets:
        instance.status = "stopping"
    db.commit()

    stopped = []
    failures = []
    for instance, deployment in targets:
        try:
            archive_before_removal(deployment)
            stop_container(deployment.container_name)
        except Exception as error:  # fail closed; report partial Docker/log archival errors
            instance.status = "running"  # Operator gate remains closed.
            failures.append(str(instance.id))
            db.commit()
            continue
        deployment.status = "stopped"
        deployment.health_status = "stopped"
        deployment.stopped_at = datetime.now(timezone.utc)
        instance.status = "stopped"
        stopped.append(str(instance.id))
        db.commit()

    record_audit_event(
        db, action="application.stop", resource_type="application_instance",
        resource_id=requested.id, actor_user_id=current_user.id,
        tenant_id=requested.tenant_id,
        outcome="failure" if failures else "success",
        message="Tenant application stopped by administrator." if not failures
                else "Operator launch gate closed; one or more containers could not be stopped.",
        metadata={"applicationId": str(requested.application_id),
                  "stoppedInstanceIds": stopped, "failedInstanceIds": failures},
    )
    db.commit()
    if failures:
        raise HTTPException(status_code=502, detail={
            "code": "APPLICATION_STOP_PARTIAL",
            "message": "Application access is stopped, but some containers could not be stopped. Retry Stop or inspect runtime logs.",
        })
    return {"status": "STOPPED", "applicationId": str(requested.application_id),
            "stoppedInstanceIds": stopped, "launchAllowed": False}


# =========================================================
# START (existing restart endpoint retained for API compatibility)
# =========================================================

@router.post(
    "/instances/{instance_id}/restart",
)
def restart_application_instance(
    instance_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    # =====================================================
    # 1. LOAD + LOCK INSTANCE
    # =====================================================

    instance = db.get(ApplicationInstance, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    acquire_instance_limit_lock(db=db, tenant_id=instance.tenant_id,
                                application_id=instance.application_id)
    instance = db.scalar(select(ApplicationInstance)
                         .where(ApplicationInstance.id == instance_id).with_for_update())

    if not instance:

        raise HTTPException(
            status_code=404,
            detail="Instance not found",
        )

    if instance.status != "stopped":

        raise HTTPException(
            status_code=409,
            detail=(
                "Only a stopped instance "
                "can be restarted."
            ),
        )

    # =====================================================
    # 2. RBAC
    # =====================================================

    try:

        require_tenant_permission(
            db=db,
            user=current_user,
            tenant_id=instance.tenant_id,
            permission_code="application.deploy",
        )

    except AuthorizationError as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 3. LOAD ACTIVE VERSION
    # =====================================================

    version = db.get(
        ApplicationVersion,
        instance.active_version_id,
    )

    if not version:

        raise HTTPException(
            status_code=409,
            detail=(
                "Instance active version "
                "does not exist."
            ),
        )

    if version.status != "image_ready":

        raise HTTPException(
            status_code=409,
            detail=(
                "Instance active version "
                "is not image_ready."
            ),
        )

    # =====================================================
    # 4. SUBSCRIPTION + ENTITLEMENT + VERSION POLICY
    # =====================================================

    try:

        subscription = require_active_subscription(
            db=db,
            tenant_id=instance.tenant_id,
            application_id=instance.application_id,
        )

        entitlement = require_active_entitlement(
            db=db,
            tenant_id=instance.tenant_id,
            application_id=instance.application_id,
            entitlement_code="application.deploy",
        )

        require_subscription_version_allowed(
            db=db,
            subscription=subscription,
            target_version=version,
        )

    except (
        EntitlementError,
        VersionPolicyError,
    ) as error:

        raise HTTPException(
            status_code=403,
            detail=str(error),
        ) from error

    # =====================================================
    # 5. INSTANCE CAPACITY
    #
    # Restart turns a stopped logical instance back into an
    # active instance, so maxInstances MUST be enforced.
    # =====================================================

    try:

        require_instance_capacity(
            db=db,
            tenant_id=instance.tenant_id,
            application_id=instance.application_id,
            entitlement=entitlement,
        )

    except InstanceLimitError as error:

        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error

    # =====================================================
    # 6. ENSURE NO ACTIVE DEPLOYMENT EXISTS
    # =====================================================

    active_deployment = db.scalar(
        select(ApplicationDeployment)
        .where(
            ApplicationDeployment.instance_id
            == instance.id,

            ApplicationDeployment.status.in_(
                (
                    "deploying",
                    "running",
                )
            ),
        )
    )

    if active_deployment:

        raise HTTPException(
            status_code=409,
            detail=(
                "Instance already has an active "
                "deployment."
            ),
        )

    # =====================================================
    # 7. FIND READY BUILD
    # =====================================================

    build = db.scalar(
        select(ApplicationBuild)
        .where(
            ApplicationBuild.application_version_id
            == version.id,

            ApplicationBuild.status
            == "ready",
        )
        .order_by(
            ApplicationBuild.created_at.desc()
        )
    )

    if not build:

        raise HTTPException(
            status_code=409,
            detail=(
                "No ready build exists for "
                "the active version."
            ),
        )

    if not build.image_ref:

        raise HTTPException(
            status_code=409,
            detail="Build has no image reference.",
        )

    # =====================================================
    # 8. CREATE RESTART DEPLOYMENT
    # =====================================================

    short_id = uuid.uuid4().hex[:8]

    container_name = safe_name(
        f"augmis-restart-"
        f"{instance.instance_key}-"
        f"{short_id}"
    )

    deployment = ApplicationDeployment(
        instance_id=instance.id,
        application_version_id=version.id,
        build_id=build.id,
        status="deploying",
        container_name=container_name,
        health_status="starting",
    )

    db.add(deployment)

    # Provisioning is an active instance status and therefore
    # reserves the maxInstances slot before the advisory lock
    # is released by commit.

    instance.status = "provisioning"

    db.commit()

    db.refresh(instance)
    db.refresh(deployment)

    # =====================================================
    # 9. START CONTAINER
    # =====================================================

    try:

        result = start_scoped_container(
            db=db, instance=instance, deployment=deployment, build=build,
            manifest=version.manifest,
            container_name=container_name,
            labels={
                "augmis.managed": "true",

                "augmis.instance_id":
                    str(instance.id),

                "augmis.tenant_id":
                    str(instance.tenant_id),

                "augmis.application_id":
                    str(instance.application_id),

                "augmis.restart":
                    "true",
            },
        )

    except DeploymentError as error:

        deployment.status = "failed"
        deployment.health_status = "unhealthy"
        deployment.error_message = str(error)
        archive_failed_start(deployment, error)

        # Restart failure leaves the logical instance stopped.
        instance.status = "stopped"

        db.commit()

        raise HTTPException(
            status_code=422,
            detail={
                "message":
                    "Instance restart failed",

                "deploymentId":
                    str(deployment.id),

                "error":
                    str(error),
            },
        ) from error

        # =====================================================
    # 10. PROMOTE RESTART DEPLOYMENT
    # =====================================================

    now = datetime.now(
        timezone.utc
    )

    deployment.container_id = (
        result["container_id"]
    )

    deployment.container_name = (
        result["container_name"]
    )

    deployment.host_port = (
        result["host_port"]
    )

    deployment.runtime_url = (
        result["runtime_url"]
    )

    deployment.status = "running"

    deployment.health_status = "healthy"

    deployment.deployed_at = now

    instance.status = "running"
    set_runtime_desired_state(db, instance.tenant_id, instance.application_id,
                              "running", current_user.id)

    record_audit_event(
        db,
        action="application.restart",
        resource_type="application_instance",
        resource_id=instance.id,
        actor_user_id=current_user.id,
        tenant_id=instance.tenant_id,
        outcome="success",
        message="Application instance restarted successfully.",
        metadata={
            "deploymentId":
                str(deployment.id),

            "versionId":
                str(version.id),

            "version":
                version.version,

            "containerName":
                deployment.container_name,

            "hostPort":
                deployment.host_port,
        },
    )

    db.commit()

    db.refresh(instance)
    db.refresh(deployment)

    # =====================================================
    # 11. RESPONSE
    # =====================================================

    return {
        "status": "RESTARTED",

        "instance": {
            "id": str(instance.id),
            "name": instance.name,
            "status": instance.status,
        },

        "activeVersion": {
            "id": str(version.id),
            "version": version.version,
        },

        "deployment": {
            "id": str(deployment.id),

            "containerId":
                deployment.container_id,

            "containerName":
                deployment.container_name,

            "hostPort":
                deployment.host_port,

            "url":
                deployment.runtime_url,

            "health":
                deployment.health_status,
        },
    }