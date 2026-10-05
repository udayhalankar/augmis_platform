# tools/verify_phase4_rbac.py

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import (
    func,
    select,
)

from services.api.app.core.rbac_catalog import (
    PERMISSION_DEFINITIONS,
    ROLE_BLUEPRINTS,
    permission_scope,
)

from services.api.app.db.session import (
    SessionLocal,
)

from services.api.app.models.iam import (
    Permission,
    PlatformUserRole,
    PublisherMembershipRole,
    Role,
    RolePermission,
    TenantInvitationRole,
    TenantMembership,
    TenantMembershipRole,
    User,
)

from services.api.app.models.platform import (
    Tenant,
)


def main() -> None:

    db = SessionLocal()

    failures: list[str] = []
    passed: list[str] = []

    try:

        # ====================================================
        # 1. PERMISSION CATALOGUE
        # ====================================================

        permissions = list(
            db.scalars(
                select(
                    Permission
                )
            )
        )

        permission_by_code = {
            permission.code:
                permission
            for permission
            in permissions
        }


        missing_permissions = sorted(
            set(
                PERMISSION_DEFINITIONS
            )
            - set(
                permission_by_code
            )
        )

        if missing_permissions:

            failures.append(
                "Missing canonical permissions: "
                + ", ".join(
                    missing_permissions
                )
            )

        else:

            passed.append(
                "All canonical permissions exist."
            )


        unknown_permissions = sorted(
            set(
                permission_by_code
            )
            - set(
                PERMISSION_DEFINITIONS
            )
        )

        if unknown_permissions:

            failures.append(
                "Unknown permissions exist in DB: "
                + ", ".join(
                    unknown_permissions
                )
            )

        else:

            passed.append(
                "No unknown permissions exist."
            )


        for (
            permission_code,
            definition,
        ) in (
            PERMISSION_DEFINITIONS.items()
        ):

            permission = (
                permission_by_code.get(
                    permission_code
                )
            )

            if not permission:

                continue


            expected_name = str(
                definition[
                    "name"
                ]
            )

            if (
                permission.name
                != expected_name
            ):

                failures.append(
                    (
                        "Permission display name drift: "
                        f"{permission_code} "
                        f"DB='{permission.name}' "
                        f"expected='{expected_name}'"
                    )
                )


        # ====================================================
        # 2. ROLE CATALOGUE
        # ====================================================

        roles = list(
            db.scalars(
                select(
                    Role
                )
            )
        )

        role_by_key = {
            (
                role.scope_type,
                role.code,
            ):
                role
            for role
            in roles
        }


        canonical_role_keys = set(
            ROLE_BLUEPRINTS
        )

        db_role_keys = set(
            role_by_key
        )


        missing_roles = sorted(
            canonical_role_keys
            - db_role_keys
        )

        if missing_roles:

            failures.append(
                (
                    "Missing canonical roles: "
                    + ", ".join(
                        (
                            f"{scope}:{code}"
                            for (
                                scope,
                                code,
                            )
                            in missing_roles
                        )
                    )
                )
            )

        else:

            passed.append(
                "All canonical roles exist."
            )


        unknown_roles = sorted(
            db_role_keys
            - canonical_role_keys
        )

        if unknown_roles:

            failures.append(
                (
                    "Unknown roles exist in DB: "
                    + ", ".join(
                        (
                            f"{scope}:{code}"
                            for (
                                scope,
                                code,
                            )
                            in unknown_roles
                        )
                    )
                )
            )

        else:

            passed.append(
                "No unknown roles exist."
            )


        for (
            role_key,
            definition,
        ) in (
            ROLE_BLUEPRINTS.items()
        ):

            role = (
                role_by_key.get(
                    role_key
                )
            )

            if not role:

                continue


            expected_name = str(
                definition[
                    "name"
                ]
            )

            if (
                role.name
                != expected_name
            ):

                failures.append(
                    (
                        "Role display name drift: "
                        f"{role.scope_type}:"
                        f"{role.code} "
                        f"DB='{role.name}' "
                        f"expected='{expected_name}'"
                    )
                )


        # ====================================================
        # 3. ROLE → PERMISSION ASSIGNMENTS
        # ====================================================

        assignment_rows = (
            db.execute(
                select(
                    Role.id,
                    Role.scope_type,
                    Role.code,
                    Permission.code,
                )
                .join(
                    RolePermission,
                    RolePermission.role_id
                    == Role.id,
                )
                .join(
                    Permission,
                    Permission.id
                    == RolePermission.permission_id,
                )
            )
            .all()
        )


        role_permissions: dict[
            object,
            set[str],
        ] = defaultdict(set)


        for (
            role_id,
            role_scope,
            role_code,
            permission_code,
        ) in assignment_rows:

            role_permissions[
                role_id
            ].add(
                permission_code
            )


            expected_scope = (
                permission_scope(
                    permission_code
                )
            )

            if (
                expected_scope
                != role_scope
            ):

                failures.append(
                    (
                        "Cross-scope role permission: "
                        f"{role_scope}:"
                        f"{role_code} -> "
                        f"{permission_code} "
                        f"(permission scope "
                        f"{expected_scope})"
                    )
                )


        if not any(
            "Cross-scope role permission:"
            in item
            for item
            in failures
        ):

            passed.append(
                (
                    "All role-permission "
                    "assignments match scope."
                )
            )


        # ====================================================
        # 4. PROTECTED ROLE INTEGRITY
        # ====================================================

        for (
            role_key,
            definition,
        ) in (
            ROLE_BLUEPRINTS.items()
        ):

            if not bool(
                definition.get(
                    "protected",
                    False,
                )
            ):

                continue


            role = (
                role_by_key.get(
                    role_key
                )
            )

            if not role:

                continue


            expected_permissions = set(
                definition[
                    "permissions"
                ]
            )

            actual_permissions = (
                role_permissions.get(
                    role.id,
                    set(),
                )
            )


            if (
                actual_permissions
                != expected_permissions
            ):

                failures.append(
                    (
                        "Protected role permission drift: "
                        f"{role.scope_type}:"
                        f"{role.code} "
                        f"expected="
                        f"{sorted(expected_permissions)} "
                        f"actual="
                        f"{sorted(actual_permissions)}"
                    )
                )

            else:

                passed.append(
                    (
                        "Protected role intact: "
                        f"{role.scope_type}:"
                        f"{role.code}"
                    )
                )


        # ====================================================
        # 5. PLATFORM ROLE SCOPE SAFETY
        # ====================================================

        bad_platform_roles = (
            db.execute(
                select(
                    PlatformUserRole.user_id,
                    Role.code,
                    Role.scope_type,
                )
                .join(
                    Role,
                    Role.id
                    == PlatformUserRole.role_id,
                )
                .where(
                    Role.scope_type
                    != "platform"
                )
            )
            .all()
        )


        if bad_platform_roles:

            failures.append(
                (
                    "Platform users have "
                    "non-platform roles assigned."
                )
            )

        else:

            passed.append(
                (
                    "Platform user-role "
                    "scope integrity passed."
                )
            )


        # ====================================================
        # 6. TENANT ROLE SCOPE SAFETY
        # ====================================================

        bad_tenant_roles = (
            db.execute(
                select(
                    TenantMembershipRole
                    .membership_id,

                    Role.code,

                    Role.scope_type,
                )
                .join(
                    Role,
                    Role.id
                    == TenantMembershipRole
                    .role_id,
                )
                .where(
                    Role.scope_type
                    != "tenant"
                )
            )
            .all()
        )


        if bad_tenant_roles:

            failures.append(
                (
                    "Tenant memberships have "
                    "non-tenant roles assigned."
                )
            )

        else:

            passed.append(
                (
                    "Tenant membership-role "
                    "scope integrity passed."
                )
            )


        # ====================================================
        # 7. PUBLISHER ROLE SCOPE SAFETY
        # ====================================================

        bad_publisher_roles = (
            db.execute(
                select(
                    PublisherMembershipRole
                    .membership_id,

                    Role.code,

                    Role.scope_type,
                )
                .join(
                    Role,
                    Role.id
                    == PublisherMembershipRole
                    .role_id,
                )
                .where(
                    Role.scope_type
                    != "publisher"
                )
            )
            .all()
        )


        if bad_publisher_roles:

            failures.append(
                (
                    "Publisher memberships have "
                    "non-publisher roles assigned."
                )
            )

        else:

            passed.append(
                (
                    "Publisher membership-role "
                    "scope integrity passed."
                )
            )


        # ====================================================
        # 8. INVITATION ROLE SCOPE SAFETY
        # ====================================================

        bad_invitation_roles = (
            db.execute(
                select(
                    TenantInvitationRole
                    .invitation_id,

                    Role.code,

                    Role.scope_type,
                )
                .join(
                    Role,
                    Role.id
                    == TenantInvitationRole
                    .role_id,
                )
                .where(
                    Role.scope_type
                    != "tenant"
                )
            )
            .all()
        )


        if bad_invitation_roles:

            failures.append(
                (
                    "Tenant invitations contain "
                    "non-tenant roles."
                )
            )

        else:

            passed.append(
                (
                    "Tenant invitation-role "
                    "scope integrity passed."
                )
            )


        # ====================================================
        # 9. ACTIVE MEMBERSHIPS MUST HAVE A ROLE
        # ====================================================

        roleless_memberships = list(
            db.scalars(
                select(
                    TenantMembership.id
                )
                .outerjoin(
                    TenantMembershipRole,
                    TenantMembershipRole
                    .membership_id
                    == TenantMembership.id,
                )
                .where(
                    TenantMembership.status
                    == "active"
                )
                .group_by(
                    TenantMembership.id
                )
                .having(
                    func.count(
                        TenantMembershipRole
                        .role_id
                    )
                    == 0
                )
            )
        )


        if roleless_memberships:

            failures.append(
                (
                    "Active tenant memberships "
                    "without roles: "
                    + ", ".join(
                        str(value)
                        for value
                        in roleless_memberships
                    )
                )
            )

        else:

            passed.append(
                (
                    "Every active tenant "
                    "membership has a role."
                )
            )


        # ====================================================
        # 10. ACTIVE PLATFORM OWNER EXISTS
        # ====================================================

        platform_owner_count = (
            db.scalar(
                select(
                    func.count()
                )
                .select_from(
                    PlatformUserRole
                )
                .join(
                    User,
                    User.id
                    == PlatformUserRole.user_id,
                )
                .join(
                    Role,
                    Role.id
                    == PlatformUserRole.role_id,
                )
                .where(
                    User.status
                    == "active",

                    Role.scope_type
                    == "platform",

                    Role.code
                    == "platform_owner",
                )
            )
            or 0
        )


        if (
            platform_owner_count
            < 1
        ):

            failures.append(
                (
                    "No active Platform Owner "
                    "assignment exists."
                )
            )

        else:

            passed.append(
                (
                    "At least one active "
                    "Platform Owner exists."
                )
            )


        # ====================================================
        # 11. EVERY ACTIVE TENANT HAS AN ACTIVE OWNER
        # ====================================================

        active_tenant_ids = set(
            db.scalars(
                select(
                    Tenant.id
                )
                .where(
                    Tenant.status
                    == "active"
                )
            )
        )


        owner_tenant_ids = set(
            db.scalars(
                select(
                    TenantMembership.tenant_id
                )
                .join(
                    TenantMembershipRole,
                    TenantMembershipRole
                    .membership_id
                    == TenantMembership.id,
                )
                .join(
                    Role,
                    Role.id
                    == TenantMembershipRole
                    .role_id,
                )
                .where(
                    TenantMembership.status
                    == "active",

                    Role.scope_type
                    == "tenant",

                    Role.code
                    == "tenant_owner",
                )
            )
        )


        missing_owner_tenants = sorted(
            (
                active_tenant_ids
                - owner_tenant_ids
            ),
            key=str,
        )


        if missing_owner_tenants:

            failures.append(
                (
                    "Active tenants without "
                    "an active Tenant Owner: "
                    + ", ".join(
                        str(value)
                        for value
                        in missing_owner_tenants
                    )
                )
            )

        else:

            passed.append(
                (
                    "Every active tenant has "
                    "an active Tenant Owner."
                )
            )


        # ====================================================
        # RESULT
        # ====================================================

        print()
        print(
            "============================================="
        )
        print(
            "AUGMIS PHASE 4 RBAC INTEGRITY VERIFICATION"
        )
        print(
            "============================================="
        )
        print()


        for item in passed:

            print(
                f"[PASS] {item}"
            )


        if failures:

            print()

            for item in failures:

                print(
                    f"[FAIL] {item}"
                )


            print()
            print(
                "PHASE 4 RBAC INTEGRITY CHECK: FAILED"
            )

            raise SystemExit(
                1
            )


        print()
        print(
            "PHASE 4 RBAC INTEGRITY CHECK: PASSED"
        )


    finally:

        db.close()


if __name__ == "__main__":

    main()