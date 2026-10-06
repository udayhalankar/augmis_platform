from __future__ import annotations

import uuid

from unittest.mock import patch

from sqlalchemy import select

from services.api.app.core.rbac_catalog import (
    PERMISSION_DEFINITIONS,
    ROLE_BLUEPRINTS,
    role_is_protected,
)

from services.api.app.db.session import (
    SessionLocal,
)

from services.api.app.models.iam import (
    Permission,
    PlatformUserRole,
    PublisherMembership,
    PublisherMembershipRole,
    Role,
    RolePermission,
    TenantMembership,
    TenantMembershipRole,
    User,
)

from services.api.app.models.platform import (
    Publisher,
    Tenant,
)

from services.api.app.services.authorization_service import (
    AuthorizationError,
    require_platform_permission,
    require_protected_tenant_role_manager,
    require_publisher_permission,
    require_tenant_permission,
)

from services.api.app.services.rbac_admin_service import (
    RbacAdminError,
    replace_role_permissions,
)

from services.api.app.services.tenant_user_service import (
    TenantUserServiceError,
    _protect_last_active_owner,
    replace_membership_roles,
    set_membership_status,
)


failures: list[str] = []
passes = 0


def pass_result(
    message: str,
) -> None:

    global passes

    passes += 1

    print(
        f"[PASS] {message}"
    )


def fail_result(
    message: str,
) -> None:

    failures.append(
        message
    )

    print(
        f"[FAIL] {message}"
    )


def expect(
    condition: bool,
    message: str,
) -> None:

    if condition:

        pass_result(
            message
        )

    else:

        fail_result(
            message
        )


def role_for(
    db,
    scope_type: str,
    role_code: str,
) -> Role:

    role = db.scalar(
        select(
            Role
        )
        .where(
            Role.scope_type
            == scope_type,

            Role.code
            == role_code,
        )
    )

    if not role:

        raise RuntimeError(
            (
                "Required RBAC role is missing: "
                f"{scope_type}:{role_code}"
            )
        )

    return role


def actual_role_permissions(
    db,
    role: Role,
) -> set[str]:

    return set(
        db.scalars(
            select(
                Permission.code
            )
            .join(
                RolePermission,
                RolePermission.permission_id
                == Permission.id,
            )
            .where(
                RolePermission.role_id
                == role.id,
            )
        )
    )


def make_user(
    label: str,
) -> User:

    suffix = (
        uuid.uuid4()
        .hex[:12]
    )

    email = (
        f"phase4.matrix.{label}."
        f"{suffix}@augmis.test"
    )

    return User(
        email=email,
        email_normalized=(
            email.lower()
        ),
        password_hash=(
            "phase4-matrix-not-a-login"
        ),
        first_name="Phase4",
        last_name=label,
        status="active",
    )


def permission_codes_for_scope(
    scope_type: str,
) -> set[str]:

    return {
        code
        for (
            code,
            definition,
        ) in PERMISSION_DEFINITIONS.items()
        if definition[
            "scope_type"
        ] == scope_type
    }


def expect_authorization(
    *,
    message: str,
    expected_allowed: bool,
    operation,
) -> None:

    try:

        operation()

        actual_allowed = True

    except AuthorizationError:

        actual_allowed = False

    except Exception as error:

        fail_result(
            (
                f"{message} "
                f"(unexpected exception: "
                f"{type(error).__name__}: "
                f"{error})"
            )
        )

        return

    expect(
        actual_allowed
        == expected_allowed,

        (
            f"{message} -> "
            f"{'ALLOW' if expected_allowed else 'DENY'}"
        ),
    )


def expect_service_conflict(
    *,
    message: str,
    operation,
) -> None:

    try:

        operation()

    except TenantUserServiceError as error:

        expect(
            error.status_code == 409,
            (
                f"{message} "
                "returns 409"
            ),
        )

        return

    except Exception as error:

        fail_result(
            (
                f"{message} "
                f"(unexpected exception: "
                f"{type(error).__name__}: "
                f"{error})"
            )
        )

        return

    fail_result(
        (
            f"{message} "
            "unexpectedly succeeded"
        )
    )


def main() -> None:

    print()
    print(
        "AUGMIS PHASE 4 RBAC MATRIX VERIFICATION"
    )
    print(
        "=" * 45
    )
    print()

    db = SessionLocal()

    try:

        # ====================================================
        # 1. CANONICAL ROLE -> PERMISSION MATRIX
        # ====================================================

        print(
            "--- Canonical role matrix ---"
        )

        for (
            scope_type,
            role_code,
        ), definition in (
            ROLE_BLUEPRINTS.items()
        ):

            role = role_for(
                db,
                scope_type,
                role_code,
            )

            expected_codes = set(
                definition[
                    "permissions"
                ]
            )

            actual_codes = (
                actual_role_permissions(
                    db,
                    role,
                )
            )

            expect(
                actual_codes
                == expected_codes,
                (
                    "Role permissions match: "
                    f"{scope_type}:"
                    f"{role_code}"
                ),
            )

        # ====================================================
        # 2. TEMPORARY TEST RESOURCES
        # ====================================================

        suffix = (
            uuid.uuid4()
            .hex[:12]
        )

        tenant_a = Tenant(
            name=(
                "Phase 4 Matrix Tenant A"
            ),
            slug=(
                f"phase4-matrix-a-{suffix}"
            ),
            status="active",
        )

        tenant_b = Tenant(
            name=(
                "Phase 4 Matrix Tenant B"
            ),
            slug=(
                f"phase4-matrix-b-{suffix}"
            ),
            status="active",
        )

        tenant_single_owner = Tenant(
            name=(
                "Phase 4 Matrix Single Owner"
            ),
            slug=(
                f"phase4-matrix-single-{suffix}"
            ),
            status="active",
        )

        publisher_a = Publisher(
            name=(
                "Phase 4 Matrix Publisher A"
            ),
            slug=(
                f"phase4-matrix-pub-a-{suffix}"
            ),
            status="active",
        )

        publisher_b = Publisher(
            name=(
                "Phase 4 Matrix Publisher B"
            ),
            slug=(
                f"phase4-matrix-pub-b-{suffix}"
            ),
            status="active",
        )

        db.add_all(
            [
                tenant_a,
                tenant_b,
                tenant_single_owner,
                publisher_a,
                publisher_b,
            ]
        )

        db.flush()

        tenant_subjects: dict[
            str,
            tuple[
                User,
                TenantMembership,
            ],
        ] = {}

        publisher_subjects: dict[
            str,
            tuple[
                User,
                PublisherMembership,
            ],
        ] = {}

        platform_subjects: dict[
            str,
            User,
        ] = {}

        # ====================================================
        # 3. CREATE ONE SUBJECT PER CANONICAL ROLE
        # ====================================================

        for (
            scope_type,
            role_code,
        ), _definition in (
            ROLE_BLUEPRINTS.items()
        ):

            role = role_for(
                db,
                scope_type,
                role_code,
            )

            user = make_user(
                f"{scope_type}-{role_code}"
            )

            db.add(
                user
            )

            db.flush()

            if scope_type == "platform":

                db.add(
                    PlatformUserRole(
                        user_id=user.id,
                        role_id=role.id,
                    )
                )

                platform_subjects[
                    role_code
                ] = user

            elif scope_type == "tenant":

                membership = (
                    TenantMembership(
                        tenant_id=(
                            tenant_a.id
                        ),
                        user_id=user.id,
                        status="active",
                    )
                )

                db.add(
                    membership
                )

                db.flush()

                db.add(
                    TenantMembershipRole(
                        membership_id=(
                            membership.id
                        ),
                        role_id=role.id,
                    )
                )

                tenant_subjects[
                    role_code
                ] = (
                    user,
                    membership,
                )

            elif scope_type == "publisher":

                membership = (
                    PublisherMembership(
                        publisher_id=(
                            publisher_a.id
                        ),
                        user_id=user.id,
                        status="active",
                    )
                )

                db.add(
                    membership
                )

                db.flush()

                db.add(
                    PublisherMembershipRole(
                        membership_id=(
                            membership.id
                        ),
                        role_id=role.id,
                    )
                )

                publisher_subjects[
                    role_code
                ] = (
                    user,
                    membership,
                )

        # ----------------------------------------------------
        # Add a SECOND Tenant Owner.
        #
        # This is essential for the self-demotion test.
        # Without another owner, the old last-owner rule would
        # also return 409 and could hide a broken self-lockout
        # implementation.
        # ----------------------------------------------------

        tenant_owner_role = role_for(
            db,
            "tenant",
            "tenant_owner",
        )

        owner_peer = make_user(
            "tenant-owner-peer"
        )

        db.add(
            owner_peer
        )

        db.flush()

        owner_peer_membership = (
            TenantMembership(
                tenant_id=tenant_a.id,
                user_id=owner_peer.id,
                status="active",
            )
        )

        db.add(
            owner_peer_membership
        )

        db.flush()

        db.add(
            TenantMembershipRole(
                membership_id=(
                    owner_peer_membership.id
                ),
                role_id=(
                    tenant_owner_role.id
                ),
            )
        )

        # ====================================================
        # 4. PLATFORM ROLE MATRIX
        # ====================================================

        db.flush()

        print()
        print(
            "--- Platform authorization matrix ---"
        )

        platform_permissions = (
            permission_codes_for_scope(
                "platform"
            )
        )

        for (
            scope_type,
            role_code,
        ), definition in (
            ROLE_BLUEPRINTS.items()
        ):

            if scope_type != "platform":
                continue

            user = (
                platform_subjects[
                    role_code
                ]
            )

            expected_permissions = set(
                definition[
                    "permissions"
                ]
            )

            for permission_code in sorted(
                platform_permissions
            ):

                expect_authorization(
                    message=(
                        f"{role_code} -> "
                        f"{permission_code}"
                    ),
                    expected_allowed=(
                        permission_code
                        in expected_permissions
                    ),
                    operation=lambda u=user, p=permission_code: (
                        require_platform_permission(
                            db=db,
                            user=u,
                            permission_code=p,
                        )
                    ),
                )

        # ====================================================
        # 5. TENANT ROLE MATRIX
        # ====================================================

        print()
        print(
            "--- Tenant authorization matrix ---"
        )

        tenant_permissions = (
            permission_codes_for_scope(
                "tenant"
            )
        )

        for (
            scope_type,
            role_code,
        ), definition in (
            ROLE_BLUEPRINTS.items()
        ):

            if scope_type != "tenant":
                continue

            user, _membership = (
                tenant_subjects[
                    role_code
                ]
            )

            expected_permissions = set(
                definition[
                    "permissions"
                ]
            )

            for permission_code in sorted(
                tenant_permissions
            ):

                expect_authorization(
                    message=(
                        f"{role_code} -> "
                        f"{permission_code}"
                    ),
                    expected_allowed=(
                        permission_code
                        in expected_permissions
                    ),
                    operation=lambda u=user, p=permission_code: (
                        require_tenant_permission(
                            db=db,
                            user=u,
                            tenant_id=(
                                tenant_a.id
                            ),
                            permission_code=p,
                        )
                    ),
                )

        # ====================================================
        # 6. PUBLISHER ROLE MATRIX
        # ====================================================

        print()
        print(
            "--- Publisher authorization matrix ---"
        )

        publisher_permissions = (
            permission_codes_for_scope(
                "publisher"
            )
        )

        for (
            scope_type,
            role_code,
        ), definition in (
            ROLE_BLUEPRINTS.items()
        ):

            if scope_type != "publisher":
                continue

            user, _membership = (
                publisher_subjects[
                    role_code
                ]
            )

            expected_permissions = set(
                definition[
                    "permissions"
                ]
            )

            for permission_code in sorted(
                publisher_permissions
            ):

                expect_authorization(
                    message=(
                        f"{role_code} -> "
                        f"{permission_code}"
                    ),
                    expected_allowed=(
                        permission_code
                        in expected_permissions
                    ),
                    operation=lambda u=user, p=permission_code: (
                        require_publisher_permission(
                            db=db,
                            user=u,
                            publisher_id=(
                                publisher_a.id
                            ),
                            permission_code=p,
                        )
                    ),
                )

        # ====================================================
        # 7. CROSS-SCOPE / CROSS-RESOURCE BOUNDARIES
        # ====================================================

        print()
        print(
            "--- Scope boundary checks ---"
        )

        tenant_owner_user, _ = (
            tenant_subjects[
                "tenant_owner"
            ]
        )

        publisher_owner_user, _ = (
            publisher_subjects[
                "publisher_owner"
            ]
        )

        platform_owner_user = (
            platform_subjects[
                "platform_owner"
            ]
        )

        expect_authorization(
            message=(
                "Tenant Owner cannot access "
                "another tenant"
            ),
            expected_allowed=False,
            operation=lambda: (
                require_tenant_permission(
                    db=db,
                    user=tenant_owner_user,
                    tenant_id=tenant_b.id,
                    permission_code=(
                        "tenant.users.view"
                    ),
                )
            ),
        )

        expect_authorization(
            message=(
                "Publisher Owner cannot access "
                "another publisher"
            ),
            expected_allowed=False,
            operation=lambda: (
                require_publisher_permission(
                    db=db,
                    user=publisher_owner_user,
                    publisher_id=(
                        publisher_b.id
                    ),
                    permission_code=(
                        "application.manage"
                    ),
                )
            ),
        )

        expect_authorization(
            message=(
                "Platform Owner does not "
                "implicitly bypass tenant scope"
            ),
            expected_allowed=False,
            operation=lambda: (
                require_tenant_permission(
                    db=db,
                    user=platform_owner_user,
                    tenant_id=tenant_a.id,
                    permission_code=(
                        "tenant.users.view"
                    ),
                )
            ),
        )

        expect_authorization(
            message=(
                "Tenant Owner does not gain "
                "platform RBAC permission"
            ),
            expected_allowed=False,
            operation=lambda: (
                require_platform_permission(
                    db=db,
                    user=tenant_owner_user,
                    permission_code=(
                        "platform.rbac.manage"
                    ),
                )
            ),
        )

                # ====================================================
        # 8. SUSPENDED / REVOKED MEMBERSHIPS
        # ====================================================

        print()
        print(
            "--- Membership lifecycle boundaries ---"
        )

        standard_role = role_for(
            db,
            "tenant",
            "standard_user",
        )

        for status in (
            "suspended",
            "revoked",
        ):

            blocked_user = make_user(
                f"tenant-{status}"
            )

            db.add(
                blocked_user
            )

            db.flush()

            blocked_membership = (
                TenantMembership(
                    tenant_id=tenant_a.id,
                    user_id=blocked_user.id,
                    status=status,
                )
            )

            db.add(
                blocked_membership
            )

            db.flush()

            db.add(
                TenantMembershipRole(
                    membership_id=(
                        blocked_membership.id
                    ),
                    role_id=(
                        standard_role.id
                    ),
                )
            )

            db.flush()

            expect_authorization(
                message=(
                    f"{status} tenant membership "
                    "cannot authorize"
                ),
                expected_allowed=False,
                operation=lambda u=blocked_user: (
                    require_tenant_permission(
                        db=db,
                        user=u,
                        tenant_id=tenant_a.id,
                        permission_code=(
                            "application.instance.view"
                        ),
                    )
                ),
            )

        publisher_developer_role = role_for(
            db,
            "publisher",
            "publisher_developer",
        )

        for status in (
            "suspended",
            "revoked",
        ):

            blocked_user = make_user(
                f"publisher-{status}"
            )

            db.add(
                blocked_user
            )

            db.flush()

            blocked_membership = (
                PublisherMembership(
                    publisher_id=(
                        publisher_a.id
                    ),
                    user_id=(
                        blocked_user.id
                    ),
                    status=status,
                )
            )

            db.add(
                blocked_membership
            )

            db.flush()

            db.add(
                PublisherMembershipRole(
                    membership_id=(
                        blocked_membership.id
                    ),
                    role_id=(
                        publisher_developer_role.id
                    ),
                )
            )

            db.flush()

            expect_authorization(
                message=(
                    f"{status} publisher membership "
                    "cannot authorize"
                ),
                expected_allowed=False,
                operation=lambda u=blocked_user: (
                    require_publisher_permission(
                        db=db,
                        user=u,
                        publisher_id=(
                            publisher_a.id
                        ),
                        permission_code=(
                            "application.manage"
                        ),
                    )
                ),
            )
        # ====================================================
        # 9. PROTECTED TENANT OWNER MANAGEMENT
        # ====================================================

        print()
        print(
            "--- Protected Tenant Owner checks ---"
        )

        tenant_admin_user, _ = (
            tenant_subjects[
                "tenant_admin"
            ]
        )

        try:

            require_protected_tenant_role_manager(
                db=db,
                user_id=tenant_owner_user.id,
                tenant_id=tenant_a.id,
            )

            pass_result(
                "Active Tenant Owner may manage protected owner access"
            )

        except Exception as error:

            fail_result(
                (
                    "Active Tenant Owner was denied "
                    f"protected owner management: {error}"
                )
            )

        try:

            require_protected_tenant_role_manager(
                db=db,
                user_id=tenant_admin_user.id,
                tenant_id=tenant_a.id,
            )

            fail_result(
                "Tenant Admin unexpectedly managed protected owner access"
            )

        except AuthorizationError:

            pass_result(
                "Tenant Admin cannot manage protected owner access"
            )

        # ====================================================
        # 10. PROTECTED ROLE BLUEPRINTS
        # ====================================================

        print()
        print(
            "--- Protected role mutation checks ---"
        )

        protected_roles = [
            (
                "platform",
                "platform_owner",
            ),
            (
                "tenant",
                "tenant_owner",
            ),
            (
                "publisher",
                "publisher_owner",
            ),
        ]

        for (
            scope_type,
            role_code,
        ) in protected_roles:

            role = role_for(
                db,
                scope_type,
                role_code,
            )

            expect(
                role_is_protected(
                    scope_type,
                    role_code,
                ),
                (
                    "Role is protected: "
                    f"{scope_type}:"
                    f"{role_code}"
                ),
            )

            current_permissions = (
                actual_role_permissions(
                    db,
                    role,
                )
            )

            try:

                replace_role_permissions(
                    db=db,
                    role_id=role.id,
                    permission_codes=sorted(
                        current_permissions
                    ),
                )

                fail_result(
                    (
                        "Protected role mutation "
                        "unexpectedly succeeded: "
                        f"{scope_type}:"
                        f"{role_code}"
                    )
                )

            except RbacAdminError as error:

                expect(
                    error.status_code == 409,
                    (
                        "Protected role mutation blocked: "
                        f"{scope_type}:"
                        f"{role_code}"
                    ),
                )

        # ====================================================
        # 11. SELF-LOCKOUT PROTECTION
        # ====================================================

        print()
        print(
            "--- Self-lockout protections ---"
        )

        (
            self_owner_user,
            self_owner_membership,
        ) = (
            tenant_subjects[
                "tenant_owner"
            ]
        )

        # Use nested SAVEPOINTS and deliberately prevent commits.
        #
        # If the protection is accidentally missing, the verifier
        # will catch the attempted commit and roll the SAVEPOINT
        # back instead of modifying real data.

        savepoint = db.begin_nested()

        try:

            with patch.object(
                db,
                "commit",
                side_effect=RuntimeError(
                    "COMMIT_REACHED"
                ),
            ):

                try:

                    replace_membership_roles(
                        db=db,
                        tenant_id=tenant_a.id,
                        membership_id=(
                            self_owner_membership.id
                        ),
                        actor_user_id=(
                            self_owner_user.id
                        ),
                        role_codes=[
                            "standard_user"
                        ],
                    )

                    fail_result(
                        (
                            "Tenant Owner self-demotion "
                            "unexpectedly succeeded"
                        )
                    )

                except TenantUserServiceError as error:

                    expect(
                        error.status_code
                        == 409,
                        (
                            "Tenant Owner cannot "
                            "demote self"
                        ),
                    )

                except RuntimeError as error:

                    if str(
                        error
                    ) == "COMMIT_REACHED":

                        fail_result(
                            (
                                "Tenant Owner self-demotion "
                                "reached commit; self-lockout "
                                "protection is missing"
                            )
                        )

                    else:

                        raise

        finally:

            savepoint.rollback()

        for new_status in (
            "suspended",
            "revoked",
        ):

            savepoint = (
                db.begin_nested()
            )

            try:

                with patch.object(
                    db,
                    "commit",
                    side_effect=RuntimeError(
                        "COMMIT_REACHED"
                    ),
                ):

                    try:

                        set_membership_status(
                            db=db,
                            tenant_id=(
                                tenant_a.id
                            ),
                            membership_id=(
                                self_owner_membership.id
                            ),
                            actor_user_id=(
                                self_owner_user.id
                            ),
                            new_status=(
                                new_status
                            ),
                        )

                        fail_result(
                            (
                                "Tenant Owner self-"
                                f"{new_status} unexpectedly "
                                "succeeded"
                            )
                        )

                    except TenantUserServiceError as error:

                        expect(
                            error.status_code
                            == 409,
                            (
                                "Tenant Owner cannot "
                                f"{new_status} self"
                            ),
                        )

                    except RuntimeError as error:

                        if str(
                            error
                        ) == "COMMIT_REACHED":

                            fail_result(
                                (
                                    "Tenant Owner self-"
                                    f"{new_status} reached "
                                    "commit; protection "
                                    "is missing"
                                )
                            )

                        else:

                            raise

            finally:

                savepoint.rollback()

        # ====================================================
        # 12. LAST ACTIVE OWNER DEFENCE-IN-DEPTH
        # ====================================================

        print()
        print(
            "--- Last-owner defence ---"
        )

        single_owner_user = make_user(
            "single-owner"
        )

        db.add(
            single_owner_user
        )

        db.flush()

        single_owner_membership = (
            TenantMembership(
                tenant_id=(
                    tenant_single_owner.id
                ),
                user_id=(
                    single_owner_user.id
                ),
                status="active",
            )
        )

        db.add(
            single_owner_membership
        )

        db.flush()

        db.add(
            TenantMembershipRole(
                membership_id=(
                    single_owner_membership.id
                ),
                role_id=(
                    tenant_owner_role.id
                ),
            )
        )

        db.flush()

        expect_service_conflict(
            message=(
                "Last active Tenant Owner "
                "removal protection"
            ),
            operation=lambda: (
                _protect_last_active_owner(
                    db=db,
                    membership=(
                        single_owner_membership
                    ),
                )
            ),
        )

        # ====================================================
        # RESULT
        # ====================================================

        print()
        print(
            "=" * 45
        )

        if failures:

            print(
                (
                    "PHASE 4 RBAC MATRIX CHECK: "
                    "FAILED"
                )
            )

            print()

            for failure in failures:

                print(
                    f"  - {failure}"
                )

            raise SystemExit(
                1
            )

        print(
            (
                "PHASE 4 RBAC MATRIX CHECK: "
                "PASSED"
            )
        )

        print(
            f"Assertions passed: {passes}"
        )

    finally:

        # IMPORTANT:
        #
        # The verifier deliberately does not persist any of its
        # synthetic users, memberships, tenants or publishers.

        db.rollback()
        db.close()


if __name__ == "__main__":

    main()