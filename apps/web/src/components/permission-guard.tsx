// apps/web/src/components/permission-guard.tsx

"use client";

import {
  ReactNode,
} from "react";

import {
  Alert,
  Box,
  CircularProgress,
} from "@mui/material";

import {
  usePermissions,
} from "@/context/permission-context";


type PermissionGuardProps = {

  scope:
    | "platform"
    | "tenant";

  permission: string;

  children: ReactNode;
};


export default function PermissionGuard({
  scope,
  permission,
  children,
}: PermissionGuardProps) {

  const {
    platformLoading,
    tenantLoading,
    hasPlatformPermission,
    hasTenantPermission,
  } = usePermissions();


  const loading =
    scope === "platform"
      ? platformLoading
      : tenantLoading;


  if (loading) {

    return (
      <Box
        sx={{
          minHeight: 240,
          display: "grid",
          placeItems: "center",
        }}
      >
        <CircularProgress
          size={28}
        />
      </Box>
    );
  }


  const allowed =
    scope === "platform"
      ? hasPlatformPermission(
          permission
        )
      : hasTenantPermission(
          permission
        );


  if (!allowed) {

    return (
      <Alert
        severity="error"
      >
        You do not have permission to access this area.
      </Alert>
    );
  }


  return children;
}