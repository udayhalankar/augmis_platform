import api from "@/lib/api";


export type AuditScopeType =
  | "personal"
  | "tenant"
  | "platform";


export type AuditEvent = {
  id: string;

  createdAt: string;

  actorUserId:
    string | null;

  tenantId:
    string | null;

  publisherId:
    string | null;

  action: string;

  resourceType:
    string | null;

  resourceId:
    string | null;

  outcome: string;

  message:
    string | null;

  metadata:
    Record<string, unknown> | null;

  requestId:
    string | null;
};


export type AuditPagination = {
  total: number;
  limit: number;
  offset: number;
  returned: number;
};


export type AuditEventsResponse = {
  scope: {
    type: AuditScopeType;

    tenantId?: string;
    tenantName?: string;
  };

  tenant?: {
    id: string;
    name: string;
  };

  pagination:
    AuditPagination;

  items:
    AuditEvent[];
};


export type AuditCategoryOption = {
  key: string;
  label: string;
};


export type AuditActorOption = {
  id: string;
  email: string;

  firstName:
    string | null;

  lastName:
    string | null;
};


export type AuditTenantOption = {
  id: string;
  name: string;
  slug: string;
};


export type AuditPublisherOption = {
  id: string;
  name: string;
  slug: string;
};


export type AuditFilterOptions = {
  categories:
    AuditCategoryOption[];

  actions:
    string[];

  outcomes:
    string[];

  resourceTypes:
    string[];

  actors:
    AuditActorOption[];

  tenants:
    AuditTenantOption[];

  publishers:
    AuditPublisherOption[];
};


export type AuditEventFilters = {
  tenantId?: string;

  publisherId?: string;

  action?: string;

  actionPrefix?: string;

  category?: string;

  outcome?: string;

  resourceType?: string;

  resourceId?: string;

  actorUserId?: string;

  search?: string;

  from?: string;

  to?: string;

  limit?: number;

  offset?: number;
};


function buildAuditParams(
  filters:
    AuditEventFilters
) {

  return {
    tenant_id:
      filters.tenantId ||
      undefined,

    publisher_id:
      filters.publisherId ||
      undefined,

    action:
      filters.action ||
      undefined,

    action_prefix:
      filters.actionPrefix ||
      undefined,

    category:
      filters.category ||
      undefined,

    outcome:
      filters.outcome ||
      undefined,

    resource_type:
      filters.resourceType ||
      undefined,

    resource_id:
      filters.resourceId ||
      undefined,

    actor_user_id:
      filters.actorUserId ||
      undefined,

    search:
      filters.search ||
      undefined,

    from:
      filters.from ||
      undefined,

    to:
      filters.to ||
      undefined,

    limit:
      filters.limit,

    offset:
      filters.offset,
  };
}


export async function loadMyAuditEvents(
  filters:
    AuditEventFilters = {}
): Promise<AuditEventsResponse> {

  const response =
    await api.get<
      AuditEventsResponse
    >(
      "/api/v1/audit-events/me",
      {
        params:
          buildAuditParams({
            ...filters,

            /*
             * Personal scope is server-authoritative.
             * Never allow caller state to choose another actor.
             */
            actorUserId:
              undefined,
          }),
      }
    );

  return response.data;
}


export async function loadTenantAuditEvents(
  tenantId: string,
  filters:
    AuditEventFilters = {}
): Promise<AuditEventsResponse> {

  const response =
    await api.get<
      AuditEventsResponse
    >(
      "/api/v1/audit-events",
      {
        params: {
          ...buildAuditParams(
            filters
          ),

          /*
           * Authoritative tenant for this
           * frontend request.
           *
           * Backend tenant authorization
           * remains the real security boundary.
           */
          tenant_id:
            tenantId,
        },
      }
    );

  return response.data;
}


export async function loadPlatformAuditEvents(
  filters:
    AuditEventFilters = {}
): Promise<AuditEventsResponse> {

  const response =
    await api.get<
      AuditEventsResponse
    >(
      "/api/v1/platform/audit-events",
      {
        params:
          buildAuditParams(
            filters
          ),
      }
    );

  return response.data;
}


export async function loadMyAuditFilterOptions():
Promise<AuditFilterOptions> {

  const response =
    await api.get<
      AuditFilterOptions
    >(
      "/api/v1/audit-events/me/filter-options"
    );

  return response.data;
}


export async function loadTenantAuditFilterOptions(
  tenantId: string
): Promise<AuditFilterOptions> {

  const response =
    await api.get<
      AuditFilterOptions
    >(
      "/api/v1/audit-events/filter-options",
      {
        params: {
          tenant_id:
            tenantId,
        },
      }
    );

  return response.data;
}


export async function loadPlatformAuditFilterOptions():
Promise<AuditFilterOptions> {

  const response =
    await api.get<
      AuditFilterOptions
    >(
      "/api/v1/platform/audit-events/filter-options"
    );

  return response.data;
}