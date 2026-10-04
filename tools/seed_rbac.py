# tools/seed_rbac.py
from sqlalchemy import select

from services.api.app.db.session import SessionLocal

from services.api.app.models.iam import (
    Permission,
    Role,
    RolePermission
)


PERMISSIONS = {

    "platform.settings.manage":
        "Manage platform settings",

    "tenant.manage":
        "Manage tenant",

    "tenant.users.manage":
        "Manage tenant users",

    "application.deploy":
        "Deploy applications",

    "application.instance.view":
        "View application instances",

    "application.instance.stop":
        "Stop application instances",

    "audit.view":
    "View tenant audit events",

    "publisher.manage":
        "Manage publisher",

    "application.upload":
        "Upload application packages",

    "application.manage":
        "Manage publisher applications",

    "offer.manage":
        "Manage application offers",

    "subscription.view":
        "View subscriptions",

    "subscription.manage":
        "Manage subscriptions"
}


ROLES = {

    ("platform", "platform_owner"): {
        "name":
            "Platform Owner",

        "permissions": [
            "platform.settings.manage",
        ]
    },

    ("tenant", "tenant_owner"): {
        "name":
            "Tenant Owner",

        "permissions": [
            "tenant.manage",
            "tenant.users.manage",
            "application.deploy",
            "application.instance.view",
            "application.instance.stop",
            "subscription.view",
            "subscription.manage",
            "audit.view"
        ]
    },

    ("tenant", "tenant_user"): {
        "name":
            "Tenant User",

        "permissions": [
            "application.instance.view",
            "subscription.view"
        ]
    },

    ("publisher", "publisher_owner"): {
        "name":
            "Publisher Owner",

        "permissions": [
            "publisher.manage",
            "application.upload",
            "application.manage",
            "offer.manage"
        ]
    },

    ("publisher", "publisher_developer"): {
        "name":
            "Publisher Developer",

        "permissions": [
            "application.upload",
            "application.manage"
        ]
    }
}


def main():

    db = SessionLocal()

    try:

        permission_map = {}

        for code, name in PERMISSIONS.items():

            permission = db.scalar(
                select(Permission)
                .where(
                    Permission.code == code
                )
            )

            if not permission:

                permission = Permission(
                    code=code,
                    name=name
                )

                db.add(permission)

                db.flush()

            permission_map[code] = permission

        for (
            scope_type,
            role_code
        ), data in ROLES.items():

            role = db.scalar(
                select(Role)
                .where(
                    Role.scope_type
                    == scope_type,

                    Role.code
                    == role_code
                )
            )

            if not role:

                role = Role(
                    scope_type=scope_type,
                    code=role_code,
                    name=data["name"]
                )

                db.add(role)

                db.flush()

            for permission_code in data[
                "permissions"
            ]:

                permission = (
                    permission_map[
                        permission_code
                    ]
                )

                existing = db.scalar(
                    select(RolePermission)
                    .where(
                        RolePermission.role_id
                        == role.id,

                        RolePermission.permission_id
                        == permission.id
                    )
                )

                if not existing:

                    db.add(
                        RolePermission(
                            role_id=role.id,
                            permission_id=permission.id
                        )
                    )

        db.commit()

        print(
            "RBAC SEED COMPLETE"
        )

    finally:

        db.close()


if __name__ == "__main__":
    main()