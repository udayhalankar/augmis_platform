"""Persistent tenant/application operator stop gate. Never infer access from UI state."""
from __future__ import annotations
import uuid
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from services.api.app.models.platform import TenantApplicationRuntimeControl

STOP_MESSAGE = "Application is currently stopped. Contact your administrator to start the application."

def get_runtime_desired_state(db: Session, tenant_id: uuid.UUID, application_id: uuid.UUID) -> str:
    control = db.get(TenantApplicationRuntimeControl, (tenant_id, application_id))
    return control.desired_state if control else "running"

def get_runtime_launch_epoch(db: Session, tenant_id: uuid.UUID, application_id: uuid.UUID) -> int:
    control = db.get(TenantApplicationRuntimeControl, (tenant_id, application_id))
    return int(control.launch_epoch or 0) if control else 0

def require_runtime_launch_allowed(db: Session, tenant_id: uuid.UUID, application_id: uuid.UUID) -> None:
    if get_runtime_desired_state(db, tenant_id, application_id) != "running":
        raise HTTPException(status_code=409, detail={"code": "APPLICATION_STOPPED", "message": STOP_MESSAGE})

def set_runtime_desired_state(db: Session, tenant_id: uuid.UUID, application_id: uuid.UUID,
                              state: str, actor_user_id: uuid.UUID) -> None:
    if state not in ("running", "stopped"):
        raise ValueError("Invalid operator runtime state")
    # Callers serialize control-plane mutations using the existing tenant/application
    # advisory lock before calling this function.
    row = db.scalar(select(TenantApplicationRuntimeControl).where(
        TenantApplicationRuntimeControl.tenant_id == tenant_id,
        TenantApplicationRuntimeControl.application_id == application_id,
    ).with_for_update())
    if row is None:
        row = TenantApplicationRuntimeControl(tenant_id=tenant_id, application_id=application_id)
        db.add(row)
    if state == "stopped" and row.desired_state != "stopped":
        # Revokes even a previously issued gateway cookie after an admin re-start.
        row.launch_epoch = int(row.launch_epoch or 0) + 1
    row.desired_state = state
    row.updated_by_user_id = actor_user_id
    db.flush()
