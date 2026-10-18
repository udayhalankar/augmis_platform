import api from "@/lib/api";


export type TenantAvailableApplication = {
  latestPublishedVersion?: { id: string; version: string } | null;
  promotableVersion?: { id: string; version: string } | null;
  runningVersion?: string | null;
  versionUpdateAvailable?: boolean;
  subscriptionId: string;

  tenant: {
    id: string;
    name: string;
    slug: string;
  };

  application: {
    id: string;
    publisherId: string;
    appKey: string;
    name: string;
    description: string | null;
    status: string;
  };

  offer: {
    id: string;
    offerKey: string;
    name: string;
    deliveryType: string;
    currentStatus: string;
  };

  subscription: {
    status: string;
    startsAt: string | null;
    endsAt: string | null;
    versionPolicy: string;
    autoUpgrade: boolean;
  };

  version: {
    id: string;
    version: string;
    technicalStatus: string;
    publicationStatus: string;
    buildType: string;
    deploymentMode: string;
  };

  entitlement: {
    code: string;
    status: string;
    value: Record<string, unknown> | null;
  };

  available: boolean;
  runtimeReady: boolean;
  runtimeState?: "running" | "stopped" | "available";
};


export type TenantApplicationCatalog = {
  tenant: {
    id: string;
    name: string;
    slug: string;
    status: string;
  };

  count: number;

  items: TenantAvailableApplication[];
};


export async function loadTenantApplications(
  tenantId: string
): Promise<TenantApplicationCatalog> {

  const response =
    await api.get<TenantApplicationCatalog>(
      `/api/v1/tenants/${tenantId}/applications`
    );

  return response.data;
}

export type TenantApplicationLaunchResult = {
  status: "REUSED" | "DEPLOYED" | "STATIC";
  tenantId: string;
  applicationId: string;
  instanceId: string;
  versionId: string;
  version: string;
  runtimeUrl: string;
};


export async function openTenantContainerApplication(
  tenantId: string,
  applicationId: string
): Promise<TenantApplicationLaunchResult> {

  const response =
    await api.post<TenantApplicationLaunchResult>(
      `/api/v1/tenants/${tenantId}/applications/${applicationId}/open`
    );

  return response.data;
}


export async function openTenantStaticApplication(
  tenantId: string,
  applicationId: string
): Promise<TenantApplicationLaunchResult> {

  const response =
    await api.post<TenantApplicationLaunchResult>(
      `/api/v1/tenants/${tenantId}/applications/${applicationId}/open-static`
    );

  return response.data;
}


// C1-C4: uses existing authorized backend; never changes offers or records.
export async function promoteTenantApplicationBaseline(
  subscriptionId: string,
  targetVersionId: string
): Promise<{ status: string; version: string; baselineVersionId: string }> {
  const result = await api.post(
    `/api/v1/subscriptions/${subscriptionId}/promote-baseline`,
    { target_version_id: targetVersionId }
  );
  return result.data;
}
