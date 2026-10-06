# services/api/app/core/rbac_catalog.py

from __future__ import annotations


# ============================================================
# AUGMIS CANONICAL RBAC PERMISSION CATALOGUE
# ============================================================
#
# This file is the canonical source for:
#
# - permission codes
# - permission display names
# - permission scope
# - standard AUGMIS role blueprints
#
# IMPORTANT:
#
# Permission enforcement still occurs in
# authorization_service.py.
#
# This catalogue defines WHAT exists.
# authorization_service.py decides WHETHER a user has it.
#
# ============================================================


PERMISSION_DEFINITIONS = {

    # --------------------------------------------------------
    # PLATFORM SCOPE
    # --------------------------------------------------------

    "platform.settings.manage": {
        "name":
            "Manage platform settings",

        "scope_type":
            "platform",
    },


    "platform.rbac.manage": {
        "name":
            "Manage platform RBAC",

        "scope_type":
            "platform",
    },

    "platform.tenants.manage": {
        "name":
            "Manage platform tenants",

        "scope_type":
            "platform",
    },

    "platform.publishers.manage": {
        "name":
            "Manage platform publishers",

        "scope_type":
            "platform",
    },


    # --------------------------------------------------------
    # TENANT SCOPE

    "tenant.manage": {
        "name":
            "Manage tenant",

        "scope_type":
            "tenant",
    },

    "tenant.users.view": {
        "name":
            "View tenant users",

        "scope_type":
            "tenant",
    },

    "tenant.users.manage": {
        "name":
            "Manage tenant users",

        "scope_type":
            "tenant",
    },


    # --------------------------------------------------------
    # TENANT APPLICATION / RUNTIME
    # --------------------------------------------------------

    "application.deploy": {
        "name":
            "Deploy applications",

        "scope_type":
            "tenant",
    },

    "application.instance.view": {
        "name":
            "View application instances",

        "scope_type":
            "tenant",
    },

    "application.instance.stop": {
        "name":
            "Stop application instances",

        "scope_type":
            "tenant",
    },


    # --------------------------------------------------------
    # TENANT SUBSCRIPTIONS
    # --------------------------------------------------------

    "subscription.view": {
        "name":
            "View subscriptions",

        "scope_type":
            "tenant",
    },

    "subscription.manage": {
        "name":
            "Manage subscriptions",

        "scope_type":
            "tenant",
    },


    # --------------------------------------------------------
    # TENANT AUDIT
    # --------------------------------------------------------

    "audit.view": {
        "name":
            "View tenant audit events",

        "scope_type":
            "tenant",
    },


    # --------------------------------------------------------
    # PUBLISHER SCOPE
    # --------------------------------------------------------

    "publisher.manage": {
        "name":
            "Manage publisher",

        "scope_type":
            "publisher",
    },

    "application.upload": {
        "name":
            "Upload application packages",

        "scope_type":
            "publisher",
    },

    "application.manage": {
        "name":
            "Manage publisher applications",

        "scope_type":
            "publisher",
    },

    "offer.manage": {
        "name":
            "Manage application offers",

        "scope_type":
            "publisher",
    },
}


# ============================================================
# STANDARD AUGMIS ROLE BLUEPRINTS
# ============================================================
#
# protected=True means that role-permission mappings cannot be
# edited using the normal RBAC administration API.
#
# These roles provide recovery / ownership capability.
#
# Existing tenant_user is deliberately preserved for backward
# compatibility with current memberships and invitations.
#
# ============================================================


ROLE_BLUEPRINTS = {

    # --------------------------------------------------------
    # PLATFORM
    # --------------------------------------------------------

    (
        "platform",
        "platform_owner"
    ): {

        "name":
            "Platform Owner",

        "protected":
            True,

        "permissions": [
            "platform.settings.manage",
            "platform.rbac.manage",
            "platform.tenants.manage",
            "platform.publishers.manage",
        ],
    },


    # --------------------------------------------------------
    # TENANT OWNER
    # --------------------------------------------------------

    (
        "tenant",
        "tenant_owner"
    ): {

        "name":
            "Tenant Owner",

        "protected":
            True,

        "permissions": [
            "tenant.manage",
            "tenant.users.view",
            "tenant.users.manage",
            "application.deploy",
            "application.instance.view",
            "application.instance.stop",
            "subscription.view",
            "subscription.manage",
            "audit.view",
        ],
    },


    # --------------------------------------------------------
    # TENANT ADMIN
    # --------------------------------------------------------

    (
        "tenant",
        "tenant_admin"
    ): {

        "name":
            "Tenant Admin",

        "protected":
            False,

        "permissions": [
            "tenant.manage",
            "tenant.users.view",
            "tenant.users.manage",
            "application.instance.view",
            "subscription.view",
            "audit.view",
        ],
    },


    # --------------------------------------------------------
    # SUBSCRIPTION ADMIN
    # --------------------------------------------------------

    (
        "tenant",
        "subscription_admin"
    ): {

        "name":
            "Subscription Admin",

        "protected":
            False,

        "permissions": [
            "subscription.view",
            "subscription.manage",
            "application.instance.view",
        ],
    },


    # --------------------------------------------------------
    # OPERATIONS ADMIN
    # --------------------------------------------------------

    (
        "tenant",
        "operations_admin"
    ): {

        "name":
            "Operations Admin",

        "protected":
            False,

        "permissions": [
            "application.deploy",
            "application.instance.view",
            "application.instance.stop",
            "audit.view",
        ],
    },


    # --------------------------------------------------------
    # SUPPORT
    # --------------------------------------------------------

    (
        "tenant",
        "support"
    ): {

        "name":
            "Support",

        "protected":
            False,

        "permissions": [
            "tenant.users.view",
            "application.instance.view",
            "subscription.view",
            "audit.view",
        ],
    },


    # --------------------------------------------------------
    # AUDITOR
    # --------------------------------------------------------

    (
        "tenant",
        "auditor"
    ): {

        "name":
            "Auditor",

        "protected":
            False,

        "permissions": [
            "tenant.users.view",
            "application.instance.view",
            "subscription.view",
            "audit.view",
        ],
    },


    # --------------------------------------------------------
    # STANDARD USER
    # --------------------------------------------------------

    (
        "tenant",
        "standard_user"
    ): {

        "name":
            "Standard User",

        "protected":
            False,

        "permissions": [
            "application.instance.view",
            "subscription.view",
        ],
    },


    # --------------------------------------------------------
    # LEGACY TENANT USER
    # --------------------------------------------------------
    #
    # Retained because current AUGMIS memberships and
    # invitations already use this role.
    #
    # We can later decide whether to migrate these users to
    # standard_user.
    #
    # --------------------------------------------------------

    (
        "tenant",
        "tenant_user"
    ): {

        "name":
            "Tenant User",

        "protected":
            False,

        "permissions": [
            "application.instance.view",
            "subscription.view",
        ],
    },


    # --------------------------------------------------------
    # PUBLISHER OWNER
    # --------------------------------------------------------

    (
        "publisher",
        "publisher_owner"
    ): {

        "name":
            "Publisher Owner",

        "protected":
            True,

        "permissions": [
            "publisher.manage",
            "application.upload",
            "application.manage",
            "offer.manage",
        ],
    },


    # --------------------------------------------------------
    # PUBLISHER ADMIN
    # --------------------------------------------------------

    (
        "publisher",
        "publisher_admin"
    ): {

        "name":
            "Publisher Admin",

        "protected":
            False,

        "permissions": [
            "publisher.manage",
            "application.upload",
            "application.manage",
            "offer.manage",
        ],
    },


    # --------------------------------------------------------
    # PUBLISHER DEVELOPER
    # --------------------------------------------------------

    (
        "publisher",
        "publisher_developer"
    ): {

        "name":
            "Publisher Developer",

        "protected":
            False,

        "permissions": [
            "application.upload",
            "application.manage",
        ],
    },
}


VALID_SCOPE_TYPES = {
    "platform",
    "tenant",
    "publisher",
}


def permission_scope(
    permission_code: str,
) -> str | None:

    definition = (
        PERMISSION_DEFINITIONS.get(
            permission_code
        )
    )

    if not definition:

        return None

    return str(
        definition[
            "scope_type"
        ]
    )


def role_is_protected(
    scope_type: str,
    role_code: str,
) -> bool:

    definition = (
        ROLE_BLUEPRINTS.get(
            (
                scope_type,
                role_code,
            )
        )
    )

    if not definition:

        return False

    return bool(
        definition.get(
            "protected",
            False,
        )
    )