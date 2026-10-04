// apps/web/src/context/tenant-context.tsx

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
  loadMyTenants,
  MyTenantMembership,
} from "@/lib/tenant-context-api";


const TENANT_STORAGE_KEY =
  "augmis.platform.selectedTenantId";


type TenantContextType = {

  tenants:
    MyTenantMembership[];

  selectedTenant:
    MyTenantMembership | null;

  selectedTenantId:
    string;

  loading:
    boolean;

  error:
    string;

  selectTenant:
    (
      tenantId: string
    ) => void;

  refreshTenants:
    () => Promise<void>;
};


const TenantContext =
  createContext<
    TenantContextType | undefined
  >(undefined);


export function TenantProvider({
  children,
}: {
  children: ReactNode;
}) {

  const {
    user,
    loading: authLoading,
  } = useAuth();


  const [
    tenants,
    setTenants,
  ] = useState<
    MyTenantMembership[]
  >([]);


  const [
    selectedTenantId,
    setSelectedTenantId,
  ] = useState("");


  const [
    loading,
    setLoading,
  ] = useState(false);


  const [
    error,
    setError,
  ] = useState("");


  /*
   * --------------------------------------------------
   * Select tenant
   * --------------------------------------------------
   *
   * Only tenants already present in the current
   * authenticated user's authorized tenant list can
   * become the active tenant.
   *
   * The backend remains the authoritative RBAC
   * security boundary.
   * --------------------------------------------------
   */

  const selectTenant =
    useCallback(
      (
        tenantId: string
      ) => {

        const cleanTenantId =
          String(
            tenantId || ""
          ).trim();


        if (!cleanTenantId) {

          setSelectedTenantId(
            ""
          );

          if (
            typeof window !==
            "undefined"
          ) {

            window.localStorage
              .removeItem(
                TENANT_STORAGE_KEY
              );
          }

          return;
        }


        const allowed =
          tenants.some(
            (
              membership
            ) =>
              membership.status ===
                "active" &&
              membership.tenant.id ===
                cleanTenantId
          );


        if (!allowed) {

          console.warn(
            "[AUGMIS tenant context] " +
            "Rejected unauthorized " +
            "tenant selection:",
            cleanTenantId
          );

          return;
        }


        setSelectedTenantId(
          cleanTenantId
        );


        if (
          typeof window !==
          "undefined"
        ) {

          window.localStorage.setItem(
            TENANT_STORAGE_KEY,
            cleanTenantId
          );
        }
      },
      [
        tenants,
      ]
    );


  /*
   * --------------------------------------------------
   * Load authorized tenants
   * --------------------------------------------------
   */

  const refreshTenants =
    useCallback(
      async () => {

        if (
          authLoading ||
          !user
        ) {

          return;
        }


        setLoading(
          true
        );

        setError(
          ""
        );


        try {

          const memberships =
            await loadMyTenants();


          /*
           * Current backend /me/tenants returns
           * memberships regardless of membership
           * status.
           *
           * For tenant context we expose ACTIVE
           * memberships only.
           */

          const activeMemberships =
            memberships.filter(
              (
                membership
              ) =>
                membership.status ===
                "active"
            );


          setTenants(
            activeMemberships
          );


          let storedTenantId =
            "";


          if (
            typeof window !==
            "undefined"
          ) {

            storedTenantId =
              window.localStorage
                .getItem(
                  TENANT_STORAGE_KEY
                ) || "";
          }


          const storedTenantStillAllowed =
            activeMemberships.some(
              (
                membership
              ) =>
                membership
                  .tenant
                  .id ===
                storedTenantId
            );


          if (
            storedTenantStillAllowed
          ) {

            setSelectedTenantId(
              storedTenantId
            );

            return;
          }


          /*
           * Stored tenant no longer exists,
           * membership was suspended, or this is
           * the user's first login.
           *
           * Automatically select first authorized
           * active tenant.
           */

          const firstTenant =
            activeMemberships[0];


          if (firstTenant) {

            setSelectedTenantId(
              firstTenant.tenant.id
            );


            if (
              typeof window !==
              "undefined"
            ) {

              window.localStorage
                .setItem(
                  TENANT_STORAGE_KEY,
                  firstTenant.tenant.id
                );
            }

          } else {

            setSelectedTenantId(
              ""
            );


            if (
              typeof window !==
              "undefined"
            ) {

              window.localStorage
                .removeItem(
                  TENANT_STORAGE_KEY
                );
            }
          }

        } catch (
          loadError
        ) {

          console.error(
            "[AUGMIS tenant context] " +
            "Unable to load tenants.",
            loadError
          );


          setTenants(
            []
          );

          setSelectedTenantId(
            ""
          );

          setError(
            "Your tenant memberships " +
            "could not be loaded."
          );

        } finally {

          setLoading(
            false
          );
        }
      },
      [
        authLoading,
        user,
      ]
    );


  /*
   * --------------------------------------------------
   * Authentication lifecycle
   * --------------------------------------------------
   */

  useEffect(
    () => {

      if (
        authLoading
      ) {

        return;
      }


      if (!user) {

        setTenants(
          []
        );

        setSelectedTenantId(
          ""
        );

        setError(
          ""
        );

        setLoading(
          false
        );

        return;
      }


      refreshTenants();

    },
    [
      authLoading,
      user,
      refreshTenants,
    ]
  );


  /*
   * --------------------------------------------------
   * Resolve selected tenant object
   * --------------------------------------------------
   */

  const selectedTenant =
    useMemo(
      () => {

        if (
          !selectedTenantId
        ) {

          return null;
        }


        return (
          tenants.find(
            (
              membership
            ) =>
              membership.tenant.id ===
              selectedTenantId
          ) || null
        );

      },
      [
        tenants,
        selectedTenantId,
      ]
    );


  const value =
    useMemo<
      TenantContextType
    >(
      () => ({
        tenants,
        selectedTenant,
        selectedTenantId,
        loading,
        error,
        selectTenant,
        refreshTenants,
      }),
      [
        tenants,
        selectedTenant,
        selectedTenantId,
        loading,
        error,
        selectTenant,
        refreshTenants,
      ]
    );


  return (
    <TenantContext.Provider
      value={value}
    >
      {children}
    </TenantContext.Provider>
  );
}


export function useTenant() {

  const context =
    useContext(
      TenantContext
    );


  if (!context) {

    throw new Error(
      "useTenant must be used inside TenantProvider"
    );
  }


  return context;
}