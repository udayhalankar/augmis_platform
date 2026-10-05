// apps/web/src/context/permission-context.tsx

"use client";

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  useAuth,
} from "@/context/auth-context";

import {
  useTenant,
} from "@/context/tenant-context";

import {
  loadMyPlatformPermissions,
  loadMyTenantPermissions,
} from "@/lib/rbac";


type PermissionContextValue = {

  platformPermissions: string[];

  tenantPermissions: string[];

  platformLoading: boolean;

  tenantLoading: boolean;

  hasPlatformPermission:
    (permissionCode: string) => boolean;

  hasTenantPermission:
    (permissionCode: string) => boolean;

  hasAnyPlatformPermission:
    (permissionCodes: string[]) => boolean;

  hasAnyTenantPermission:
    (permissionCodes: string[]) => boolean;

  refreshPermissions:
    () => Promise<void>;
};


const PermissionContext =
  createContext<
    PermissionContextValue | undefined
  >(undefined);


export function PermissionProvider({
  children,
}: {
  children: ReactNode;
}) {

  const {
    user,
  } = useAuth();

  const {
    selectedTenantId,
    loading: tenantContextLoading,
  } = useTenant();


  const [
    platformPermissions,
    setPlatformPermissions,
  ] = useState<string[]>([]);


  const [
    tenantPermissions,
    setTenantPermissions,
  ] = useState<string[]>([]);


  const [
    platformLoading,
    setPlatformLoading,
  ] = useState(true);


  const [
    tenantLoading,
    setTenantLoading,
  ] = useState(true);


  const authenticated =
    Boolean(user);


  const refreshPlatformPermissions =
    useCallback(
      async () => {

        if (!authenticated) {

          setPlatformPermissions([]);

          setPlatformLoading(false);

          return;
        }

        setPlatformLoading(true);

        try {

          const result =
            await loadMyPlatformPermissions();

          setPlatformPermissions(
            Array.isArray(
              result.permissions
            )
              ? result.permissions
              : []
          );

        } catch {

          /*
           * Permission discovery failure must
           * fail closed.
           *
           * The backend remains authoritative.
           */

          setPlatformPermissions([]);

        } finally {

          setPlatformLoading(false);
        }
      },
      [
        authenticated,
      ]
    );


  const refreshTenantPermissions =
    useCallback(
      async () => {

        if (
          !authenticated ||
          !selectedTenantId
        ) {

          setTenantPermissions([]);

          setTenantLoading(false);

          return;
        }

        setTenantLoading(true);

        try {

          const result =
            await loadMyTenantPermissions(
              selectedTenantId
            );

          setTenantPermissions(
            Array.isArray(
              result.permissions
            )
              ? result.permissions
              : []
          );

        } catch {

          /*
           * Fail closed on permission
           * discovery failure.
           */

          setTenantPermissions([]);

        } finally {

          setTenantLoading(false);
        }
      },
      [
        authenticated,
        selectedTenantId,
      ]
    );


  useEffect(
    () => {

      void refreshPlatformPermissions();

    },
    [
      refreshPlatformPermissions,
    ]
  );


  useEffect(
    () => {

      if (tenantContextLoading) {

        setTenantLoading(true);

        return;
      }

      void refreshTenantPermissions();

    },
    [
      tenantContextLoading,
      refreshTenantPermissions,
    ]
  );


  const hasPlatformPermission =
    useCallback(
      (
        permissionCode: string
      ) =>
        platformPermissions.includes(
          permissionCode
        ),
      [
        platformPermissions,
      ]
    );


  const hasTenantPermission =
    useCallback(
      (
        permissionCode: string
      ) =>
        tenantPermissions.includes(
          permissionCode
        ),
      [
        tenantPermissions,
      ]
    );


  const hasAnyPlatformPermission =
    useCallback(
      (
        permissionCodes: string[]
      ) =>
        permissionCodes.some(
          (permissionCode) =>
            platformPermissions.includes(
              permissionCode
            )
        ),
      [
        platformPermissions,
      ]
    );


  const hasAnyTenantPermission =
    useCallback(
      (
        permissionCodes: string[]
      ) =>
        permissionCodes.some(
          (permissionCode) =>
            tenantPermissions.includes(
              permissionCode
            )
        ),
      [
        tenantPermissions,
      ]
    );


  const refreshPermissions =
    useCallback(
      async () => {

        await Promise.all([
          refreshPlatformPermissions(),
          refreshTenantPermissions(),
        ]);
      },
      [
        refreshPlatformPermissions,
        refreshTenantPermissions,
      ]
    );


  const value =
    useMemo<PermissionContextValue>(
      () => ({
        platformPermissions,
        tenantPermissions,

        platformLoading,
        tenantLoading,

        hasPlatformPermission,
        hasTenantPermission,

        hasAnyPlatformPermission,
        hasAnyTenantPermission,

        refreshPermissions,
      }),
      [
        platformPermissions,
        tenantPermissions,

        platformLoading,
        tenantLoading,

        hasPlatformPermission,
        hasTenantPermission,

        hasAnyPlatformPermission,
        hasAnyTenantPermission,

        refreshPermissions,
      ]
    );


  return (
    <PermissionContext.Provider
      value={value}
    >
      {children}
    </PermissionContext.Provider>
  );
}


export function usePermissions():
PermissionContextValue {

  const context =
    useContext(
      PermissionContext
    );

  if (!context) {

    throw new Error(
      "usePermissions must be used inside PermissionProvider."
    );
  }

  return context;
}