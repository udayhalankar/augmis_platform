# tools/seed_rbac.py

from sqlalchemy import select

from services.api.app.core.rbac_catalog import (
    PERMISSION_DEFINITIONS,
    ROLE_BLUEPRINTS,
)

from services.api.app.db.session import (
    SessionLocal,
)

from services.api.app.models.iam import (
    Permission,
    Role,
    RolePermission,
)


# ============================================================
# AUGMIS RBAC SEED
# ============================================================
#
# This seed is deliberately idempotent.
#
# Running:
#
#     python -m tools.seed_rbac
#
# multiple times must not create duplicate:
#
# - permissions
# - roles
# - role-permission assignments
#
# Canonical definitions are held in:
#
#     services/api/app/core/rbac_catalog.py
#
# ============================================================


def main():

    db = SessionLocal()


    try:

        # ----------------------------------------------------
        # PERMISSION MAP
        # ----------------------------------------------------

        permission_map: dict[
            str,
            Permission
        ] = {}


        # ----------------------------------------------------
        # CREATE / UPDATE PERMISSIONS
        # ----------------------------------------------------

        for (
            permission_code,
            definition
        ) in (
            PERMISSION_DEFINITIONS.items()
        ):

            permission = db.scalar(
                select(
                    Permission
                )
                .where(
                    Permission.code
                    == permission_code
                )
            )


            if not permission:

                permission = (
                    Permission(
                        code=(
                            permission_code
                        ),

                        name=(
                            definition[
                                "name"
                            ]
                        ),
                    )
                )


                db.add(
                    permission
                )


                db.flush()


            else:

                # --------------------------------------------
                # Keep display names synchronized with the
                # canonical catalogue without replacing IDs.
                # --------------------------------------------

                permission.name = (
                    definition[
                        "name"
                    ]
                )


            permission_map[
                permission_code
            ] = permission


        # ----------------------------------------------------
        # CREATE / UPDATE ROLES
        # ----------------------------------------------------

        for (
            scope_type,
            role_code
        ), definition in (
            ROLE_BLUEPRINTS.items()
        ):

            role = db.scalar(
                select(
                    Role
                )
                .where(
                    Role.scope_type
                    == scope_type,

                    Role.code
                    == role_code
                )
            )


            if not role:

                role = Role(
                    scope_type=(
                        scope_type
                    ),

                    code=(
                        role_code
                    ),

                    name=(
                        definition[
                            "name"
                        ]
                    ),
                )


                db.add(
                    role
                )


                db.flush()


            else:

                # --------------------------------------------
                # Keep role display name synchronized.
                #
                # Existing role IDs and assignments remain
                # untouched.
                # --------------------------------------------

                role.name = (
                    definition[
                        "name"
                    ]
                )


            # ------------------------------------------------
            # ENSURE ROLE-PERMISSION ASSIGNMENTS
            # ------------------------------------------------

            permission_codes = (
                definition[
                    "permissions"
                ]
            )


            for permission_code in (
                permission_codes
            ):

                permission = (
                    permission_map[
                        permission_code
                    ]
                )


                existing_assignment = (
                    db.scalar(
                        select(
                            RolePermission
                        )
                        .where(
                            RolePermission.role_id
                            == role.id,

                            RolePermission.permission_id
                            == permission.id
                        )
                    )
                )


                if existing_assignment:

                    continue


                db.add(
                    RolePermission(
                        role_id=(
                            role.id
                        ),

                        permission_id=(
                            permission.id
                        ),
                    )
                )


        # ----------------------------------------------------
        # COMMIT COMPLETE RBAC SEED
        # ----------------------------------------------------

        db.commit()


        print(
            "RBAC SEED COMPLETE"
        )


    except Exception:

        db.rollback()

        raise


    finally:

        db.close()


if __name__ == "__main__":

    main()