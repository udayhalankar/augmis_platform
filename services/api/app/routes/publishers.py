import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.api.app.core.auth import (
    get_current_user
)

from services.api.app.db.session import (
    get_db
)

from services.api.app.models.iam import (
    PublisherMembership,
    User
)

from services.api.app.models.platform import (
    Publisher,
    Tenant,
)

from services.api.app.schemas.publisher import (
    PublisherCreate,
    PublisherResponse,
    PublisherOrganizationAssign,
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_platform_permission,
    require_tenant_permission,
)

from services.api.app.services.membership_service import (
    MembershipSetupError,
    create_publisher_owner_membership
)

from services.api.app.services.audit_service import (
    record_audit_event,
)

from services.api.app.services.publisher_ownership_service import (
    PublisherOwnershipError,
    get_active_organization,
    resolve_initial_publisher_owner,
    assign_publisher_organization,
)
from services.api.app.services.publisher_workspace_service import (
    activate_organization_publisher,
)


from services.api.app.services.authorization_service import (
    get_publisher_membership, get_publisher_permissions, require_publisher_permission,
)
from services.api.app.schemas.publisher_user import (
    PublisherUserAddRequest, PublisherUserRoleUpdateRequest,
)
from services.api.app.services.publisher_user_service import (
    PublisherUserServiceError, list_publisher_roles, list_publisher_users,
    add_publisher_user, update_publisher_roles, change_publisher_status,
)

router = APIRouter(
    prefix="/api/v1/publishers",
    tags=["Publishers"]
)


@router.post(
    "",
    response_model=PublisherResponse,
    status_code=201,
)
def create_publisher(
    payload: PublisherCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Platform publisher management authority, never inferred from tenant membership.
    try:
        require_platform_permission(
            db=db, user=current_user, permission_code="platform.publishers.manage",
        )
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if db.scalar(select(Publisher.id).where(Publisher.slug == payload.slug)):
        raise HTTPException(status_code=409, detail="Publisher slug already exists")

    try:
        tenant = get_active_organization(db, payload.tenantId, lock=True)
        if db.scalar(select(Publisher.id).where(Publisher.tenant_id == tenant.id)):
            raise PublisherOwnershipError(
                "This organization already has a publisher workspace.", 409
            )
        initial_owner = resolve_initial_publisher_owner(
            db,
            tenant_id=tenant.id,
            actor=current_user,
            initial_owner_email=payload.initialOwnerEmail,
        )
        publisher = Publisher(
            tenant_id=tenant.id,
            name=payload.name,
            slug=payload.slug,
            status="active",
        )
        db.add(publisher)
        db.flush()
        create_publisher_owner_membership(
            db=db, publisher_id=publisher.id, user_id=initial_owner.id,
        )
        record_audit_event(
            db,
            action="platform.publisher.created",
            resource_type="publisher",
            resource_id=publisher.id,
            actor_user_id=current_user.id,
            tenant_id=tenant.id,
            publisher_id=publisher.id,
            outcome="success",
            message="Organization-owned publisher workspace created.",
            metadata={
                "name": publisher.name,
                "slug": publisher.slug,
                "status": publisher.status,
                "tenantId": str(tenant.id),
                "initialOwnerUserId": str(initial_owner.id),
            },
        )
        db.commit()
        db.refresh(publisher)
        return publisher
    except PublisherOwnershipError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except MembershipSetupError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409,
                            detail="Publisher could not be created due to a uniqueness conflict.") from exc


@router.get(
    "",
    response_model=list[PublisherResponse]
)
def list_publishers(
    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    )
):

    publishers = db.scalars(
        select(Publisher)
        .join(
            PublisherMembership,
            PublisherMembership.publisher_id
            == Publisher.id
        )
        .where(
            PublisherMembership.user_id
            == current_user.id,

            PublisherMembership.status
            == "active"
        )
        .order_by(
            Publisher.name
        )
    )

    return list(publishers)

# ============================================================
# ORGANIZATION PUBLISHER ACTIVATION (STEP 53E)
# ============================================================

@router.post("/organizations/{tenant_id}/activate", response_model=PublisherResponse)
def activate_publisher_for_organization(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        require_tenant_permission(
            db=db, user=current_user, tenant_id=tenant_id,
            permission_code="tenant.manage",
        )
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        publisher, _created = activate_organization_publisher(
            db, tenant_id=tenant_id, actor=current_user,
        )
        db.commit()
        db.refresh(publisher)
        return publisher
    except PublisherOwnershipError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except MembershipSetupError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Organization already has a publisher workspace.") from exc


# ============================================================
# EXPLICIT ORGANIZATION OWNERSHIP (STEP 53D)
# ============================================================

@router.get("/ownership")
def platform_publisher_ownership(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        require_platform_permission(
            db=db, user=current_user, permission_code="platform.publishers.manage",
        )
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    rows = db.execute(
        select(Publisher, Tenant.name)
        .outerjoin(Tenant, Tenant.id == Publisher.tenant_id)
        .order_by(Publisher.name, Publisher.id)
        .limit(limit).offset(offset)
    ).all()
    return [{
        "id": str(publisher.id),
        "name": publisher.name,
        "slug": publisher.slug,
        "status": publisher.status,
        "tenantId": str(publisher.tenant_id) if publisher.tenant_id else None,
        "tenantName": tenant_name,
    } for publisher, tenant_name in rows]


@router.get("/organizations/{tenant_id}", response_model=list[PublisherResponse])
def organization_publishers(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # This returns organization-owned publisher directory data only.
    # It DOES NOT grant publisher application/offer permissions.
    try:
        require_tenant_permission(
            db=db, user=current_user, tenant_id=tenant_id,
            permission_code="tenant.manage",
        )
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        get_active_organization(db, tenant_id)
    except PublisherOwnershipError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return list(db.scalars(
        select(Publisher)
        .where(Publisher.tenant_id == tenant_id)
        .order_by(Publisher.name)
    ))


@router.post("/{publisher_id}/organization", response_model=PublisherResponse)
def bind_existing_publisher_to_organization(
    publisher_id: uuid.UUID,
    payload: PublisherOrganizationAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        require_platform_permission(
            db=db, user=current_user, permission_code="platform.publishers.manage",
        )
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        publisher = assign_publisher_organization(
            db=db, publisher_id=publisher_id, tenant_id=payload.tenantId,
            actor_user_id=current_user.id,
        )
        db.commit()
        db.refresh(publisher)
        return publisher
    except PublisherOwnershipError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Organization already has a publisher workspace.") from exc


# ============================================================
# PUBLISHER USERS & ROLES ADMINISTRATION (STEP 53C)
# ============================================================

@router.get("/{publisher_id}/me/permissions")
def my_publisher_permissions(
    publisher_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if db.get(Publisher, publisher_id) is None:
        raise HTTPException(status_code=404, detail="Publisher not found.")
    membership = get_publisher_membership(
        db=db, user_id=current_user.id, publisher_id=publisher_id,
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="You do not belong to this publisher.")
    return {"permissions": sorted(get_publisher_permissions(db, membership.id))}


def _require_publisher_manager(publisher_id: uuid.UUID,
                               db: Session, user: User) -> None:
    if db.get(Publisher, publisher_id) is None:
        raise HTTPException(status_code=404, detail="Publisher not found.")
    try:
        require_publisher_permission(
            db=db, user=user, publisher_id=publisher_id,
            permission_code="publisher.manage",
        )
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/{publisher_id}/roles")
def publisher_roles(
    publisher_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_publisher_manager(publisher_id, db, current_user)
    return list_publisher_roles(db, publisher_id)


@router.get("/{publisher_id}/users")
def publisher_users(
    publisher_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_publisher_manager(publisher_id, db, current_user)
    return list_publisher_users(db, publisher_id)


@router.post("/{publisher_id}/users", status_code=201)
def add_user_to_publisher(
    publisher_id: uuid.UUID,
    payload: PublisherUserAddRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return add_publisher_user(
            db, publisher_id=publisher_id, actor_user_id=current_user.id,
            email=payload.email, role_codes=payload.roleCodes,
        )
    except PublisherUserServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.put("/{publisher_id}/memberships/{membership_id}/roles")
def update_publisher_user_roles(
    publisher_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: PublisherUserRoleUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return update_publisher_roles(
            db, publisher_id=publisher_id, membership_id=membership_id,
            actor_user_id=current_user.id, role_codes=payload.roleCodes,
        )
    except PublisherUserServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{publisher_id}/memberships/{membership_id}/suspend")
def suspend_publisher_user(
    publisher_id: uuid.UUID,
    membership_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return change_publisher_status(
            db, publisher_id=publisher_id, membership_id=membership_id,
            actor_user_id=current_user.id, status="suspended",
        )
    except PublisherUserServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{publisher_id}/memberships/{membership_id}/activate")
def activate_publisher_user(
    publisher_id: uuid.UUID,
    membership_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return change_publisher_status(
            db, publisher_id=publisher_id, membership_id=membership_id,
            actor_user_id=current_user.id, status="active",
        )
    except PublisherUserServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/{publisher_id}/memberships/{membership_id}/revoke")
def revoke_publisher_user(
    publisher_id: uuid.UUID,
    membership_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return change_publisher_status(
            db, publisher_id=publisher_id, membership_id=membership_id,
            actor_user_id=current_user.id, status="revoked",
        )
    except PublisherUserServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
