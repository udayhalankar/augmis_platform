import api from "@/lib/api";


export type MarketplaceEntitlement = {
  code: string;
  value: Record<string, unknown> | null;
};


export type MarketplaceVersion = {
  id: string;
  version: string;
  buildType: string;
  deploymentMode: string;
  status: string;
};


export type MarketplaceApplication = {
  id: string;
  appKey: string;
  name: string;
  description: string | null;
  status: string;
};


export type MarketplaceOffer = {
  id: string;
  offerKey: string;
  name: string;
  description: string | null;
  deliveryType: string;
  status: string;
  versionPolicy: string;
  autoUpgrade: boolean;

  application: MarketplaceApplication;

  version: MarketplaceVersion;

  entitlements: MarketplaceEntitlement[];
};


export async function loadMarketplaceOffers():
Promise<MarketplaceOffer[]> {

  const response =
    await api.get<MarketplaceOffer[]>(
      "/api/v1/marketplace/offers"
    );

  return response.data;
}
