"""Guarded Stage 53D publisher ownership source edits.

Usage (from repository root):
  python -m tools.apply_step53d_org_publisher --check
  python -m tools.apply_step53d_org_publisher --apply

Only modifies three supplied current files. Makes no DB changes.
Refuses to overwrite local files that differ from the reviewed snapshots.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path.cwd()
FILES = {
    "services/api/app/models/platform.py": "20771248fffa1fecf27b96b677b2c9f7b6e14f18bba0a2425fed161d1a69120b",
    "services/api/app/schemas/publisher.py": "07dd7e33565270944de7e0bacaf01089c85e9d786af842f17d67920f67e6643a",
    "services/api/app/routes/publishers.py": "829a2f7571785836d3c2fcba98e5cf5b6dbcd858b4d1ad75c64f1a76d48666f5",
}


def norm(text: str) -> str:
    return text.replace("\r\n", "\n")


def digest(data: str) -> str:
    return hashlib.sha256(norm(data).encode("utf-8")).hexdigest()


def once(data: str, original: str, new: str, label: str) -> str:
    if data.count(original) != 1:
        raise ValueError(f"{label}: expected one existing anchor, got {data.count(original)}")
    return data.replace(original, new, 1)


def patch_model(data: str) -> str:
    start = data.index("class Publisher(Base):")
    end = data.index("class Application(Base):")
    publisher = data[start:end]
    if "tenant_id" in publisher:
        raise ValueError("Publisher model already has tenant_id; do not apply twice.")
    publisher = once(publisher,
        "    name: Mapped[str] = mapped_column(",
        "    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n"
        "        UUID(as_uuid=True),\n"
        "        ForeignKey(\"tenants.id\", ondelete=\"RESTRICT\"),\n"
        "        nullable=True,\n"
        "        index=True,\n"
        "    )\n\n"
        "    name: Mapped[str] = mapped_column(",
        "Publisher model")
    return data[:start] + publisher + data[end:]


def patch_schema(data: str) -> str:
    data = once(data, "from pydantic import BaseModel, ConfigDict", "from pydantic import BaseModel, ConfigDict, Field", "Schema import")
    data = once(data, "    slug: str\n\n\nclass PublisherResponse",
                "    slug: str\n\n    # Required for every newly-created publisher workspace.\n"
                "    tenantId: uuid.UUID\n\n"
                "    # Optional; must be an active Tenant Owner in that organization.\n"
                "    initialOwnerEmail: str | None = None\n\n\nclass PublisherResponse", "PublisherCreate")
    data = once(data, "    status: str\n\n    model_config",
                "    status: str\n\n    # Legacy publishers remain unassigned until reviewed.\n"
                "    tenantId: uuid.UUID | None = Field(default=None, validation_alias=\"tenant_id\")\n\n"
                "    model_config", "PublisherResponse")
    data += ("\n\nclass PublisherOrganizationAssign(BaseModel):\n"
             "    tenantId: uuid.UUID\n")
    return data


CREATE_ROUTE = '''@router.post(
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


'''

EXTRA_ROUTES = '''# ============================================================
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


'''


def patch_route(data: str) -> str:
    data = once(data, "    HTTPException\n)", "    HTTPException,\n    Query,\n)", "FastAPI import")
    data = once(data, "from sqlalchemy import select", "from sqlalchemy import select\nfrom sqlalchemy.exc import IntegrityError", "SQL import")
    data = once(data, "from services.api.app.models.platform import (\n    Publisher\n)", "from services.api.app.models.platform import (\n    Publisher,\n    Tenant,\n)", "Platform model import")
    data = once(data, "    PublisherCreate,\n    PublisherResponse\n)",
                "    PublisherCreate,\n    PublisherResponse,\n    PublisherOrganizationAssign,\n)", "Schema import")
    data = once(data, "    require_platform_permission,\n)",
                "    require_platform_permission,\n    require_tenant_permission,\n)", "Authorization import")
    target = "from services.api.app.services.audit_service import (\n    record_audit_event,\n)"
    data = once(data, target, target + "\n\nfrom services.api.app.services.publisher_ownership_service import (\n"
                "    PublisherOwnershipError,\n"
                "    get_active_organization,\n"
                "    resolve_initial_publisher_owner,\n"
                "    assign_publisher_organization,\n"
                ")", "Ownership service import")
    start = data.index("@router.post(\n    \"\",\n")
    end = data.index("@router.get(\n    \"\",\n", start)
    data = data[:start] + CREATE_ROUTE + data[end:]
    anchor = "# ============================================================\n# PUBLISHER USERS & ROLES ADMINISTRATION (STEP 53C)"
    data = once(data, anchor, EXTRA_ROUTES + anchor, "Insert organization routes")
    return data

PATCH = {
    "services/api/app/models/platform.py": patch_model,
    "services/api/app/schemas/publisher.py": patch_schema,
    "services/api/app/routes/publishers.py": patch_route,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    flags = parser.add_mutually_exclusive_group(required=True)
    flags.add_argument("--check", action="store_true")
    flags.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    updates = {}
    for rel, expected_sha in FILES.items():
        path = ROOT / rel
        if not path.is_file():
            raise SystemExit(f"[BLOCKED] Missing expected source: {rel}")
        original = path.read_text(encoding="utf-8-sig")
        if digest(original) != expected_sha:
            raise SystemExit(
                f"[BLOCKED] {rel} differs from supplied reviewed file. "
                "No files changed; provide current code before proceeding."
            )
        updated = PATCH[rel](norm(original))
        compile(updated, rel, "exec")
        updates[path] = updated
        print(f"[PASS] Compatible: {rel}")
    if args.apply:
        # All patches are validated before any writes.
        for path, updated in updates.items():
            backup = path.with_suffix(path.suffix + ".step53d.bak")
            backup.write_bytes(path.read_bytes())
            path.write_text(updated, encoding="utf-8", newline="\n")
            print(f"[APPLIED] {path.relative_to(ROOT)}; backup={backup.name}")
    else:
        print("[CHECK ONLY] No files changed.")


if __name__ == "__main__":
    main()
