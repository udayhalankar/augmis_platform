# services/api/app/services/invitation_service.py

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from services.api.app.core.rbac_catalog import (
    role_is_protected,
)

from services.api.app.models.iam import (
    Role,
    TenantInvitation,
    TenantInvitationRole,
    TenantMembership,
    TenantMembershipRole,
    User,
)
from services.api.app.models.platform import Tenant
from services.api.app.services.auth_service import (
    hash_password,
    normalize_email,
)
from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_protected_tenant_role_manager,
)


VALID_INVITATION_STATUSES = {
    "pending",
    "accepted",
    "revoked",
    "expired",
}


class InvitationError(Exception):
    pass


class InvitationConflict(InvitationError):
    pass


class InvitationNotFound(InvitationError):
    pass


class InvitationExpired(InvitationError):
    pass


class InvitationForbidden(InvitationError):
    pass


@dataclass
class InvitationCreationResult:
    invitation: TenantInvitation
    token: str


@dataclass
class InvitationAcceptanceResult:
    invitation: TenantInvitation
    tenant: Tenant
    membership: TenantMembership
    user: User
    roles: list[Role]
    new_user_created: bool


def invitation_token_hash(
    token: str
) -> str:
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def invitation_effective_status(
    invitation: TenantInvitation
) -> str:
    if (
        invitation.status == "pending"
        and invitation.expires_at
        <= datetime.now(timezone.utc)
    ):
        return "expired"

    return invitation.status

def mark_invitation_delivery(
    db: Session,
    *,
    invitation: TenantInvitation,
    delivered: bool,
    error_message: str | None = None,
    message_id: str | None = None,
) -> None:
    now = datetime.now(
        timezone.utc
    )

    invitation.delivery_attempts = (
        int(
            invitation.delivery_attempts
            or 0
        )
        + 1
    )

    invitation.last_delivery_event_at = (
        now
    )

    if delivered:
        invitation.delivery_status = (
            "submitted"
        )

        invitation.last_sent_at = (
            now
        )

        invitation.last_delivery_error = (
            None
        )

        invitation.delivery_message_id = (
            str(message_id).strip()
            if message_id
            else None
        )

        invitation.provider_message_id = (
            None
        )

        invitation.delivered_at = (
            None
        )

    else:
        invitation.delivery_status = (
            "failed"
        )

        clean_error = str(
            error_message
            or "Email delivery failed."
        ).strip()

        invitation.last_delivery_error = (
            clean_error[:1000]
        )

    db.flush()


def _load_active_tenant(
    db: Session,
    tenant_id: uuid.UUID,
) -> Tenant:
    tenant = db.scalar(
        select(Tenant).where(
            Tenant.id == tenant_id
        )
    )

    if not tenant:
        raise InvitationNotFound(
            "Tenant not found."
        )

    if tenant.status != "active":
        raise InvitationConflict(
            "Invitations can only be created for an active tenant."
        )

    return tenant


def _normalise_role_codes(
    role_codes: list[str],
) -> list[str]:
    clean_codes: list[str] = []
    seen: set[str] = set()

    for value in role_codes:
        code = str(
            value or ""
        ).strip()

        if (
            not code
            or code in seen
        ):
            continue

        seen.add(code)
        clean_codes.append(code)

    if not clean_codes:
        raise InvitationError(
            "At least one tenant role is required."
        )

    return clean_codes


def _load_tenant_roles(
    db: Session,
    role_codes: list[str],
) -> list[Role]:
    clean_codes = _normalise_role_codes(
        role_codes
    )

    roles = list(
        db.scalars(
            select(Role).where(
                Role.scope_type == "tenant",
                Role.code.in_(clean_codes),
            )
        )
    )

    role_by_code = {
        role.code: role
        for role in roles
    }

    missing = [
        code
        for code in clean_codes
        if code not in role_by_code
    ]

    if missing:
        raise InvitationError(
            "Unknown tenant role code(s): "
            + ", ".join(missing)
        )

    return [
        role_by_code[code]
        for code in clean_codes
    ]



def _roles_include_protected_tenant_role(
    roles: list[Role],
) -> bool:

    return any(
        role_is_protected(
            "tenant",
            role.code,
        )
        for role in roles
    )


def _require_actor_can_manage_invited_roles(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    roles: list[Role],
) -> None:

    if not _roles_include_protected_tenant_role(
        roles
    ):
        return

    try:
        require_protected_tenant_role_manager(
            db=db,
            user_id=actor_user_id,
            tenant_id=tenant_id,
        )

    except AuthorizationError as error:
        raise InvitationForbidden(
            str(error)
        ) from error

def _expire_old_pending_invitation(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    email_normalized: str,
) -> None:
    now = datetime.now(timezone.utc)

    stale = list(
        db.scalars(
            select(TenantInvitation).where(
                TenantInvitation.tenant_id
                == tenant_id,
                TenantInvitation.email_normalized
                == email_normalized,
                TenantInvitation.status
                == "pending",
                TenantInvitation.expires_at
                <= now,
            )
        )
    )

    for invitation in stale:
        invitation.status = "expired"

    if stale:
        db.flush()


def create_tenant_invitation(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    invited_by_user_id: uuid.UUID,
    email: str,
    role_codes: list[str],
    expiry_hours: int,
) -> InvitationCreationResult:
    _load_active_tenant(
        db,
        tenant_id
    )

    normalized = normalize_email(
        email
    )

    roles = _load_tenant_roles(
        db,
        role_codes
    )

    _require_actor_can_manage_invited_roles(
        db=db,
        tenant_id=tenant_id,
        actor_user_id=invited_by_user_id,
        roles=roles,
    )

    _expire_old_pending_invitation(
        db,
        tenant_id=tenant_id,
        email_normalized=normalized,
    )

    pending = db.scalar(
        select(TenantInvitation).where(
            TenantInvitation.tenant_id
            == tenant_id,
            TenantInvitation.email_normalized
            == normalized,
            TenantInvitation.status
            == "pending",
        )
    )

    if pending:
        raise InvitationConflict(
            "A pending invitation already exists for this email address."
        )

    existing_user = db.scalar(
        select(User).where(
            User.email_normalized
            == normalized
        )
    )

    if existing_user:
        active_membership = db.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id
                == tenant_id,
                TenantMembership.user_id
                == existing_user.id,
                TenantMembership.status
                == "active",
            )
        )

        if active_membership:
            raise InvitationConflict(
                "This user is already an active member of the tenant."
            )

    raw_token = secrets.token_urlsafe(
        32
    )

    now = datetime.now(
        timezone.utc
    )

    invitation = TenantInvitation(
        tenant_id=tenant_id,
        email=str(
            email
        ).strip(),
        email_normalized=normalized,
        token_hash=invitation_token_hash(
            raw_token
        ),
        status="pending",
        invited_by_user_id=(
            invited_by_user_id
        ),
        created_at=now,
        expires_at=(
            now
            + timedelta(
                hours=max(
                    1,
                    int(expiry_hours),
                )
            )
        ),
    )

    db.add(invitation)
    db.flush()

    for role in roles:
        db.add(
            TenantInvitationRole(
                invitation_id=(
                    invitation.id
                ),
                role_id=role.id,
            )
        )

    db.flush()

    return InvitationCreationResult(
        invitation=invitation,
        token=raw_token,
    )


def list_tenant_invitations(
    db: Session,
    *,
    tenant_id: uuid.UUID,
) -> list[TenantInvitation]:
    _load_active_tenant(
        db,
        tenant_id
    )

    return list(
        db.scalars(
            select(TenantInvitation)
            .where(
                TenantInvitation.tenant_id
                == tenant_id
            )
            .order_by(
                TenantInvitation.created_at.desc()
            )
        )
    )


def get_tenant_invitation(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    invitation_id: uuid.UUID,
) -> TenantInvitation:
    invitation = db.scalar(
        select(TenantInvitation).where(
            TenantInvitation.id
            == invitation_id,
            TenantInvitation.tenant_id
            == tenant_id,
        )
    )

    if not invitation:
        raise InvitationNotFound(
            "Tenant invitation not found."
        )

    return invitation


def reissue_tenant_invitation(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    invitation_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expiry_hours: int,
) -> InvitationCreationResult:
    """
    Reissue an existing pending or expired tenant invitation.

    The invitation row and invitation ID are preserved.

    A new raw token is generated and its hash replaces the
    previous token hash, immediately invalidating the old link.
    """

    _load_active_tenant(
        db,
        tenant_id,
    )

    invitation = db.scalar(
        select(TenantInvitation)
        .where(
            TenantInvitation.id
            == invitation_id,
            TenantInvitation.tenant_id
            == tenant_id,
        )
        .with_for_update()
    )

    if not invitation:
        raise InvitationNotFound(
            "Tenant invitation not found."
        )

    effective_status = (
        invitation_effective_status(
            invitation
        )
    )

    if invitation.status == "accepted":
        raise InvitationConflict(
            "An accepted invitation cannot be reissued."
        )

    if invitation.status == "revoked":
        raise InvitationConflict(
            "A revoked invitation cannot be reissued."
        )

    if effective_status not in {
        "pending",
        "expired",
    }:
        raise InvitationConflict(
            "This invitation cannot be reissued."
        )

    roles = get_invitation_roles(
        db,
        invitation.id,
    )

    _require_actor_can_manage_invited_roles(
        db=db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        roles=roles,
    )

    # Re-check whether the invited email has meanwhile
    # become an active tenant member through another path.
    existing_user = db.scalar(
        select(User).where(
            User.email_normalized
            == invitation.email_normalized
        )
    )

    if existing_user:
        active_membership = db.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id
                == tenant_id,
                TenantMembership.user_id
                == existing_user.id,
                TenantMembership.status
                == "active",
            )
        )

        if active_membership:
            raise InvitationConflict(
                "This user is already an active member of the tenant."
            )

    raw_token = secrets.token_urlsafe(
        32
    )

    now = datetime.now(
        timezone.utc
    )

    # Replace the token hash.
    #
    # Because only the hash is stored, replacing it
    # immediately makes the previous invitation URL invalid.
    invitation.token_hash = (
        invitation_token_hash(
            raw_token
        )
    )

    invitation.status = "pending"

    invitation.expires_at = (
        now
        + timedelta(
            hours=max(
                1,
                int(expiry_hours),
            )
        )
    )

    # Defensive cleanup. Accepted/revoked invitations

     # Reset delivery state because this reissue
    # creates a new invitation token/link.
    invitation.delivery_status = (
        "not_attempted"
    )

    invitation.last_sent_at = None

    invitation.last_delivery_error = (
        None
    )

    invitation.delivery_message_id = (
        None
    )

    invitation.provider_message_id = (
        None
    )

    invitation.delivered_at = None

    invitation.last_delivery_event_at = (
        None
    )

    # are rejected above, but these fields should be
    # empty for every reissued invitation.
    invitation.accepted_at = None
    invitation.accepted_by_user_id = None
    invitation.revoked_at = None

    db.flush()

    return InvitationCreationResult(
        invitation=invitation,
        token=raw_token,
    )


def revoke_tenant_invitation(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    invitation_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> TenantInvitation:
    invitation = get_tenant_invitation(
        db,
        tenant_id=tenant_id,
        invitation_id=invitation_id,
    )

    effective_status = (
        invitation_effective_status(
            invitation
        )
    )

    if effective_status == "expired":
        raise InvitationConflict(
            "This invitation has expired."
        )

    if invitation.status == "accepted":
        raise InvitationConflict(
            "An accepted invitation cannot be revoked."
        )

    if invitation.status == "revoked":
        raise InvitationConflict(
            "This invitation is already revoked."
        )

    roles = get_invitation_roles(
        db,
        invitation.id,
    )

    _require_actor_can_manage_invited_roles(
        db=db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        roles=roles,
    )

    invitation.status = "revoked"
    invitation.revoked_at = (
        datetime.now(
            timezone.utc
        )
    )

    db.flush()

    return invitation


def get_invitation_roles(
    db: Session,
    invitation_id: uuid.UUID,
) -> list[Role]:
    return list(
        db.scalars(
            select(Role)
            .join(
                TenantInvitationRole,
                TenantInvitationRole.role_id
                == Role.id,
            )
            .where(
                TenantInvitationRole.invitation_id
                == invitation_id
            )
            .order_by(
                Role.name
            )
        )
    )


def invitation_payload(
    db: Session,
    invitation: TenantInvitation,
) -> dict:
    roles = get_invitation_roles(
        db,
        invitation.id
    )

    existing_user_id = db.scalar(
        select(User.id).where(
            User.email_normalized
            == invitation.email_normalized
        )
    )

    return {
        "invitationId":
            invitation.id,
        "email":
            invitation.email,
        "status":
            invitation_effective_status(
                invitation
            ),
        "createdAt":
            invitation.created_at,
                "deliveryStatus":
            invitation.delivery_status,
        "deliveryAttempts":
            invitation.delivery_attempts,
                "lastSentAt":
            invitation.last_sent_at,
        "lastDeliveryError":
            invitation.last_delivery_error,
        "expiresAt":
            invitation.expires_at,
        "acceptedAt":
            invitation.accepted_at,
        "revokedAt":
            invitation.revoked_at,
        "invitedByUserId":
            invitation.invited_by_user_id,
        "acceptedByUserId":
            invitation.accepted_by_user_id,
        "existingUser":
            existing_user_id
            is not None,
        "roles": [
            {
                "id":
                    role.id,
                "code":
                    role.code,
                "name":
                    role.name,
            }
            for role in roles
        ],
    }


def _load_invitation_by_token(
    db: Session,
    *,
    token: str,
    for_update: bool,
) -> TenantInvitation:
    clean_token = str(
        token or ""
    ).strip()

    if not clean_token:
        raise InvitationNotFound(
            "Invitation is invalid or no longer available."
        )

    statement = select(
        TenantInvitation
    ).where(
        TenantInvitation.token_hash
        == invitation_token_hash(
            clean_token
        )
    )

    if for_update:
        statement = (
            statement.with_for_update()
        )

    invitation = db.scalar(
        statement
    )

    if not invitation:
        raise InvitationNotFound(
            "Invitation is invalid or no longer available."
        )

    return invitation


def _validate_invitation_for_acceptance(
    invitation: TenantInvitation,
) -> None:
    effective_status = (
        invitation_effective_status(
            invitation
        )
    )

    if effective_status == "expired":
        raise InvitationExpired(
            "This invitation has expired."
        )

    if invitation.status == "revoked":
        raise InvitationConflict(
            "This invitation has been revoked."
        )

    if invitation.status == "accepted":
        raise InvitationConflict(
            "This invitation has already been accepted."
        )

    if invitation.status != "pending":
        raise InvitationConflict(
            "This invitation is not available for acceptance."
        )


def resolve_invitation(
    db: Session,
    *,
    token: str,
) -> dict:
    invitation = _load_invitation_by_token(
        db,
        token=token,
        for_update=False,
    )

    tenant = db.scalar(
        select(Tenant).where(
            Tenant.id
            == invitation.tenant_id
        )
    )

    if not tenant:
        raise InvitationNotFound(
            "Invitation tenant no longer exists."
        )

    roles = get_invitation_roles(
        db,
        invitation.id
    )

    existing_user_id = db.scalar(
        select(User.id).where(
            User.email_normalized
            == invitation.email_normalized
        )
    )

    status = invitation_effective_status(
        invitation
    )

    return {
        "invitationId":
            invitation.id,
        "email":
            invitation.email,
        "status":
            status,
        "expiresAt":
            invitation.expires_at,
        "existingUser":
            existing_user_id
            is not None,
        "canAccept":
            status == "pending",
        "tenant": {
            "id":
                tenant.id,
            "name":
                tenant.name,
            "slug":
                tenant.slug,
        },
        "roles": [
            {
                "id":
                    role.id,
                "code":
                    role.code,
                "name":
                    role.name,
            }
            for role in roles
        ],
    }


def _activate_membership_with_invited_roles(
    db: Session,
    *,
    invitation: TenantInvitation,
    user: User,
) -> tuple[
    TenantMembership,
    list[Role],
]:
    roles = get_invitation_roles(
        db,
        invitation.id
    )

    if not roles:
        raise InvitationConflict(
            "This invitation has no tenant roles."
        )

    membership = db.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id
            == invitation.tenant_id,
            TenantMembership.user_id
            == user.id,
        )
    )

    if membership:
        membership.status = "active"
    else:
        membership = TenantMembership(
            tenant_id=(
                invitation.tenant_id
            ),
            user_id=user.id,
            status="active",
        )
        db.add(membership)
        db.flush()

    db.execute(
        delete(
            TenantMembershipRole
        ).where(
            TenantMembershipRole.membership_id
            == membership.id
        )
    )

    db.flush()

    for role in roles:
        db.add(
            TenantMembershipRole(
                membership_id=(
                    membership.id
                ),
                role_id=role.id,
            )
        )

    db.flush()

    return (
        membership,
        roles,
    )


def _consume_invitation(
    invitation: TenantInvitation,
    *,
    accepted_by_user_id: uuid.UUID,
) -> None:
    invitation.status = "accepted"
    invitation.accepted_at = (
        datetime.now(
            timezone.utc
        )
    )
    invitation.accepted_by_user_id = (
        accepted_by_user_id
    )

    # One-time token consumption:
    # rotate the stored hash after success.
    invitation.token_hash = (
        invitation_token_hash(
            secrets.token_urlsafe(
                48
            )
        )
    )


def accept_existing_invitation(
    db: Session,
    *,
    token: str,
    current_user: User,
) -> InvitationAcceptanceResult:
    invitation = _load_invitation_by_token(
        db,
        token=token,
        for_update=True,
    )

    _validate_invitation_for_acceptance(
        invitation
    )

    if current_user.status != "active":
        raise InvitationForbidden(
            "Your AUGMIS account is not active."
        )

    if (
        current_user.email_normalized
        != invitation.email_normalized
    ):
        raise InvitationForbidden(
            "This invitation belongs to a different email address."
        )

    tenant = db.scalar(
        select(Tenant).where(
            Tenant.id
            == invitation.tenant_id
        )
    )

    if (
        not tenant
        or tenant.status != "active"
    ):
        raise InvitationConflict(
            "The invitation tenant is not active."
        )

    membership, roles = (
        _activate_membership_with_invited_roles(
            db,
            invitation=invitation,
            user=current_user,
        )
    )

    _consume_invitation(
        invitation,
        accepted_by_user_id=(
            current_user.id
        ),
    )

    db.flush()

    return InvitationAcceptanceResult(
        invitation=invitation,
        tenant=tenant,
        membership=membership,
        user=current_user,
        roles=roles,
        new_user_created=False,
    )


def accept_new_invitation(
    db: Session,
    *,
    token: str,
    first_name: str,
    last_name: str,
    password: str,
) -> InvitationAcceptanceResult:
    invitation = _load_invitation_by_token(
        db,
        token=token,
        for_update=True,
    )

    _validate_invitation_for_acceptance(
        invitation
    )

    existing_user = db.scalar(
        select(User).where(
            User.email_normalized
            == invitation.email_normalized
        )
    )

    if existing_user:
        raise InvitationConflict(
            "An AUGMIS account already exists for this email address. "
            "Sign in and accept the invitation as an existing user."
        )

    tenant = db.scalar(
        select(Tenant).where(
            Tenant.id
            == invitation.tenant_id
        )
    )

    if (
        not tenant
        or tenant.status != "active"
    ):
        raise InvitationConflict(
            "The invitation tenant is not active."
        )

    clean_first_name = str(
        first_name or ""
    ).strip()

    clean_last_name = str(
        last_name or ""
    ).strip()

    if (
        not clean_first_name
        or not clean_last_name
    ):
        raise InvitationError(
            "First name and last name are required."
        )

    user = User(
        email=invitation.email,
        email_normalized=(
            invitation.email_normalized
        ),
        password_hash=hash_password(
            password
        ),
        first_name=clean_first_name,
        last_name=clean_last_name,
        status="active",
    )

    db.add(user)
    db.flush()

    membership, roles = (
        _activate_membership_with_invited_roles(
            db,
            invitation=invitation,
            user=user,
        )
    )

    _consume_invitation(
        invitation,
        accepted_by_user_id=(
            user.id
        ),
    )

    db.flush()

    return InvitationAcceptanceResult(
        invitation=invitation,
        tenant=tenant,
        membership=membership,
        user=user,
        roles=roles,
        new_user_created=True,
    )


def acceptance_payload(
    result: InvitationAcceptanceResult,
    *,
    access_token: str | None = None,
) -> dict:
    return {
        "status":
            "accepted",
        "invitationId":
            result.invitation.id,
        "membershipId":
            result.membership.id,
        "tenant": {
            "id":
                result.tenant.id,
            "name":
                result.tenant.name,
            "slug":
                result.tenant.slug,
        },
        "user": {
            "id":
                result.user.id,
            "email":
                result.user.email,
            "firstName":
                result.user.first_name,
            "lastName":
                result.user.last_name,
            "status":
                result.user.status,
        },
        "roles": [
            {
                "id":
                    role.id,
                "code":
                    role.code,
                "name":
                    role.name,
            }
            for role in result.roles
        ],
        "accessToken":
            access_token,
        "tokenType":
            (
                "bearer"
                if access_token
                else None
            ),
    }
