import api from "@/lib/api";

export type TenantIdlePolicy = {
  id: string;
  name: string;
  status: string;
  idleMinutes: number;
  overrideMinutes: number | null;
};
export type SessionPolicies = {
  platformDefaultMinutes: number;
  tenants: TenantIdlePolicy[];
  multiTenantRule: string;
};
const BASE = "/api/v1/platform/session-policies";
export async function listSessionPolicies(): Promise<SessionPolicies> {
  return (await api.get<SessionPolicies>(BASE)).data;
}
export async function updateDefaultIdle(minutes: number): Promise<void> {
  await api.put(`${BASE}/default`, { idleMinutes: minutes });
}
export async function updateTenantIdle(id: string, minutes: number): Promise<void> {
  await api.put(`${BASE}/tenants/${encodeURIComponent(id)}`, { idleMinutes: minutes });
}
export async function clearTenantIdle(id: string): Promise<void> {
  await api.delete(`${BASE}/tenants/${encodeURIComponent(id)}`);
}
