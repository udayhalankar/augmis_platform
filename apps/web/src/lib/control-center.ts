import api from "@/lib/api";


type TenantMembership = {
  membershipId: string;
  status: string;

  tenant: {
    id: string;
    name: string;
    slug: string;
  };
};


type PublisherMembership = {
  membershipId: string;
  status: string;

  publisher: {
    id: string;
    name: string;
    slug: string;
  };
};


type ApplicationRecord = {
  id: string;
  publisherId: string;
  appKey: string;
  name: string;
  description?: string | null;
  status: string;
};


type OfferRecord = {
  id: string;
  offerKey: string;
  name: string;
  deliveryType: string;
  status: string;
};


type VersionListResponse = {
  count: number;

  items: Array<{
    id: string;
    version: string;
    status: string;
  }>;
};


type SubscriptionRecord = {
  id: string;
  status: string;
};


type InstanceRecord = {
  id: string;
  name: string;
  status: string;
};


export type AuditEventRecord = {
  id: string;
  createdAt: string;
  actorUserId: string | null;
  action: string;
  resourceType: string;
  resourceId: string | null;
  outcome: string;
  message: string | null;
};


type AuditResponse = {
  items: AuditEventRecord[];
};


type ReadinessResponse = {
  status: string;

  checks: {
    database: {
      ready: boolean;
      error: string | null;
    };

    docker: {
      ready: boolean;
      error: string | null;
    };
  };
};


export type ControlCenterData = {
  counts: {
    applications: number;
    versions: number;

    activeOffers: number;

    activeSubscriptions: number;

    runningInstances: number;
    totalInstances: number;

    tenants: number;
    publishers: number;
  };

  health: {
    api: boolean;
    database: boolean;
    docker: boolean;
    overall: string;
  };

  activity: AuditEventRecord[];

  workspaces: {
    tenants: Array<{
      id: string;
      name: string;
      slug: string;
    }>;

    publishers: Array<{
      id: string;
      name: string;
      slug: string;
    }>;
  };
};


export async function loadControlCenterData():
Promise<ControlCenterData> {

  // =====================================================
  // 1. CURRENT USER CONTEXT
  // =====================================================

  const [
    tenantMembershipResponse,
    publisherMembershipResponse,
    applicationsResponse,
    readinessResponse,
  ] = await Promise.all([

    api.get<TenantMembership[]>(
      "/api/v1/me/tenants"
    ),

    api.get<PublisherMembership[]>(
      "/api/v1/me/publishers"
    ),

    api.get<ApplicationRecord[]>(
      "/api/v1/applications"
    ),

    api.get<ReadinessResponse>(
      "/api/v1/readiness"
    ),
  ]);


  const tenantMemberships =
    tenantMembershipResponse.data.filter(
      (item) =>
        item.status === "active"
    );


  const publisherMemberships =
    publisherMembershipResponse.data.filter(
      (item) =>
        item.status === "active"
    );


  // =====================================================
  // 2. LIMIT APPLICATIONS TO USER'S PUBLISHERS
  // =====================================================

  const publisherIds =
    new Set(
      publisherMemberships.map(
        (item) =>
          item.publisher.id
      )
    );


  const applications =
    applicationsResponse.data.filter(
      (application) =>
        publisherIds.has(
          application.publisherId
        )
    );


  // =====================================================
  // 3. APPLICATION VERSIONS + OFFERS
  // =====================================================

  const [
    versionGroups,
    offerGroups,
  ] = await Promise.all([

    Promise.all(
      applications.map(
        async (application) => {

          const response =
            await api.get<VersionListResponse>(
              `/api/v1/applications/${application.id}/versions`
            );

          return response.data;
        }
      )
    ),

    Promise.all(
      applications.map(
        async (application) => {

          const response =
            await api.get<OfferRecord[]>(
              `/api/v1/applications/${application.id}/offers`
            );

          return response.data;
        }
      )
    ),
  ]);


  const versionCount =
    versionGroups.reduce(
      (
        total,
        group
      ) =>
        total + group.count,
      0
    );


  const activeOfferCount =
    offerGroups
      .flat()
      .filter(
        (offer) =>
          offer.status === "active"
      )
      .length;


  // =====================================================
  // 4. TENANT COMMERCIAL + RUNTIME DATA
  // =====================================================

  const tenantData =
    await Promise.all(

      tenantMemberships.map(
        async (membership) => {

          const tenantId =
            membership.tenant.id;


          const [
            subscriptionResponse,
            instanceResponse,
            auditEvents,
          ] = await Promise.all([

            api.get<SubscriptionRecord[]>(
              `/api/v1/tenants/${tenantId}/subscriptions`
            ),

            api.get<InstanceRecord[]>(
              `/api/v1/tenants/${tenantId}/instances`
            ),

            api.get<AuditResponse>(
              `/api/v1/audit-events?tenant_id=${tenantId}&limit=10`
            )
              .then(
                (response) =>
                  response.data.items
              )
              .catch(
                () =>
                  [] as AuditEventRecord[]
              ),
          ]);


          return {
            subscriptions:
              subscriptionResponse.data,

            instances:
              instanceResponse.data,

            auditEvents,
          };
        }
      )
    );


  // =====================================================
  // 5. AGGREGATE SUBSCRIPTIONS
  // =====================================================

  const subscriptions =
    tenantData.flatMap(
      (item) =>
        item.subscriptions
    );


  const activeSubscriptions =
    subscriptions.filter(
      (subscription) =>
        subscription.status === "active"
    ).length;


  // =====================================================
  // 6. AGGREGATE INSTANCES
  // =====================================================

  const instances =
    tenantData.flatMap(
      (item) =>
        item.instances
    );


  const runningInstances =
    instances.filter(
      (instance) =>
        instance.status === "running"
    ).length;


  // =====================================================
  // 7. AGGREGATE AUDIT EVENTS
  // =====================================================

  const activity =
    tenantData
      .flatMap(
        (item) =>
          item.auditEvents
      )
      .sort(
        (left, right) =>
          new Date(
            right.createdAt
          ).getTime()
          -
          new Date(
            left.createdAt
          ).getTime()
      )
      .slice(
        0,
        8
      );


  // =====================================================
  // 8. RETURN CONTROL CENTER VIEW MODEL
  // =====================================================

  return {
    counts: {
      applications:
        applications.length,

      versions:
        versionCount,

      activeOffers:
        activeOfferCount,

      activeSubscriptions,

      runningInstances,

      totalInstances:
        instances.length,

      tenants:
        tenantMemberships.length,

      publishers:
        publisherMemberships.length,
    },

    health: {
      api: true,

      database:
        readinessResponse
          .data
          .checks
          .database
          .ready,

      docker:
        readinessResponse
          .data
          .checks
          .docker
          .ready,

      overall:
        readinessResponse
          .data
          .status,
    },

    activity,

    workspaces: {
      tenants:
        tenantMemberships.map(
          (item) =>
            item.tenant
        ),

      publishers:
        publisherMemberships.map(
          (item) =>
            item.publisher
        ),
    },
  };
}