import api from "@/lib/api";

export type PublisherRole = { id: string; code: string; name: string };
export type PublisherMember = {
  membershipId: string;
  status: "active" | "suspended" | "revoked";
  createdAt: string;
  user: {
    id: string;
    email: string;
    firstName: string;
    lastName: string;
    status: string;
  };
  roles: PublisherRole[];
};

const base = (publisherId: string) =>
  `/api/v1/publishers/${encodeURIComponent(publisherId)}`;

export async function loadMyPublisherPermissions(publisherId: string): Promise<string[]> {
  const result = await api.get<{ permissions: string[] }>(
    `${base(publisherId)}/me/permissions`
  );
  return result.data.permissions;
}

export async function loadPublisherRoles(publisherId: string): Promise<PublisherRole[]> {
  const result = await api.get<PublisherRole[]>(`${base(publisherId)}/roles`);
  return result.data;
}

export async function loadPublisherMembers(publisherId: string): Promise<PublisherMember[]> {
  const result = await api.get<PublisherMember[]>(`${base(publisherId)}/users`);
  return result.data;
}

export async function addPublisherMember(
  publisherId: string, email: string, roleCodes: string[]
): Promise<PublisherMember> {
  const result = await api.post<PublisherMember>(`${base(publisherId)}/users`, {
    email, roleCodes,
  });
  return result.data;
}

export async function changePublisherMemberRoles(
  publisherId: string, membershipId: string, roleCodes: string[]
): Promise<PublisherMember> {
  const result = await api.put<PublisherMember>(
    `${base(publisherId)}/memberships/${encodeURIComponent(membershipId)}/roles`,
    { roleCodes }
  );
  return result.data;
}

export async function setPublisherMemberStatus(
  publisherId: string, membershipId: string,
  action: "suspend" | "activate" | "revoke"
): Promise<PublisherMember> {
  const result = await api.post<PublisherMember>(
    `${base(publisherId)}/memberships/${encodeURIComponent(membershipId)}/${action}`
  );
  return result.data;
}
