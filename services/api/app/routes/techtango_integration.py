"""B4 tenant identity mapping. Pending bindings are never an authorization grant."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from services.api.app.core.auth import get_current_user
from services.api.app.db.session import get_db
from services.api.app.models.iam import User
from services.api.app.models.platform import Tenant
from services.api.app.models.techtango_integration import (TechtangoTenantLink, TechtangoBridgeNonce, TechtangoAppSnapshot)
from services.api.app.services.techtango_bridge_service import (
    VERIFY, STAGE, BridgeProofError, decode_bridge_proof, check_link_claims, validate_stage_snapshot,
)
from services.api.app.services.authorization_service import AuthorizationError, require_platform_permission
from services.api.app.services.audit_service import record_audit_event

router = APIRouter(prefix="/api/v1/integrations/techtango", tags=["Integration - Techtango"])

class TenantLinkRequest(BaseModel):
    augmis_tenant_id: uuid.UUID
    techtango_tenant_id: int = Field(ge=1)


def _require_operator(db, user, permission):
    try:
        require_platform_permission(db=db, user=user, permission_code=permission)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/tenant-links")
def list_links(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_operator(db, user, "platform.tenants.manage")
    links = db.scalars(select(TechtangoTenantLink).order_by(TechtangoTenantLink.created_at.desc())).all()
    return [{"id": str(row.id), "augmisTenantId": str(row.augmis_tenant_id),
             "techtangoTenantId": row.external_tenant_id, "status": row.status} for row in links]


@router.post("/tenant-links", status_code=201)
def create_link(payload: TenantLinkRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_operator(db, user, "platform.tenants.manage")
    tenant = db.get(Tenant, payload.augmis_tenant_id)
    if tenant is None or tenant.status != "active":
        raise HTTPException(status_code=404, detail="Active AUGMIS tenant not found")
    # All mappings are PENDING. Only a future verified service-to-service
    # proof flow can activate an identity link; this endpoint cannot do so.
    link = TechtangoTenantLink(augmis_tenant_id=tenant.id,
                               external_tenant_id=payload.techtango_tenant_id,
                               status="pending", created_by_user_id=user.id)
    try:
        db.add(link)
        db.flush()
        record_audit_event(db, action="integration.techtango.tenant_link.proposed",
                           resource_type="techtango_tenant_link", resource_id=link.id,
                           actor_user_id=user.id, tenant_id=tenant.id, outcome="success",
                           message="Techtango tenant mapping proposed; pending independent verification.",
                           metadata={"externalTenantId": payload.techtango_tenant_id})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="One-to-one tenant mapping already exists") from exc
    return {"id": str(link.id), "status": "pending",
            "augmisTenantId": str(link.augmis_tenant_id),
            "techtangoTenantId": link.external_tenant_id}


# --- B4 Pass 2: independently verified attestation and immutable staging ---
class BridgeAttestationRequest(BaseModel):
    proof: str = Field(min_length=50, max_length=48000)


def _locked_link(db: Session, link_id: uuid.UUID) -> TechtangoTenantLink:
    link = db.scalar(
        select(TechtangoTenantLink)
        .where(TechtangoTenantLink.id == link_id)
        .with_for_update()
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Tenant link not found")
    return link


@router.post("/tenant-links/{link_id}/verify")
def verify_tenant_link(
    link_id: uuid.UUID, payload: BridgeAttestationRequest,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    _require_operator(db, user, "platform.tenants.manage")
    try:
        proof = decode_bridge_proof(payload.proof, purpose=VERIFY)
        link = _locked_link(db, link_id)
        check_link_claims(proof, link)
        if link.status != "pending":
            raise HTTPException(status_code=409, detail="Tenant link is not pending")
        active_tenant = db.get(Tenant, link.augmis_tenant_id)
        if active_tenant is None or active_tenant.status != "active":
            raise HTTPException(status_code=409, detail="Target tenant is not active")
        db.add(TechtangoBridgeNonce(jti=proof["jti"], link_id=link.id, purpose=VERIFY))
        db.flush()  # Unique JTI guarantees durable one-time use.
        link.status = "verified"
        link.verified_at = datetime.now(timezone.utc)
        record_audit_event(
            db, action="integration.techtango.tenant_link.verified",
            resource_type="techtango_tenant_link", resource_id=link.id,
            actor_user_id=user.id, tenant_id=link.augmis_tenant_id,
            outcome="success", message="Independent source-tenant proof verified.",
            metadata={"externalTenantId": link.external_tenant_id,
                      "proofActorId": proof["actorId"], "proofJti": proof["jti"]},
        )
        db.commit()
    except BridgeProofError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Proof already used") from exc
    except Exception:
        db.rollback()
        raise
    return {"id": str(link.id), "status": "verified", "verifiedAt": link.verified_at.isoformat()}


@router.post("/tenant-links/{link_id}/snapshots", status_code=201)
def stage_app_snapshot(
    link_id: uuid.UUID, payload: BridgeAttestationRequest,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    _require_operator(db, user, "platform.tenants.manage")
    try:
        proof = decode_bridge_proof(payload.proof, purpose=STAGE)
        link = _locked_link(db, link_id)
        check_link_claims(proof, link)
        if link.status != "verified":
            raise HTTPException(status_code=409, detail="Verified tenant link required")
        tenant = db.get(Tenant, link.augmis_tenant_id)
        if tenant is None or tenant.status != "active":
            raise HTTPException(status_code=409, detail="Target tenant is not active")
        snapshot = validate_stage_snapshot(proof)
        item = TechtangoAppSnapshot(
            link_id=link.id, external_app_id=proof["sourceAppId"],
            app_slug=snapshot["appSlug"], sha256=snapshot["sha256"],
            snapshot_metadata=snapshot, staged_by_user_id=user.id,
        )
        db.add(TechtangoBridgeNonce(jti=proof["jti"], link_id=link.id, purpose=STAGE))
        db.add(item)
        db.flush()  # Unique (link, slug, digest) forbids overwriting a snapshot.
        record_audit_event(
            db, action="integration.techtango.app.snapshot.staged",
            resource_type="techtango_app_snapshot", resource_id=item.id,
            actor_user_id=user.id, tenant_id=link.augmis_tenant_id,
            outcome="success", message="Published app metadata staged; no executable export.",
            metadata={"appSlug": item.app_slug, "sha256": item.sha256,
                      "sourceAppId": item.external_app_id},
        )
        db.commit()
    except BridgeProofError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Proof replay or identical immutable snapshot exists") from exc
    except Exception:
        db.rollback()
        raise
    return {"id": str(item.id), "linkId": str(link.id), "appSlug": item.app_slug,
            "sha256": item.sha256, "status": "staged_metadata_only"}


@router.get("/tenant-links/{link_id}/snapshots")
def list_app_snapshots(
    link_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    _require_operator(db, user, "platform.tenants.manage")
    if db.get(TechtangoTenantLink, link_id) is None:
        raise HTTPException(status_code=404, detail="Tenant link not found")
    rows = db.scalars(select(TechtangoAppSnapshot)
                      .where(TechtangoAppSnapshot.link_id == link_id)
                      .order_by(TechtangoAppSnapshot.staged_at.desc())).all()
    return [{"id": str(x.id), "appSlug": x.app_slug, "sha256": x.sha256,
             "sourceAppId": x.external_app_id, "stagedAt": x.staged_at.isoformat(),
             "status": "staged_metadata_only"} for x in rows]
