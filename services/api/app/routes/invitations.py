# services/api/app/routes/invitations.py



import uuid



from fastapi import (

    APIRouter,

    Depends,

    HTTPException,

    Query,

)

from sqlalchemy.orm import Session



from services.api.app.core.auth import (

    get_current_user,

)

from services.api.app.core.config import (

    settings,

)

from services.api.app.db.session import (

    get_db,

)

from services.api.app.models.iam import (

    User,

)



from services.api.app.models.platform import (
    Tenant,
)

from services.api.app.services.email_service import (
    EmailDeliveryError,
    send_tenant_invitation_email,
)

from services.api.app.services.platform_settings_service import (
    get_effective_mail_configuration,
)


from services.api.app.services.invitation_service import (

    get_invitation_roles,

    mark_invitation_delivery,

)





from services.api.app.schemas.invitation import (

    TenantInvitationAcceptanceResponse,

    TenantInvitationAcceptExistingRequest,

    TenantInvitationAcceptNewRequest,

    TenantInvitationCreate,

    TenantInvitationCreateResponse,

    TenantInvitationResolveResponse,

    TenantInvitationResponse,

)

from services.api.app.services.audit_service import (

    record_audit_event,

)

from services.api.app.services.auth_service import (

    create_access_token,

)

from services.api.app.services.authorization_service import (

    AuthorizationError,

    require_tenant_permission,

)

from services.api.app.services.invitation_service import (

    InvitationConflict,

    InvitationError,

    InvitationExpired,

    InvitationForbidden,

    InvitationNotFound,

    VALID_INVITATION_STATUSES,

    acceptance_payload,

    accept_existing_invitation,

    accept_new_invitation,

    create_tenant_invitation,

    invitation_payload,

    list_tenant_invitations,

    reissue_tenant_invitation,

    resolve_invitation,

    revoke_tenant_invitation,

)





router = APIRouter(

    prefix="/api/v1",

    tags=[

        "Tenant Invitations"

    ],

)









def _require_invitation_admin(

    *,

    db: Session,

    current_user: User,

    tenant_id: uuid.UUID,

) -> None:

    try:

        require_tenant_permission(

            db=db,

            user=current_user,

            tenant_id=tenant_id,

            permission_code=(

                "tenant.users.manage"

            ),

        )

    except AuthorizationError as error:

        raise HTTPException(

            status_code=403,

            detail=str(error),

        ) from error





def _raise_invitation_error(

    error: Exception

) -> None:

    if isinstance(

        error,

        InvitationNotFound,

    ):

        raise HTTPException(

            status_code=404,

            detail=str(error),

        ) from error



    if isinstance(

        error,

        InvitationExpired,

    ):

        raise HTTPException(

            status_code=410,

            detail=str(error),

        ) from error



    if isinstance(

        error,

        InvitationForbidden,

    ):

        raise HTTPException(

            status_code=403,

            detail=str(error),

        ) from error



    if isinstance(

        error,

        InvitationConflict,

    ):

        raise HTTPException(

            status_code=409,

            detail=str(error),

        ) from error



    if isinstance(

        error,

        InvitationError,

    ):

        raise HTTPException(

            status_code=400,

            detail=str(error),

        ) from error



    raise error



def _deliver_invitation_email(
    *,
    db: Session,
    invitation,
    raw_token: str,
    actor_user_id: uuid.UUID,
    reissued: bool,
) -> None:

    (
        mail_configuration,
        _mail_source,
        _mail_provider,
    ) = get_effective_mail_configuration(
        db
    )

    if not mail_configuration.enabled:
        return

    tenant = db.get(
        Tenant,
        invitation.tenant_id,
    )

    if not tenant:
        return

    roles = get_invitation_roles(
        db,
        invitation.id,
    )

    acceptance_url = (
        settings
        .frontend_base_url
        .rstrip("/")
        + "/invite/accept?token="
        + raw_token
    )

    try:
        delivery_message_id = (
            send_tenant_invitation_email(
                recipient_email=(
                    invitation.email
                ),
                tenant_name=(
                    tenant.name
                ),
                tenant_slug=(
                    tenant.slug
                ),
                role_names=[
                    role.name
                    for role in roles
                ],
                acceptance_url=(
                    acceptance_url
                ),
                expires_at=(
                    invitation.expires_at
                ),
                reissued=reissued,
                mail_configuration=(
                    mail_configuration
                ),
            )
        )

        mark_invitation_delivery(
            db,
            invitation=invitation,
            delivered=True,
            message_id=(
                delivery_message_id
            ),
        )

        record_audit_event(
            db,
            action=(
                "tenant.invitation."
                "delivery.submitted"
            ),
            resource_type=(
                "tenant_invitation"
            ),
            resource_id=(
                invitation.id
            ),
            actor_user_id=(
                actor_user_id
            ),
            tenant_id=(
                invitation.tenant_id
            ),
            outcome="success",
            message=(
                "Tenant invitation "
                "email submitted to provider."
            ),
            metadata={
                "email":
                    invitation.email,
                "reissued":
                    reissued,
                "channel":
                    "email",
                "messageId":
                    delivery_message_id,
            },
        )

        db.commit()

    except EmailDeliveryError as error:

        mark_invitation_delivery(
            db,
            invitation=invitation,
            delivered=False,
            error_message=str(
                error
            ),
        )

        record_audit_event(
            db,
            action=(
                "tenant.invitation."
                "delivery.failed"
            ),
            resource_type=(
                "tenant_invitation"
            ),
            resource_id=(
                invitation.id
            ),
            actor_user_id=(
                actor_user_id
            ),
            tenant_id=(
                invitation.tenant_id
            ),
            outcome="failed",
            message=(
                "Tenant invitation "
                "email delivery failed."
            ),
            metadata={
                "email":
                    invitation.email,
                "reissued":
                    reissued,
                "channel":
                    "email",
            },
        )

        db.commit()


@router.post(

    "/tenants/{tenant_id}/invitations",

    response_model=(

        TenantInvitationCreateResponse

    ),

    status_code=201,

)

def create_invitation(

    tenant_id: uuid.UUID,

    payload:

        TenantInvitationCreate,

    db: Session = Depends(

        get_db

    ),

    current_user: User = Depends(

        get_current_user

    ),

):

    _require_invitation_admin(

        db=db,

        current_user=current_user,

        tenant_id=tenant_id,

    )



    try:

        result = create_tenant_invitation(

            db=db,

            tenant_id=tenant_id,

            invited_by_user_id=(

                current_user.id

            ),

            email=str(

                payload.email

            ),

            role_codes=(

                payload.role_codes

            ),

            expiry_hours=(

                settings

                .tenant_invitation_expiry_hours

            ),

        )



        base_payload = invitation_payload(

            db,

            result.invitation,

        )



        expose_token = (

            settings.app_env.lower()

            != "production"

        )



        invitation_token = (

            result.token

            if expose_token

            else None

        )



        acceptance_url = (

            settings

            .frontend_base_url

            .rstrip("/")

            + "/invite/accept?token="

            + result.token

            if expose_token

            else None

        )



        record_audit_event(

            db,

            action=(

                "tenant.invitation.created"

            ),

            resource_type=(

                "tenant_invitation"

            ),

            resource_id=(

                result.invitation.id

            ),

            actor_user_id=(

                current_user.id

            ),

            tenant_id=tenant_id,

            outcome="success",

            message=(

                "Tenant invitation created."

            ),

            metadata={

                "email":

                    result

                    .invitation

                    .email,

                "roleCodes":

                    payload

                    .role_codes,

                "expiresAt":

                    result

                    .invitation

                    .expires_at

                    .isoformat(),

            },

        )



        db.commit()



        _deliver_invitation_email(

            db=db,

            invitation=(

                result.invitation

            ),

            raw_token=(

                result.token

            ),

            actor_user_id=(

                current_user.id

            ),

            reissued=False,

        )



        base_payload = (

            invitation_payload(

                db,

                result.invitation,

            )

        )



        return {

            **base_payload,

            "invitationToken":

                invitation_token,

            "acceptanceUrl":

                acceptance_url,

        }



    except InvitationError as error:

        db.rollback()

        _raise_invitation_error(

            error

        )





@router.get(

    "/tenants/{tenant_id}/invitations",

    response_model=list[

        TenantInvitationResponse

    ],

)

def list_invitations(

    tenant_id: uuid.UUID,

    status: str | None = Query(

        default=None

    ),

    db: Session = Depends(

        get_db

    ),

    current_user: User = Depends(

        get_current_user

    ),

):

    _require_invitation_admin(

        db=db,

        current_user=current_user,

        tenant_id=tenant_id,

    )



    if (

        status is not None

        and status not in

        VALID_INVITATION_STATUSES

    ):

        raise HTTPException(

            status_code=400,

            detail=(

                "Invalid invitation status."

            ),

        )



    try:

        invitations = (

            list_tenant_invitations(

                db=db,

                tenant_id=tenant_id,

            )

        )



        rows = [

            invitation_payload(

                db,

                invitation

            )

            for invitation

            in invitations

        ]



        if status is not None:

            rows = [

                row

                for row in rows

                if row["status"]

                == status

            ]



        return rows



    except InvitationError as error:

        _raise_invitation_error(

            error

        )





@router.post(

    "/tenants/{tenant_id}/invitations/{invitation_id}/revoke",

    response_model=(

        TenantInvitationResponse

    ),

)

def revoke_invitation(

    tenant_id: uuid.UUID,

    invitation_id:

        uuid.UUID,

    db: Session = Depends(

        get_db

    ),

    current_user: User = Depends(

        get_current_user

    ),

):

    _require_invitation_admin(

        db=db,

        current_user=current_user,

        tenant_id=tenant_id,

    )



    try:

        invitation = (

            revoke_tenant_invitation(

                db=db,

                tenant_id=tenant_id,

                invitation_id=(

                    invitation_id

                ),

                actor_user_id=(

                    current_user.id

                ),

            )

        )



        record_audit_event(

            db,

            action=(

                "tenant.invitation.revoked"

            ),

            resource_type=(

                "tenant_invitation"

            ),

            resource_id=(

                invitation.id

            ),

            actor_user_id=(

                current_user.id

            ),

            tenant_id=tenant_id,

            outcome="success",

            message=(

                "Tenant invitation revoked."

            ),

            metadata={

                "email":

                    invitation.email,

            },

        )



        response = (

            invitation_payload(

                db,

                invitation

            )

        )



        db.commit()



        return response



    except InvitationError as error:

        db.rollback()

        _raise_invitation_error(

            error

        )







@router.post(

    "/tenants/{tenant_id}/invitations/{invitation_id}/reissue",

    response_model=(

        TenantInvitationCreateResponse

    ),

)

def reissue_invitation(

    tenant_id: uuid.UUID,

    invitation_id: uuid.UUID,

    db: Session = Depends(

        get_db

    ),

    current_user: User = Depends(

        get_current_user

    ),

):

    _require_invitation_admin(

        db=db,

        current_user=current_user,

        tenant_id=tenant_id,

    )



    try:

        result = (

            reissue_tenant_invitation(

                db=db,

                tenant_id=tenant_id,

                invitation_id=(

                    invitation_id

                ),

                actor_user_id=(

                    current_user.id

                ),

                expiry_hours=(

                    settings

                    .tenant_invitation_expiry_hours

                ),

            )

        )



        base_payload = (

            invitation_payload(

                db,

                result.invitation,

            )

        )



        expose_token = (

            settings.app_env.lower()

            != "production"

        )



        invitation_token = (

            result.token

            if expose_token

            else None

        )



        acceptance_url = (

            settings

            .frontend_base_url

            .rstrip("/")

            + "/invite/accept?token="

            + result.token

            if expose_token

            else None

        )



        record_audit_event(

            db,

            action=(

                "tenant.invitation.reissued"

            ),

            resource_type=(

                "tenant_invitation"

            ),

            resource_id=(

                result.invitation.id

            ),

            actor_user_id=(

                current_user.id

            ),

            tenant_id=tenant_id,

            outcome="success",

            message=(

                "Tenant invitation reissued."

            ),

            metadata={

                "email":

                    result

                    .invitation

                    .email,

                "expiresAt":

                    result

                    .invitation

                    .expires_at

                    .isoformat(),

            },

        )



        db.commit()



        _deliver_invitation_email(

            db=db,

            invitation=(

                result.invitation

            ),

            raw_token=(

                result.token

            ),

            actor_user_id=(

                current_user.id

            ),

            reissued=True,

        )



        base_payload = (

            invitation_payload(

                db,

                result.invitation,

            )

        )



        return {

            **base_payload,

            "invitationToken":

                invitation_token,

            "acceptanceUrl":

                acceptance_url,

        }



    except InvitationError as error:

        db.rollback()



        _raise_invitation_error(

            error

        )



@router.get(

    "/invitations/resolve",

    response_model=(

        TenantInvitationResolveResponse

    ),

)

def resolve_public_invitation(

    token: str = Query(

        min_length=20,

        max_length=500,

    ),

    db: Session = Depends(

        get_db

    ),

):

    try:

        return resolve_invitation(

            db=db,

            token=token,

        )

    except InvitationError as error:

        _raise_invitation_error(

            error

        )





@router.post(

    "/invitations/accept-existing",

    response_model=(

        TenantInvitationAcceptanceResponse

    ),

)

def accept_existing_user_invitation(

    payload:

        TenantInvitationAcceptExistingRequest,

    db: Session = Depends(

        get_db

    ),

    current_user: User = Depends(

        get_current_user

    ),

):

    try:

        result = (

            accept_existing_invitation(

                db=db,

                token=(

                    payload.token

                ),

                current_user=(

                    current_user

                ),

            )

        )



        role_codes = [

            role.code

            for role in result.roles

        ]



        record_audit_event(

            db,

            action=(

                "tenant.invitation.accepted"

            ),

            resource_type=(

                "tenant_invitation"

            ),

            resource_id=(

                result.invitation.id

            ),

            actor_user_id=(

                result.user.id

            ),

            tenant_id=(

                result.tenant.id

            ),

            outcome="success",

            message=(

                "Tenant invitation accepted by existing user."

            ),

            metadata={

                "email":

                    result.user.email,

                "membershipId":

                    str(

                        result

                        .membership

                        .id

                    ),

                "roleCodes":

                    role_codes,

                "onboardingMode":

                    "existing_user",

            },

        )



        response = acceptance_payload(

            result

        )



        db.commit()



        return response



    except InvitationError as error:

        db.rollback()

        _raise_invitation_error(

            error

        )





@router.post(

    "/invitations/accept-new",

    response_model=(

        TenantInvitationAcceptanceResponse

    ),

)





def accept_new_user_invitation(

    payload:

        TenantInvitationAcceptNewRequest,

    db: Session = Depends(

        get_db

    ),

):

    try:

        result = (

            accept_new_invitation(

                db=db,

                token=(

                    payload.token

                ),

                first_name=(

                    payload.first_name

                ),

                last_name=(

                    payload.last_name

                ),

                password=(

                    payload.password

                ),

            )

        )



        access_token = (

            create_access_token(

                str(

                    result.user.id

                )

            )

        )



        role_codes = [

            role.code

            for role in result.roles

        ]



        record_audit_event(

            db,

            action=(

                "tenant.invitation.accepted"

            ),

            resource_type=(

                "tenant_invitation"

            ),

            resource_id=(

                result.invitation.id

            ),

            actor_user_id=(

                result.user.id

            ),

            tenant_id=(

                result.tenant.id

            ),

            outcome="success",

            message=(

                "Tenant invitation accepted and AUGMIS user created."

            ),

            metadata={

                "email":

                    result.user.email,

                "membershipId":

                    str(

                        result

                        .membership

                        .id

                    ),

                "roleCodes":

                    role_codes,

                "onboardingMode":

                    "new_user",

            },

        )



        response = acceptance_payload(

            result,

            access_token=(

                access_token

            ),

        )



        db.commit()







        return response



    except InvitationError as error:

        db.rollback()

        _raise_invitation_error(

            error

        )
