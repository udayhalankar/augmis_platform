// apps/web/src/lib/tenant-users.ts

import api from "@/lib/api";

export type TenantRole = {
  id: string;
  code: string;
  name: string;
};

export type TenantUserIdentity = {
  id: string;
  email: string;
  firstName: string;
  lastName: string;
  status: string;
};

export type TenantUserMembership = {
  membershipId: string;
  status: string;
  createdAt: string;
  user: TenantUserIdentity;
  roles: TenantRole[];
};

export type AddTenantUserRequest = {
  email: string;
  roleCodes: string[];
};

export type UpdateTenantUserRolesRequest = {
  roleCodes: string[];
};

export async function loadTenantUsers(
  tenantId: string
): Promise<TenantUserMembership[]> {
  const response = await api.get<TenantUserMembership[]>(
    `/api/v1/tenants/${tenantId}/users`
  );
  return response.data;
}

export async function loadTenantRoles(
  tenantId: string
): Promise<TenantRole[]> {
  const response = await api.get<TenantRole[]>(
    `/api/v1/tenants/${tenantId}/roles`
  );
  return response.data;
}

export async function addExistingTenantUser(
  tenantId: string,
  payload: AddTenantUserRequest
): Promise<TenantUserMembership> {
  const response = await api.post<TenantUserMembership>(
    `/api/v1/tenants/${tenantId}/users`,
    payload
  );
  return response.data;
}

export async function replaceTenantUserRoles(
  tenantId: string,
  membershipId: string,
  payload: UpdateTenantUserRolesRequest
): Promise<TenantUserMembership> {
  const response = await api.put<TenantUserMembership>(
    `/api/v1/tenants/${tenantId}/memberships/${membershipId}/roles`,
    payload
  );
  return response.data;
}

export async function suspendTenantUser(
  tenantId: string,
  membershipId: string
): Promise<TenantUserMembership> {
  const response = await api.post<TenantUserMembership>(
    `/api/v1/tenants/${tenantId}/memberships/${membershipId}/suspend`
  );
  return response.data;
}

export async function activateTenantUser(
  tenantId: string,
  membershipId: string
): Promise<TenantUserMembership> {
  const response = await api.post<TenantUserMembership>(
    `/api/v1/tenants/${tenantId}/memberships/${membershipId}/activate`
  );
  return response.data;
}

export async function revokeTenantUser(
  tenantId: string,
  membershipId: string
): Promise<TenantUserMembership> {
  const response = await api.post<TenantUserMembership>(
    `/api/v1/tenants/${tenantId}/memberships/${membershipId}/revoke`
  );
  return response.data;
}
