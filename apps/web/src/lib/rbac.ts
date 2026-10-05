// apps/web/src/lib/rbac.ts

import api from "@/lib/api";


export type RbacScope =
  | "platform"
  | "publisher"
  | "tenant";


export type PermissionSnapshot = {
  scopeType: string;
  permissions: string[];
};


export type RbacPermission = {
  id: string;
  code: string;
  name: string;
  scopeType: RbacScope;
};


export type RbacRole = {
  id: string;
  scopeType: RbacScope;
  code: string;
  name: string;
  protected: boolean;
  permissions: RbacPermission[];
};


export type ReplaceRolePermissionsRequest = {
  permissionCodes: string[];
};


export async function loadMyPlatformPermissions():
Promise<PermissionSnapshot> {

  const response =
    await api.get<PermissionSnapshot>(
      "/api/v1/auth/permissions"
    );

  return response.data;
}


export async function loadMyTenantPermissions(
  tenantId: string
): Promise<PermissionSnapshot> {

  const response =
    await api.get<PermissionSnapshot>(
      `/api/v1/tenants/${tenantId}/me/permissions`
    );

  return response.data;
}


export async function loadRbacPermissions(
  scopeType: RbacScope
): Promise<RbacPermission[]> {

  const response =
    await api.get<RbacPermission[]>(
      "/api/v1/rbac/permissions",
      {
        params: {
          scopeType,
        },
      }
    );

  return response.data;
}


export async function loadRbacRoles(
  scopeType: RbacScope
): Promise<RbacRole[]> {

  const response =
    await api.get<RbacRole[]>(
      "/api/v1/rbac/roles",
      {
        params: {
          scopeType,
        },
      }
    );

  return response.data;
}


export async function replaceRbacRolePermissions(
  roleId: string,
  payload: ReplaceRolePermissionsRequest
): Promise<RbacRole> {

  const response =
    await api.put<RbacRole>(
      `/api/v1/rbac/roles/${roleId}/permissions`,
      payload
    );

  return response.data;
}