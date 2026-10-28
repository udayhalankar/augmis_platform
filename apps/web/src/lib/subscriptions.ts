// apps/web/src/lib/subscriptions.ts
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

// The authenticated Marketplace API exposes active offers whose application
// has a published release. Filter by exact application ID for change-offer UX;
// the backend remains authoritative for tenant scope and commercial rules.
export type SubscriptionChangeOfferOption = {
  id: string;
  offerKey: string;
  name: string;
  status: string;
  versionPolicy: string;
  autoUpgrade: boolean;
  application: { id: string; appKey: string; name: string };
  entitlements: Array<{
    code: string;
    value: Record<string, unknown> | null;
  }>;
};

export type SubscriptionChangeOfferResult = {
  status: string;
  subscriptionId: string;
  tenantId: string;
  applicationId: string;
  previousOfferId: string;
  offer: { id: string; offerKey: string; name: string };
  versionPolicy: string;
  baselineVersionId: string;
  pinnedVersionId: string | null;
  autoUpgrade: boolean;
};

export async function loadSubscriptionChangeOffers(
  applicationId: string
): Promise<SubscriptionChangeOfferOption[]> {
  const response = await api.get<SubscriptionChangeOfferOption[]>(
    "/api/v1/marketplace/offers"
  );
  return response.data.filter(
    (offer) =>
      offer.application.id === applicationId &&
      offer.status === "active" &&
      offer.entitlements.some((item) => item.code === "application.deploy")
  );
}

export async function changeTenantSubscriptionOffer(
  subscriptionId: string,
  offerId: string
): Promise<SubscriptionChangeOfferResult> {
  const response = await api.post<SubscriptionChangeOfferResult>(
    `/api/v1/subscriptions/${subscriptionId}/change-offer`,
    { offer_id: offerId }
  );
  return response.data;
}
