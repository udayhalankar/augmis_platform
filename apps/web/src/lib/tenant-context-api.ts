// apps/web/src/lib/tenant-context-api.ts

import api from "@/lib/api";


export type MyTenantMembership = {
  membershipId: string;

  tenant: {
    id: string;
    name: string;
    slug: string;
  };

  status: string;
};


export async function loadMyTenants():
  Promise<MyTenantMembership[]> {

  const response =
    await api.get<
      MyTenantMembership[]
    >(
      "/api/v1/me/tenants"
    );


  return response.data;
}