import uuid

from packaging.version import (
    InvalidVersion,
    Version,
)

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.models.commerce import (
    ApplicationOffer,
    TenantSubscription,
)

from services.api.app.models.platform import (
    ApplicationVersion,
)


class VersionPolicyError(Exception):
    pass


def parse_version(
    value: str,
) -> Version:

    try:
        return Version(value)

    except InvalidVersion as error:
        raise VersionPolicyError(
            f"Invalid application version: {value}"
        ) from error


def get_latest_image_ready_version(
    db: Session,
    application_id: uuid.UUID,
) -> ApplicationVersion:

    versions = list(
        db.scalars(
            select(ApplicationVersion)
            .where(
                ApplicationVersion.application_id
                == application_id,

                ApplicationVersion.status
                == "image_ready",
            )
        )
    )

    if not versions:
        raise VersionPolicyError(
            "Application has no image-ready version."
        )

    return max(
        versions,
        key=lambda item: parse_version(
            item.version
        ),
    )


def validate_offer_version_policy(
    db: Session,
    offer_application_id: uuid.UUID,
    version_policy: str,
    pinned_version_id: uuid.UUID | None,
):

    if version_policy not in {
        "same_major",
        "pinned",
        "any",
    }:
        raise VersionPolicyError(
            "Unsupported version policy."
        )

    if version_policy == "pinned":

        if not pinned_version_id:
            raise VersionPolicyError(
                "Pinned policy requires pinned_version_id."
            )

        version = db.get(
            ApplicationVersion,
            pinned_version_id,
        )

        if not version:
            raise VersionPolicyError(
                "Pinned application version not found."
            )

        if version.application_id != offer_application_id:
            raise VersionPolicyError(
                "Pinned version belongs to another application."
            )

        if version.status != "image_ready":
            raise VersionPolicyError(
                "Pinned version must be image_ready."
            )

    elif pinned_version_id is not None:

        raise VersionPolicyError(
            "pinned_version_id is only valid "
            "with version_policy='pinned'."
        )


def resolve_subscription_baseline(
    db: Session,
    offer: ApplicationOffer,
) -> ApplicationVersion:

    if offer.version_policy == "pinned":

        if not offer.pinned_version_id:
            raise VersionPolicyError(
                "Pinned offer has no pinned version."
            )

        version = db.get(
            ApplicationVersion,
            offer.pinned_version_id,
        )

        if not version:
            raise VersionPolicyError(
                "Pinned version no longer exists."
            )

        return version

    return get_latest_image_ready_version(
        db=db,
        application_id=offer.application_id,
    )


def require_subscription_version_allowed(
    db: Session,
    subscription: TenantSubscription,
    target_version: ApplicationVersion,
):

    offer = db.get(
        ApplicationOffer,
        subscription.offer_id,
    )

    if not offer:
        raise VersionPolicyError(
            "Subscription offer no longer exists."
        )

    if target_version.application_id != offer.application_id:
        raise VersionPolicyError(
            "Target version belongs to another application."
        )

    if target_version.status != "image_ready":
        raise VersionPolicyError(
            "Target version is not image_ready."
        )

    policy = subscription.version_policy

    if policy == "any":
        return

    if policy == "pinned":

        if (
            not subscription.pinned_version_id
            or target_version.id
            != subscription.pinned_version_id
        ):
            raise VersionPolicyError(
                "Subscription is pinned to another version."
            )

        return

    if policy == "same_major":

        if not subscription.baseline_version_id:
            raise VersionPolicyError(
                "Subscription has no baseline version."
            )

        baseline = db.get(
            ApplicationVersion,
            subscription.baseline_version_id,
        )

        if not baseline:
            raise VersionPolicyError(
                "Subscription baseline version not found."
            )

        baseline_semver = parse_version(
            baseline.version
        )

        target_semver = parse_version(
            target_version.version
        )

        if (
            baseline_semver.major
            != target_semver.major
        ):
            raise VersionPolicyError(
                "Target version is outside the "
                "subscription's allowed major version."
            )

        return

    raise VersionPolicyError(
        f"Unsupported subscription version policy: {policy}"
    )