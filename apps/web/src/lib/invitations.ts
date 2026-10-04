// apps/web/src/lib/invitations.ts

import api from "@/lib/api";

export type InvitationRole = {
  id: string;
  code: string;
  name: string;
};

export type InvitationTenant = {
  id: string;
  name: string;
  slug: string;
};

export type InvitationUser = {
  id: string;
  email: string;
  firstName: string;
  lastName: string;
  status: string;
};

export type InvitationResolveResult = {
  invitationId: string;
  email: string;
  status: string;
  expiresAt: string;
  existingUser: boolean;
  canAccept: boolean;
  tenant: InvitationTenant;
  roles: InvitationRole[];
};

export type InvitationAcceptanceResult = {
  status: string;
  invitationId: string;
  membershipId: string;
  tenant: InvitationTenant;
  user: InvitationUser;
  roles: InvitationRole[];
  accessToken: string | null;
  tokenType: string | null;
};

export type TenantInvitation = {
  invitationId: string;
  email: string;
  status: string;
  deliveryStatus: string;
  deliveryAttempts: number;
  lastSentAt: string | null;
  createdAt: string;
  expiresAt: string;
  acceptedAt: string | null;
  revokedAt: string | null;
  invitedByUserId: string | null;
  acceptedByUserId: string | null;
  existingUser: boolean;
  roles: InvitationRole[];
};

export type CreateTenantInvitationRequest = {
  email: string;
  roleCodes: string[];
};

export type CreateTenantInvitationResult =
  TenantInvitation & {
    invitationToken: string | null;
    acceptanceUrl: string | null;
  };

export async function resolveTenantInvitation(
  token: string
): Promise<InvitationResolveResult> {
  const response =
    await api.get<InvitationResolveResult>(
      "/api/v1/invitations/resolve",
      {
        params: {
          token,
        },
      }
    );

  return response.data;
}

export async function acceptExistingTenantInvitation(
  token: string
): Promise<InvitationAcceptanceResult> {
  const response =
    await api.post<InvitationAcceptanceResult>(
      "/api/v1/invitations/accept-existing",
      {
        token,
      }
    );

  return response.data;
}

export async function acceptNewTenantInvitation(
  payload: {
    token: string;
    firstName: string;
    lastName: string;
    password: string;
  }
): Promise<InvitationAcceptanceResult> {
  const response =
    await api.post<InvitationAcceptanceResult>(
      "/api/v1/invitations/accept-new",
      payload
    );

  return response.data;
}

export async function loadTenantInvitations(
  tenantId: string
): Promise<TenantInvitation[]> {
  const response =
    await api.get<TenantInvitation[]>(
      `/api/v1/tenants/${tenantId}/invitations`
    );

  return response.data;
}

export async function createTenantInvitation(
  tenantId: string,
  payload: CreateTenantInvitationRequest
): Promise<CreateTenantInvitationResult> {
  const response =
    await api.post<CreateTenantInvitationResult>(
      `/api/v1/tenants/${tenantId}/invitations`,
      payload
    );

  return response.data;
}

export async function revokeTenantInvitation(
  tenantId: string,
  invitationId: string
): Promise<TenantInvitation> {
  const response =
    await api.post<TenantInvitation>(
      `/api/v1/tenants/${tenantId}/invitations/${invitationId}/revoke`
    );

  return response.data;
}

export async function reissueTenantInvitation(
  tenantId: string,
  invitationId: string
): Promise<CreateTenantInvitationResult> {
  const response =
    await api.post<CreateTenantInvitationResult>(
      `/api/v1/tenants/${tenantId}/invitations/${invitationId}/reissue`
    );

  return response.data;
}
