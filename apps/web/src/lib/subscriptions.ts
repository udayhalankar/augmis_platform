import api from "@/lib/api";

export type TenantSubscriptionSummary = {
  id: string;
  status: string;
  startsAt: string | null;
  endsAt: string | null;
  cancelledAt: string | null;
  suspendedAt: string | null;
  resumedAt: string | null;
  suspensionReason: string | null;
  baselineVersionId: string | null;
  versionPolicy: string;
  pinnedVersionId: string | null;
  autoUpgrade: boolean;
  offer: {
    id: string;
    name: string;
    offerKey: string;
  };
  application: {
    id: string;
    name: string;
    appKey: string;
  };
};

export type SubscribeResult = {
  status: string;
  subscriptionId: string;
  tenantId: string;
  offerId: string;
  baselineVersionId: string;
  versionPolicy: string;
  pinnedVersionId: string | null;
  autoUpgrade: boolean;
  application: {
    id: string;
    name: string;
  };
};

export async function subscribeTenantToOffer(
  tenantId: string,
  offerId: string
): Promise<SubscribeResult> {
  const response = await api.post<SubscribeResult>(
    `/api/v1/tenants/${tenantId}/offers/${offerId}/subscribe`
  );
  return response.data;
}

export async function loadTenantSubscriptions(
  tenantId: string
): Promise<TenantSubscriptionSummary[]> {
  const response = await api.get<TenantSubscriptionSummary[]>(
    `/api/v1/tenants/${tenantId}/subscriptions`
  );
  return response.data;
}

export async function suspendTenantSubscription(
  subscriptionId: string,
  reason: string
) {
  const response = await api.post(
    `/api/v1/subscriptions/${subscriptionId}/suspend`,
    { reason }
  );
  return response.data;
}

export async function resumeTenantSubscription(
  subscriptionId: string
) {
  const response = await api.post(
    `/api/v1/subscriptions/${subscriptionId}/resume`
  );
  return response.data;
}

export async function cancelTenantSubscription(
  subscriptionId: string
) {
  const response = await api.post(
    `/api/v1/subscriptions/${subscriptionId}/cancel`
  );
  return response.data;
}
