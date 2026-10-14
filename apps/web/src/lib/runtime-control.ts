import api from "@/lib/api";

export type RuntimeInstance = {
  id: string;
  applicationId: string;
  versionId: string;
  instanceKey: string;
  name: string;
  status: string;
};
export type RuntimeJob = {
  id: string;
  instanceId: string;
  targetVersionId: string;
  status: string;
  attempts: number;
  errorCode: string | null;
};
export type RuntimeQuota = {
  tenantId: string;
  maxRunningContainers: number | null;
  canManageQuota?: boolean;
};
export type RuntimeConfig = {
  instanceId: string;
  revision: number | null;
  variables: Record<string, string>;
  secretReferenceNames: string[];
  appliesOnNextStart: boolean;
};

export const listRuntimeInstances = async (tenantId: string): Promise<RuntimeInstance[]> =>
  (await api.get<RuntimeInstance[]>(`/api/v1/tenants/${tenantId}/instances`)).data;
export const listRuntimeJobs = async (tenantId: string): Promise<RuntimeJob[]> =>
  (await api.get<RuntimeJob[]>(`/api/v1/tenants/${tenantId}/upgrade-jobs`)).data;
export const getRuntimeQuota = async (tenantId: string): Promise<RuntimeQuota> =>
  (await api.get<RuntimeQuota>(`/api/v1/tenants/${tenantId}/runtime-quota`)).data;
export const getRuntimeConfig = async (instanceId: string): Promise<RuntimeConfig> =>
  (await api.get<RuntimeConfig>(`/api/v1/instances/${instanceId}/configuration`)).data;
export const updateRuntimeConfig = async (
  instanceId: string,
  expected_revision: number | null,
  variables: Record<string, string>,
): Promise<{instanceId: string; revision: number; appliesOnNextStart: boolean}> =>
  (await api.put(`/api/v1/instances/${instanceId}/configuration`, {
    expected_revision,
    variables,
  })).data;

// B1+B2 explicit subscription auto-upgrade consent & read-only eligibility.
export type RuntimeUpgradeReadiness = {
  instanceId: string;
  instanceStatus: string;
  currentVersion: string | null;
  subscriptionId: string | null;
  autoUpgrade: boolean;
  versionPolicy: string | null;
  status: "eligible" | "blocked";
  reason: string;
  candidateVersionId: string | null;
  candidateVersion: string | null;
};

export async function getRuntimeUpgradeReadiness(instanceId: string): Promise<RuntimeUpgradeReadiness> {
  return (await api.get<RuntimeUpgradeReadiness>(`/api/v1/instances/${instanceId}/upgrade-readiness`)).data;
}

export async function updateRuntimeAutoUpgradeConsent(
  instanceId: string,
  expectedAutoUpgrade: boolean,
  autoUpgrade: boolean,
): Promise<{subscriptionId: string; autoUpgrade: boolean; changed: boolean; note: string}> {
  return (await api.put(`/api/v1/instances/${instanceId}/auto-upgrade`, {
    expected_auto_upgrade: expectedAutoUpgrade,
    auto_upgrade: autoUpgrade,
  })).data;
}


// Platform quota mutation; FastAPI enforces platform.settings.manage and audits changes.
export async function updateRuntimeQuota(tenantId: string, maxRunningContainers: number): Promise<RuntimeQuota> {
  return (await api.put<RuntimeQuota>(`/api/v1/tenants/${tenantId}/runtime-quota`, {
    max_running_containers: maxRunningContainers,
  })).data;
}


// B1/B2: explicit instance lifecycle and diagnostics. All calls use the authenticated API client.
export const stopRuntimeInstance = async (instanceId: string): Promise<unknown> =>
  (await api.post(`/api/v1/instances/${encodeURIComponent(instanceId)}/stop`)).data;

export const restartRuntimeInstance = async (instanceId: string): Promise<unknown> =>
  (await api.post(`/api/v1/instances/${encodeURIComponent(instanceId)}/restart`)).data;

export type RuntimeDeploymentSummary = { deploymentId: string; status: string };
export const listRuntimeDeployments = async (instanceId: string): Promise<RuntimeDeploymentSummary[]> =>
  (await api.get<RuntimeDeploymentSummary[]>(`/api/v1/instances/${encodeURIComponent(instanceId)}/deployments`)).data;

export type RuntimeHealthSummary = {
  deploymentStatus: string; effectiveHealth: string; recordedHealth: string;
  container?: { running?: boolean }; runtime?: { reachable?: boolean; httpStatus?: number | null };
};
export const getRuntimeDeploymentHealth = async (deploymentId: string): Promise<RuntimeHealthSummary> =>
  (await api.get<RuntimeHealthSummary>(`/api/v1/deployments/${encodeURIComponent(deploymentId)}/health`)).data;

export type RuntimeLogSummary = { logs: string; source: "docker" | "archived" };
export const getRuntimeDeploymentLogs = async (deploymentId: string): Promise<RuntimeLogSummary> =>
  (await api.get<RuntimeLogSummary>(`/api/v1/deployments/${encodeURIComponent(deploymentId)}/logs`, { params: { tail: 200 } })).data;
