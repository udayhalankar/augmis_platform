// apps/web/src/lib/tenants.ts

import api from "@/lib/api";


export type TenantCreateRequest = {
  name: string;
  slug: string;
};


export type TenantResponse = {
  id: string;
  name: string;
  slug: string;
  status: string;
};


export async function createTenant(
  payload: TenantCreateRequest
): Promise<TenantResponse> {

  const response =
    await api.post<TenantResponse>(
      "/api/v1/tenants",
      payload
    );

  return response.data;
}