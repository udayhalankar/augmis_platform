import api from "@/lib/api";

export type OrganizationPublisher = {
  id: string;
  name: string;
  slug: string;
  status: string;
  tenantId: string | null;
};

export async function loadOrganizationPublishers(tenantId: string): Promise<OrganizationPublisher[]> {
  const response = await api.get<OrganizationPublisher[]>(
    `/api/v1/publishers/organizations/${encodeURIComponent(tenantId)}`,
  );
  return response.data;
}

export async function activateOrganizationPublisher(tenantId: string): Promise<OrganizationPublisher> {
  const response = await api.post<OrganizationPublisher>(
    `/api/v1/publishers/organizations/${encodeURIComponent(tenantId)}/activate`,
  );
  return response.data;
}
