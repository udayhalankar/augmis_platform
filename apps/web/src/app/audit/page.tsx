"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import axios from "axios";

import {
  Alert,
  Box,
  Button,
  ButtonGroup,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  InputAdornment,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";

import CheckCircleOutlineOutlined
  from "@mui/icons-material/CheckCircleOutlineOutlined";

import ErrorOutlineOutlined
  from "@mui/icons-material/ErrorOutlineOutlined";

import FilterAltOffOutlined
  from "@mui/icons-material/FilterAltOffOutlined";

import HistoryOutlined
  from "@mui/icons-material/HistoryOutlined";

import PeopleOutlined
  from "@mui/icons-material/PeopleOutlined";

import RefreshOutlined
  from "@mui/icons-material/RefreshOutlined";

import SearchOutlined
  from "@mui/icons-material/SearchOutlined";

import VisibilityOutlined
  from "@mui/icons-material/VisibilityOutlined";

import AppShell
  from "@/components/app-shell";

import ProtectedRoute
  from "@/components/protected-route";

import {
  usePermissions,
} from "@/context/permission-context";

import {
  useTenant,
} from "@/context/tenant-context";

import {
  AuditEvent,
  AuditEventFilters,
  AuditFilterOptions,
  AuditScopeType,
  loadMyAuditEvents,
  loadMyAuditFilterOptions,
  loadPlatformAuditEvents,
  loadPlatformAuditFilterOptions,
  loadTenantAuditEvents,
  loadTenantAuditFilterOptions,
} from "@/lib/audit";


type FilterDraft = {
  search: string;
  category: string;
  action: string;
  actionPrefix: string;
  outcome: string;
  actorUserId: string;
  resourceType: string;
  resourceId: string;
  tenantId: string;
  publisherId: string;
  fromDate: string;
  toDate: string;
};


type AuditSummary = {
  total: number;
  success: number;
  failed: number;
};


const EMPTY_FILTERS:
FilterDraft = {
  search: "",
  category: "",
  action: "",
  actionPrefix: "",
  outcome: "",
  actorUserId: "",
  resourceType: "",
  resourceId: "",
  tenantId: "",
  publisherId: "",
  fromDate: "",
  toDate: "",
};


const EMPTY_OPTIONS:
AuditFilterOptions = {
  categories: [],
  actions: [],
  outcomes: [],
  resourceTypes: [],
  actors: [],
  tenants: [],
  publishers: [],
};


function apiError(
  error: unknown,
  fallback: string
): string {

  if (
    axios.isAxiosError(
      error
    )
  ) {

    const detail =
      error.response
        ?.data
        ?.detail;

    if (
      typeof detail ===
      "string"
    ) {

      return detail;
    }
  }

  if (
    error instanceof Error
  ) {

    return error.message;
  }

  return fallback;
}


function startOfDayIso(
  value: string
): string | undefined {

  if (!value) {
    return undefined;
  }

  return new Date(
    `${value}T00:00:00`
  ).toISOString();
}


function endOfDayIso(
  value: string
): string | undefined {

  if (!value) {
    return undefined;
  }

  return new Date(
    `${value}T23:59:59.999`
  ).toISOString();
}


function toApiFilters(
  draft: FilterDraft
): AuditEventFilters {

  return {
    search:
      draft.search.trim() ||
      undefined,

    category:
      draft.category ||
      undefined,

    action:
      draft.action ||
      undefined,

    actionPrefix:
      draft.actionPrefix.trim() ||
      undefined,

    outcome:
      draft.outcome ||
      undefined,

    actorUserId:
      draft.actorUserId ||
      undefined,

    resourceType:
      draft.resourceType ||
      undefined,

    resourceId:
      draft.resourceId.trim() ||
      undefined,

    tenantId:
      draft.tenantId ||
      undefined,

    publisherId:
      draft.publisherId ||
      undefined,

    from:
      startOfDayIso(
        draft.fromDate
      ),

    to:
      endOfDayIso(
        draft.toDate
      ),
  };
}


function formatDateTime(
  value: string
): string {

  const date =
    new Date(value);

  if (
    Number.isNaN(
      date.getTime()
    )
  ) {

    return value;
  }

  return date.toLocaleString();
}


function outcomeColor(
  outcome: string
):
  | "success"
  | "error"
  | "warning"
  | "default" {

  const normalized =
    outcome.toLowerCase();

  if (
    normalized === "success"
  ) {

    return "success";
  }

  if (
    normalized === "failed" ||
    normalized === "failure" ||
    normalized === "denied"
  ) {

    return "error";
  }

  if (
    normalized === "warning" ||
    normalized === "delayed"
  ) {

    return "warning";
  }

  return "default";
}

function metadataLabel(
  key: string
): string {

  return key
    .replace(
      /([a-z0-9])([A-Z])/g,
      "$1 $2"
    )
    .replace(
      /[_-]+/g,
      " "
    )
    .replace(
      /\b\w/g,
      (
        character
      ) =>
        character.toUpperCase()
    );
}


function metadataValue(
  value: unknown
): string {

  if (
    value === null ||
    value === undefined ||
    value === ""
  ) {

    return "—";
  }

  if (
    Array.isArray(
      value
    )
  ) {

    return value
      .map(
        (
          item
        ) =>
          typeof item ===
          "object"
            ? JSON.stringify(
                item
              )
            : String(
                item
              )
      )
      .join(", ");
  }

  if (
    typeof value ===
    "object"
  ) {

    return Object.entries(
      value as Record<
        string,
        unknown
      >
    )
      .map(
        (
          [
            childKey,
            childValue,
          ]
        ) =>
          `${metadataLabel(
            childKey
          )}: ${metadataValue(
            childValue
          )}`
      )
      .join(" · ");
  }

  return String(
    value
  );
}

function AuditMetric({
  label,
  value,
  icon,
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
}) {

  return (
    <Paper
      variant="outlined"
      sx={{
        px: 2,
        py: 1.75,
        minHeight: 92,
        display: "flex",
        alignItems: "center",
        gap: 1.75,
      }}
    >
      <Box
        sx={{
          width: 38,
          height: 38,
          border: "1px solid",
          borderColor: "divider",
          display: "grid",
          placeItems: "center",
          color: "primary.main",
          bgcolor: "#f8fafc",
        }}
      >
        {icon}
      </Box>

      <Box>
        <Typography
          variant="caption"
          sx={{
            color:
              "text.secondary",
            textTransform:
              "uppercase",
            letterSpacing:
              "0.08em",
            fontWeight: 600,
          }}
        >
          {label}
        </Typography>

        <Typography
          variant="h5"
          sx={{
            mt: 0.25,
            fontWeight: 600,
          }}
        >
          {value.toLocaleString()}
        </Typography>
      </Box>
    </Paper>
  );
}


export default function AuditPage() {

  const {
    selectedTenant,
    selectedTenantId,
    loading:
      tenantContextLoading,
  } = useTenant();


  const {
    platformLoading,
    tenantLoading,
    hasPlatformPermission,
    hasTenantPermission,
  } = usePermissions();


  const canPlatformAudit =
    hasPlatformPermission(
      "platform.audit.view"
    );


  const canTenantAudit =
    Boolean(
      selectedTenantId
    ) &&
    hasTenantPermission(
      "audit.view"
    );


  const [
    scope,
    setScope,
  ] =
    useState<AuditScopeType>(
      "platform"
    );


  const [
    filters,
    setFilters,
  ] =
    useState<FilterDraft>({
      ...EMPTY_FILTERS,
    });


  const [
    appliedFilters,
    setAppliedFilters,
  ] =
    useState<FilterDraft>({
      ...EMPTY_FILTERS,
    });


  const [
    filterOptions,
    setFilterOptions,
  ] =
    useState<AuditFilterOptions>(
      EMPTY_OPTIONS
    );


  const [
    events,
    setEvents,
  ] =
    useState<AuditEvent[]>([]);


  const [
    total,
    setTotal,
  ] =
    useState(0);


  const [
    summary,
    setSummary,
  ] =
    useState<AuditSummary>({
      total: 0,
      success: 0,
      failed: 0,
    });


  const [
    page,
    setPage,
  ] =
    useState(0);


  const [
    rowsPerPage,
    setRowsPerPage,
  ] =
    useState(25);


  const [
    loading,
    setLoading,
  ] =
    useState(false);


  const [
    optionsLoading,
    setOptionsLoading,
  ] =
    useState(false);


  const [
    error,
    setError,
  ] =
    useState("");


  const [
    selectedEvent,
    setSelectedEvent,
  ] =
    useState<AuditEvent | null>(
      null
    );


  const permissionLoading =
    platformLoading ||
    tenantLoading ||
    tenantContextLoading;


  /*
   * ----------------------------------------------------------
   * Keep privileged scopes fail-closed.
   *
   * Personal scope is always available to an authenticated
   * user. If tenant/platform permission disappears while this
   * page is open, return to personal scope.
   * ----------------------------------------------------------
   */

  useEffect(
    () => {

      if (
        permissionLoading
      ) {

        return;
      }

      if (
        scope === "platform" &&
        !canPlatformAudit
      ) {

        setScope(
          canTenantAudit
            ? "tenant"
            : "personal"
        );

        return;
      }

      if (
        scope === "tenant" &&
        !canTenantAudit
      ) {

        setScope(
          "personal"
        );
      }

    },
    [
      permissionLoading,
      scope,
      canPlatformAudit,
      canTenantAudit,
    ]
  );


  /*
   * ----------------------------------------------------------
   * Lookup maps
   * ----------------------------------------------------------
   */

  const actionPrefixOptions =
  useMemo(
    () => {

      const prefixes =
        new Set<string>();

      for (
        const action of
        filterOptions.actions
      ) {

        const parts =
          action.split(".");

        if (
          parts.length >= 3
        ) {

          prefixes.add(
            `${parts[0]}.${parts[1]}.`
          );

        } else if (
          parts.length >= 1
        ) {

          prefixes.add(
            `${parts[0]}.`
          );
        }
      }

      return Array.from(
        prefixes
      ).sort();

    },
    [
      filterOptions.actions,
    ]
  );



  const actorMap =
    useMemo(
      () =>
        new Map(
          filterOptions.actors.map(
            (actor) => [
              actor.id,
              actor,
            ]
          )
        ),
      [
        filterOptions.actors,
      ]
    );


  const tenantMap =
    useMemo(
      () =>
        new Map(
          filterOptions.tenants.map(
            (tenant) => [
              tenant.id,
              tenant,
            ]
          )
        ),
      [
        filterOptions.tenants,
      ]
    );


  const publisherMap =
    useMemo(
      () =>
        new Map(
          filterOptions.publishers.map(
            (publisher) => [
              publisher.id,
              publisher,
            ]
          )
        ),
      [
        filterOptions.publishers,
      ]
    );


  const actorLabel =
    useCallback(
      (
        actorUserId:
          string | null
      ) => {

        if (!actorUserId) {

          return "System / Provider";
        }

        const actor =
          actorMap.get(
            actorUserId
          );

        if (!actor) {

          return actorUserId;
        }

        const fullName =
          [
            actor.firstName,
            actor.lastName,
          ]
            .filter(Boolean)
            .join(" ");

        return fullName
          ? `${fullName} · ${actor.email}`
          : actor.email;
      },
      [
        actorMap,
      ]
    );


  const tenantLabel =
    useCallback(
      (
        tenantId:
          string | null
      ) => {

        if (!tenantId) {

          return "Platform";
        }

        const tenant =
          tenantMap.get(
            tenantId
          );

        if (tenant) {

          return tenant.name;
        }

        if (
          selectedTenant
            ?.tenant
            ?.id ===
          tenantId
        ) {

          return selectedTenant
            .tenant
            .name;
        }

        return tenantId;
      },
      [
        tenantMap,
        selectedTenant,
      ]
    );


  /*
   * ----------------------------------------------------------
   * Data loaders
   * ----------------------------------------------------------
   */

  const runAuditQuery =
    useCallback(
      async (
        requestFilters:
          AuditEventFilters
      ) => {

        if (
          scope === "personal"
        ) {

          return loadMyAuditEvents(
            requestFilters
          );
        }

        if (
          scope === "platform"
        ) {

          return loadPlatformAuditEvents(
            requestFilters
          );
        }

        if (
          !selectedTenantId
        ) {

          throw new Error(
            "No tenant is selected."
          );
        }

        return loadTenantAuditEvents(
          selectedTenantId,
          requestFilters
        );
      },
      [
        scope,
        selectedTenantId,
      ]
    );


  const loadOptions =
    useCallback(
      async () => {

        if (
          permissionLoading
        ) {

          return;
        }

        if (
          scope === "platform" &&
          !canPlatformAudit
        ) {

          setFilterOptions(
            EMPTY_OPTIONS
          );

          return;
        }

        if (
          scope === "tenant" &&
          (
            !canTenantAudit ||
            !selectedTenantId
          )
        ) {

          setFilterOptions(
            EMPTY_OPTIONS
          );

          return;
        }

        setOptionsLoading(
          true
        );

        try {

          let result:
            AuditFilterOptions;

          if (
            scope === "personal"
          ) {

            result =
              await loadMyAuditFilterOptions();

          } else if (
            scope === "platform"
          ) {

            result =
              await loadPlatformAuditFilterOptions();

          } else {

            result =
              await loadTenantAuditFilterOptions(
                selectedTenantId
              );
          }

          setFilterOptions(
            result
          );

        } catch (
          loadError
        ) {

          setError(
            apiError(
              loadError,
              "Audit filter options could not be loaded."
            )
          );

        } finally {

          setOptionsLoading(
            false
          );
        }

      },
      [
        permissionLoading,
        scope,
        canPlatformAudit,
        canTenantAudit,
        selectedTenantId,
      ]
    );


  const loadEvents =
    useCallback(
      async () => {

        if (
          permissionLoading
        ) {

          return;
        }

        if (
          scope === "platform" &&
          !canPlatformAudit
        ) {

          return;
        }

        if (
          scope === "tenant" &&
          (
            !canTenantAudit ||
            !selectedTenantId
          )
        ) {

          return;
        }

        setLoading(
          true
        );

        setError(
          ""
        );

        try {

          const baseFilters =
            toApiFilters(
              appliedFilters
            );

          const mainFilters:
          AuditEventFilters = {
            ...baseFilters,

            limit:
              rowsPerPage,

            offset:
              page *
              rowsPerPage,
          };


          /*
           * Summary cards deliberately ignore
           * the selected outcome while retaining
           * all other active filters.
           */

          const summaryBase:
          AuditEventFilters = {
            ...baseFilters,

            outcome:
              undefined,

            limit:
              1,

            offset:
              0,
          };


          const [
            mainResult,
            totalResult,
            successResult,
            failedResult,
          ] =
            await Promise.all([
              runAuditQuery(
                mainFilters
              ),

              runAuditQuery(
                summaryBase
              ),

              runAuditQuery({
                ...summaryBase,
                outcome:
                  "success",
              }),

              runAuditQuery({
                ...summaryBase,
                outcome:
                  "failed",
              }),
            ]);


          setEvents(
            mainResult.items
          );

          setTotal(
            mainResult.pagination
              .total
          );

          setSummary({
            total:
              totalResult
                .pagination
                .total,

            success:
              successResult
                .pagination
                .total,

            failed:
              failedResult
                .pagination
                .total,
          });

        } catch (
          loadError
        ) {

          setEvents(
            []
          );

          setTotal(
            0
          );

          setSummary({
            total: 0,
            success: 0,
            failed: 0,
          });

          setError(
            apiError(
              loadError,
              "Audit events could not be loaded."
            )
          );

        } finally {

          setLoading(
            false
          );
        }

      },
      [
        permissionLoading,
        scope,
        canPlatformAudit,
        canTenantAudit,
        selectedTenantId,
        appliedFilters,
        rowsPerPage,
        page,
        runAuditQuery,
      ]
    );


  useEffect(
    () => {

      void loadOptions();

    },
    [
      loadOptions,
    ]
  );


  useEffect(
    () => {

      void loadEvents();

    },
    [
      loadEvents,
    ]
  );


  /*
   * ----------------------------------------------------------
   * Actions
   * ----------------------------------------------------------
   */

  const changeScope =
    (
      nextScope:
        AuditScopeType
    ) => {

      if (
        nextScope ===
          "platform" &&
        !canPlatformAudit
      ) {

        return;
      }

      if (
        nextScope ===
          "tenant" &&
        !canTenantAudit
      ) {

        return;
      }

      setScope(
        nextScope
      );

      setFilters({
        ...EMPTY_FILTERS,
      });

      setAppliedFilters({
        ...EMPTY_FILTERS,
      });

      setPage(
        0
      );

      setSelectedEvent(
        null
      );
    };


  const applyFilters =
    () => {

      setAppliedFilters({
        ...filters,
      });

      setPage(
        0
      );
    };


  const resetFilters =
    () => {

      setFilters({
        ...EMPTY_FILTERS,
      });

      setAppliedFilters({
        ...EMPTY_FILTERS,
      });

      setPage(
        0
      );
    };


  const refresh =
    async () => {

      await Promise.all([
        loadOptions(),
        loadEvents(),
      ]);
    };


  /*
   * ----------------------------------------------------------
   * Render
   * ----------------------------------------------------------
   */

  return (
    <ProtectedRoute>
      <AppShell>

        <Stack
          spacing={2.25}
        >

          {/* PAGE HEADER */}

          <Stack
            direction={{
              xs: "column",
              md: "row",
            }}
            spacing={2}
            sx={{
              justifyContent:
                "space-between",

              alignItems: {
                xs: "stretch",
                md: "flex-start",
              },
            }}
          >
            <Box>
              <Typography
                variant="caption"
                sx={{
                  color:
                    "text.secondary",
                  textTransform:
                    "uppercase",
                  letterSpacing:
                    "0.12em",
                  fontWeight: 600,
                }}
              >
                Audit & Governance
              </Typography>

              <Typography
                variant="h4"
                sx={{
                  mt: 0.25,
                }}
              >
                Audit Center
              </Typography>

              <Typography
                variant="body2"
                sx={{
                  mt: 0.5,
                  color:
                    "text.secondary",
                  maxWidth: 760,
                }}
              >
                Search and investigate
                administrative, security,
                configuration and runtime
                events recorded by the
                AUGMIS control plane.
              </Typography>
            </Box>


            <Stack
              direction="row"
              spacing={1}
            >
              <Button
                variant="outlined"
                startIcon={
                  <RefreshOutlined />
                }
                disabled={
                  loading ||
                  optionsLoading
                }
                onClick={
                  refresh
                }
              >
                Refresh
              </Button>
            </Stack>
          </Stack>


          {permissionLoading && (
            <Paper
              variant="outlined"
              sx={{
                minHeight: 180,
                display: "grid",
                placeItems: "center",
              }}
            >
              <CircularProgress
                size={28}
              />
            </Paper>
          )}


          {!permissionLoading && (
            <>

              {/* SCOPE BAR */}

              <Paper
                variant="outlined"
                sx={{
                  px: 2,
                  py: 1.5,
                }}
              >
                <Stack
                  direction={{
                    xs: "column",
                    sm: "row",
                  }}
                  spacing={1.5}
                  sx={{
                    justifyContent:
                      "space-between",

                    alignItems: {
                      xs: "stretch",
                      sm: "center",
                    },
                  }}
                >
                  <Box>
                    <Typography
                      variant="caption"
                      sx={{
                        color:
                          "text.secondary",
                        textTransform:
                          "uppercase",
                        letterSpacing:
                          "0.08em",
                      }}
                    >
                      Audit Scope
                    </Typography>

                    <Typography
                      variant="body2"
                      sx={{
                        mt: 0.25,
                        fontWeight: 600,
                      }}
                    >
                      {scope ===
                      "personal"
                        ? "My activity only"
                        : scope ===
                          "platform"
                          ? "Platform-wide governance view"
                          : selectedTenant
                            ? `${selectedTenant.tenant.name} · ${selectedTenant.tenant.slug}`
                            : "Current tenant"}
                    </Typography>
                  </Box>


                  <ButtonGroup
                    size="small"
                    variant="outlined"
                  >
                    <Button
                      variant={
                        scope ===
                        "personal"
                          ? "contained"
                          : "outlined"
                      }
                      onClick={() =>
                        changeScope(
                          "personal"
                        )
                      }
                    >
                      My Activity
                    </Button>

                    {canTenantAudit && (
                      <Button
                        variant={
                          scope ===
                          "tenant"
                            ? "contained"
                            : "outlined"
                        }
                        onClick={() =>
                          changeScope(
                            "tenant"
                          )
                        }
                      >
                        Tenant
                      </Button>
                    )}

                    {canPlatformAudit && (
                      <Button
                        variant={
                          scope ===
                          "platform"
                            ? "contained"
                            : "outlined"
                        }
                        onClick={() =>
                          changeScope(
                            "platform"
                          )
                        }
                      >
                        Platform
                      </Button>
                    )}
                  </ButtonGroup>
                </Stack>
              </Paper>


              {error && (
                <Alert
                  severity="error"
                >
                  {error}
                </Alert>
              )}


              {/* KPI ROW */}

              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: {
                    xs:
                      "1fr",
                    sm:
                      "repeat(2, minmax(0, 1fr))",
                    lg:
                      "repeat(4, minmax(0, 1fr))",
                  },
                  gap: 1.5,
                }}
              >
                <AuditMetric
                  label="Total Events"
                  value={
                    summary.total
                  }
                  icon={
                    <HistoryOutlined
                      fontSize="small"
                    />
                  }
                />

                <AuditMetric
                  label="Success"
                  value={
                    summary.success
                  }
                  icon={
                    <CheckCircleOutlineOutlined
                      fontSize="small"
                    />
                  }
                />

                <AuditMetric
                  label="Failed"
                  value={
                    summary.failed
                  }
                  icon={
                    <ErrorOutlineOutlined
                      fontSize="small"
                    />
                  }
                />

                <AuditMetric
                  label="Known Actors"
                  value={
                    filterOptions
                      .actors
                      .length
                  }
                  icon={
                    <PeopleOutlined
                      fontSize="small"
                    />
                  }
                />
              </Box>


              {/* FILTERS */}

              <Paper
                variant="outlined"
                sx={{
                  p: 2,
                }}
              >
                <Stack
                  direction={{
                    xs: "column",
                    lg: "row",
                  }}
                  spacing={1}
                  sx={{
                    mb: 1.75,

                    justifyContent:
                      "space-between",

                    alignItems: {
                      xs: "stretch",
                      lg: "center",
                    },
                  }}
                >
                  <Box>
                    <Typography
                      variant="h6"
                    >
                      Filters
                    </Typography>

                    <Typography
                      variant="caption"
                      color=
                        "text.secondary"
                    >
                      Narrow the evidence
                      set before opening
                      individual events.
                    </Typography>
                  </Box>

                  <Stack
                    direction="row"
                    spacing={1}
                  >
                    <Button
                      size="small"
                      variant="text"
                      startIcon={
                        <FilterAltOffOutlined />
                      }
                      onClick={
                        resetFilters
                      }
                    >
                      Reset
                    </Button>

                    <Button
                      size="small"
                      variant="contained"
                      startIcon={
                        <SearchOutlined />
                      }
                      onClick={
                        applyFilters
                      }
                    >
                      Apply Filters
                    </Button>
                  </Stack>
                </Stack>


                <Box
                  sx={{
                    display: "grid",
                    gridTemplateColumns: {
                      xs:
                        "1fr",

                      md:
                        "repeat(2, minmax(0, 1fr))",

                      xl:
                        "repeat(4, minmax(0, 1fr))",
                    },
                    gap: 1.5,
                  }}
                >

                  <TextField
                    size="small"
                    label="Search"
                    value={
                      filters.search
                    }
                    onChange={
                      (event) =>
                        setFilters(
                          (
                            current
                          ) => ({
                            ...current,

                            search:
                              event
                                .target
                                .value,
                          })
                        )
                    }
                    onKeyDown={
                      (event) => {

                        if (
                          event.key ===
                          "Enter"
                        ) {

                          applyFilters();
                        }
                      }
                    }
                    slotProps={{
                      input: {
                        startAdornment: (
                          <InputAdornment
                            position="start"
                          >
                            <SearchOutlined
                              fontSize="small"
                            />
                          </InputAdornment>
                        ),
                      },
                    }}
                  />


                  <TextField
                    select
                    size="small"
                    label="Category"
                    value={
                      filters.category
                    }
                    onChange={
                      (event) =>
                        setFilters(
                          (
                            current
                          ) => ({
                            ...current,

                            category:
                              event
                                .target
                                .value,
                          })
                        )
                    }
                  >
                    <MenuItem
                      value=""
                    >
                      All categories
                    </MenuItem>

                    {filterOptions
                      .categories
                      .map(
                        (
                          category
                        ) => (
                          <MenuItem
                            key={
                              category.key
                            }
                            value={
                              category.key
                            }
                          >
                            {
                              category.label
                            }
                          </MenuItem>
                        )
                      )}
                  </TextField>


                  <TextField
                    select
                    size="small"
                    label="Action"
                    value={
                      filters.action
                    }
                    onChange={
                      (event) =>
                        setFilters(
                          (
                            current
                          ) => ({
                            ...current,

                            action:
                              event
                                .target
                                .value,
                          })
                        )
                    }
                  >
                    <MenuItem
                      value=""
                    >
                      All actions
                    </MenuItem>

                    {filterOptions
                      .actions
                      .map(
                        (
                          action
                        ) => (
                          <MenuItem
                            key={
                              action
                            }
                            value={
                              action
                            }
                          >
                            {action}
                          </MenuItem>
                        )
                      )}
                  </TextField>


                  <TextField
                      select
                      size="small"
                      label="Action prefix"
                      value={
                        filters.actionPrefix
                      }
                      onChange={
                        (event) =>
                          setFilters(
                            (
                              current
                            ) => ({
                              ...current,

                              actionPrefix:
                                event
                                  .target
                                  .value,
                            })
                          )
                      }
                    >
                      <MenuItem
                        value=""
                      >
                        All prefixes
                      </MenuItem>

                      {actionPrefixOptions.map(
                        (
                          prefix
                        ) => (
                          <MenuItem
                            key={
                              prefix
                            }
                            value={
                              prefix
                            }
                          >
                            {prefix}
                          </MenuItem>
                        )
                      )}
                    </TextField>


                  <TextField
                    select
                    size="small"
                    label="Outcome"
                    value={
                      filters.outcome
                    }
                    onChange={
                      (event) =>
                        setFilters(
                          (
                            current
                          ) => ({
                            ...current,

                            outcome:
                              event
                                .target
                                .value,
                          })
                        )
                    }
                  >
                    <MenuItem
                      value=""
                    >
                      All outcomes
                    </MenuItem>

                    {filterOptions
                      .outcomes
                      .map(
                        (
                          outcome
                        ) => (
                          <MenuItem
                            key={
                              outcome
                            }
                            value={
                              outcome
                            }
                          >
                            {outcome}
                          </MenuItem>
                        )
                      )}
                  </TextField>


                  {scope !==
                    "personal" && (
                    <TextField
                    select
                    size="small"
                    label="Actor"
                    value={
                      filters
                        .actorUserId
                    }
                    onChange={
                      (event) =>
                        setFilters(
                          (
                            current
                          ) => ({
                            ...current,

                            actorUserId:
                              event
                                .target
                                .value,
                          })
                        )
                    }
                  >
                    <MenuItem
                      value=""
                    >
                      All actors
                    </MenuItem>

                    {filterOptions
                      .actors
                      .map(
                        (
                          actor
                        ) => {

                          const name =
                            [
                              actor.firstName,
                              actor.lastName,
                            ]
                              .filter(
                                Boolean
                              )
                              .join(
                                " "
                              );

                          return (
                            <MenuItem
                              key={
                                actor.id
                              }
                              value={
                                actor.id
                              }
                            >
                              {name
                                ? `${name} · ${actor.email}`
                                : actor.email}
                            </MenuItem>
                          );
                        }
                      )}
                  </TextField>


                  )}


                  <TextField
                    select
                    size="small"
                    label="Resource type"
                    value={
                      filters
                        .resourceType
                    }
                    onChange={
                      (event) =>
                        setFilters(
                          (
                            current
                          ) => ({
                            ...current,

                            resourceType:
                              event
                                .target
                                .value,
                          })
                        )
                    }
                  >
                    <MenuItem
                      value=""
                    >
                      All resource types
                    </MenuItem>

                    {filterOptions
                      .resourceTypes
                      .map(
                        (
                          resourceType
                        ) => (
                          <MenuItem
                            key={
                              resourceType
                            }
                            value={
                              resourceType
                            }
                          >
                            {
                              resourceType
                            }
                          </MenuItem>
                        )
                      )}
                  </TextField>


                  <TextField
                    size="small"
                    label="Resource ID"
                    value={
                      filters
                        .resourceId
                    }
                    onChange={
                      (event) =>
                        setFilters(
                          (
                            current
                          ) => ({
                            ...current,

                            resourceId:
                              event
                                .target
                                .value,
                          })
                        )
                    }
                  />


                  {scope ===
                    "platform" && (
                    <TextField
                      select
                      size="small"
                      label="Tenant"
                      value={
                        filters
                          .tenantId
                      }
                      onChange={
                        (event) =>
                          setFilters(
                            (
                              current
                            ) => ({
                              ...current,

                              tenantId:
                                event
                                  .target
                                  .value,
                            })
                          )
                      }
                    >
                      <MenuItem
                        value=""
                      >
                        All tenants
                      </MenuItem>

                      {filterOptions
                        .tenants
                        .map(
                          (
                            tenant
                          ) => (
                            <MenuItem
                              key={
                                tenant.id
                              }
                              value={
                                tenant.id
                              }
                            >
                              {
                                tenant.name
                              }
                            </MenuItem>
                          )
                        )}
                    </TextField>
                  )}


                  {scope ===
                    "platform" && (
                    <TextField
                      select
                      size="small"
                      label="Publisher"
                      value={
                        filters
                          .publisherId
                      }
                      onChange={
                        (event) =>
                          setFilters(
                            (
                              current
                            ) => ({
                              ...current,

                              publisherId:
                                event
                                  .target
                                  .value,
                            })
                          )
                      }
                    >
                      <MenuItem
                        value=""
                      >
                        All publishers
                      </MenuItem>

                      {filterOptions
                        .publishers
                        .map(
                          (
                            publisher
                          ) => (
                            <MenuItem
                              key={
                                publisher.id
                              }
                              value={
                                publisher.id
                              }
                            >
                              {
                                publisher.name
                              }
                            </MenuItem>
                          )
                        )}
                    </TextField>
                  )}


                  <TextField
                    size="small"
                    type="date"
                    label="From"
                    value={
                      filters.fromDate
                    }
                    onChange={
                      (event) =>
                        setFilters(
                          (
                            current
                          ) => ({
                            ...current,

                            fromDate:
                              event
                                .target
                                .value,
                          })
                        )
                    }
                    slotProps={{
                      inputLabel: {
                        shrink: true,
                      },
                    }}
                  />


                  <TextField
                    size="small"
                    type="date"
                    label="To"
                    value={
                      filters.toDate
                    }
                    onChange={
                      (event) =>
                        setFilters(
                          (
                            current
                          ) => ({
                            ...current,

                            toDate:
                              event
                                .target
                                .value,
                          })
                        )
                    }
                    slotProps={{
                        inputLabel: {
                          shrink: true,
                        },
                      }}
                  />
                </Box>
              </Paper>


              {/* EVENT TABLE */}

              <Paper
                variant="outlined"
              >
                <Box
                  sx={{
                    px: 2,
                    py: 1.5,
                    borderBottom:
                      "1px solid",
                    borderColor:
                      "divider",
                  }}
                >
                  <Stack
                        direction={{
                          xs: "column",
                          sm: "row",
                        }}
                        spacing={0.5}
                        sx={{
                          justifyContent:
                            "space-between",

                          alignItems: {
                            xs: "flex-start",
                            sm: "center",
                          },
                        }}
                      >
                    <Box>
                      <Typography
                        variant="h6"
                      >
                        Audit Events
                      </Typography>

                      <Typography
                        variant="caption"
                        color=
                          "text.secondary"
                      >
                        {total
                          .toLocaleString()}
                        {" "}
                        matching events
                      </Typography>
                    </Box>

                    {optionsLoading && (
                      <Typography
                        variant="caption"
                        color=
                          "text.secondary"
                      >
                        Refreshing filter
                        catalogue…
                      </Typography>
                    )}
                  </Stack>
                </Box>


                {loading ? (
                  <Box
                    sx={{
                      minHeight: 260,
                      display: "grid",
                      placeItems:
                        "center",
                    }}
                  >
                    <CircularProgress
                      size={28}
                    />
                  </Box>
                ) : events.length ===
                  0 ? (
                  <Box
                    sx={{
                      minHeight: 220,
                      display: "grid",
                      placeItems:
                        "center",
                      px: 2,
                    }}
                  >
                    <Box
                      sx={{
                        textAlign:
                          "center",
                      }}
                    >
                      <HistoryOutlined
                        sx={{
                          fontSize: 34,
                          color:
                            "text.disabled",
                        }}
                      />

                      <Typography
                        variant="body1"
                        sx={{
                          mt: 1,
                          fontWeight: 600,
                        }}
                      >
                        No audit events
                        found
                      </Typography>

                      <Typography
                        variant="body2"
                        color=
                          "text.secondary"
                      >
                        Change the filters
                        or refresh the
                        audit trail.
                      </Typography>
                    </Box>
                  </Box>
                ) : (
                  <>
                    <TableContainer>
                      <Table
                        size="small"
                        sx={{
                          minWidth: 1050,
                        }}
                      >
                        <TableHead>
                          <TableRow>
                            <TableCell>
                              Timestamp
                            </TableCell>

                            <TableCell>
                              Action
                            </TableCell>

                            <TableCell>
                              Actor
                            </TableCell>

                            <TableCell>
                              Resource
                            </TableCell>

                            <TableCell>
                              Outcome
                            </TableCell>

                            <TableCell>
                              Scope
                            </TableCell>

                            <TableCell
                              align="right"
                            >
                              Details
                            </TableCell>
                          </TableRow>
                        </TableHead>

                        <TableBody>
                          {events.map(
                            (
                              event
                            ) => (
                              <TableRow
                                key={
                                  event.id
                                }
                                hover
                                sx={{
                                  cursor:
                                    "pointer",
                                }}
                                onClick={() =>
                                  setSelectedEvent(
                                    event
                                  )
                                }
                              >
                                <TableCell
                                  sx={{
                                    whiteSpace:
                                      "nowrap",
                                  }}
                                >
                                  <Typography
                                    variant=
                                      "body2"
                                  >
                                    {
                                      formatDateTime(
                                        event.createdAt
                                      )
                                    }
                                  </Typography>
                                </TableCell>


                                <TableCell>
                                  <Typography
                                    variant=
                                      "body2"
                                    sx={{
                                      fontWeight:
                                        600,
                                    }}
                                  >
                                    {
                                      event.action
                                    }
                                  </Typography>

                                  {event.message && (
                                    <Typography
                                      variant=
                                        "caption"
                                      color=
                                        "text.secondary"
                                      sx={{
                                        display:
                                          "block",
                                        maxWidth:
                                          360,
                                      }}
                                    >
                                      {
                                        event.message
                                      }
                                    </Typography>
                                  )}
                                </TableCell>


                                <TableCell>
                                  <Typography
                                    variant=
                                      "body2"
                                    sx={{
                                      maxWidth:
                                        230,
                                    }}
                                  >
                                    {
                                      actorLabel(
                                        event.actorUserId
                                      )
                                    }
                                  </Typography>
                                </TableCell>


                                <TableCell>
                                  <Typography
                                    variant=
                                      "body2"
                                  >
                                    {
                                      event.resourceType ||
                                      "—"
                                    }
                                  </Typography>

                                  {event.resourceId && (
                                    <Typography
                                      variant=
                                        "caption"
                                      color=
                                        "text.secondary"
                                      sx={{
                                        display:
                                          "block",
                                        maxWidth:
                                          230,
                                        overflow:
                                          "hidden",
                                        textOverflow:
                                          "ellipsis",
                                      }}
                                    >
                                      {
                                        event.resourceId
                                      }
                                    </Typography>
                                  )}
                                </TableCell>


                                <TableCell>
                                  <Chip
                                    size="small"
                                    variant=
                                      "outlined"
                                    color={
                                      outcomeColor(
                                        event.outcome
                                      )
                                    }
                                    label={
                                      event.outcome
                                    }
                                  />
                                </TableCell>


                                <TableCell>
                                  <Typography
                                    variant=
                                      "body2"
                                  >
                                    {
                                      tenantLabel(
                                        event.tenantId
                                      )
                                    }
                                  </Typography>

                                  {event.publisherId && (
                                    <Typography
                                      variant=
                                        "caption"
                                      color=
                                        "text.secondary"
                                      sx={{
                                        display:
                                          "block",
                                      }}
                                    >
                                      Publisher:{" "}
                                      {
                                        publisherMap
                                          .get(
                                            event.publisherId
                                          )
                                          ?.name ||
                                        event.publisherId
                                      }
                                    </Typography>
                                  )}
                                </TableCell>


                                <TableCell
                                  align="right"
                                >
                                  <Button
                                    size="small"
                                    startIcon={
                                      <VisibilityOutlined />
                                    }
                                    onClick={
                                      (
                                        clickEvent
                                      ) => {

                                        clickEvent
                                          .stopPropagation();

                                        setSelectedEvent(
                                          event
                                        );
                                      }
                                    }
                                  >
                                    View
                                  </Button>
                                </TableCell>
                              </TableRow>
                            )
                          )}
                        </TableBody>
                      </Table>
                    </TableContainer>


                    <Divider />


                    <TablePagination
                      component="div"
                      count={
                        total
                      }
                      page={
                        page
                      }
                      rowsPerPage={
                        rowsPerPage
                      }
                      rowsPerPageOptions={[
                        25,
                        50,
                        100,
                      ]}
                      onPageChange={
                        (
                          _event,
                          nextPage
                        ) =>
                          setPage(
                            nextPage
                          )
                      }
                      onRowsPerPageChange={
                        (
                          event
                        ) => {

                          setRowsPerPage(
                            Number(
                              event
                                .target
                                .value
                            )
                          );

                          setPage(
                            0
                          );
                        }
                      }
                    />
                  </>
                )}
              </Paper>
            </>
          )}
        </Stack>


        {/* EVENT DETAIL */}

        <Dialog
          open={
            Boolean(
              selectedEvent
            )
          }
          onClose={() =>
            setSelectedEvent(
              null
            )
          }
          fullWidth
          maxWidth="md"
        >
          <DialogTitle>
            Audit Event Detail
          </DialogTitle>

          <DialogContent
            dividers
          >
            {selectedEvent && (
              <Stack
                spacing={2}
              >

                <Box
                  sx={{
                    display: "grid",
                    gridTemplateColumns: {
                      xs:
                        "1fr",

                      sm:
                        "repeat(2, minmax(0, 1fr))",
                    },
                    gap: 1.5,
                  }}
                >
                  <Box>
                    <Typography
                      variant="caption"
                      color=
                        "text.secondary"
                    >
                      Event ID
                    </Typography>

                    <Typography
                      variant="body2"
                      sx={{
                        wordBreak:
                          "break-all",
                      }}
                    >
                      {
                        selectedEvent.id
                      }
                    </Typography>
                  </Box>


                  <Box>
                    <Typography
                      variant="caption"
                      color=
                        "text.secondary"
                    >
                      Timestamp
                    </Typography>

                    <Typography
                      variant="body2"
                    >
                      {
                        formatDateTime(
                          selectedEvent
                            .createdAt
                        )
                      }
                    </Typography>
                  </Box>


                  <Box>
                    <Typography
                      variant="caption"
                      color=
                        "text.secondary"
                    >
                      Action
                    </Typography>

                    <Typography
                      variant="body2"
                      sx={{
                        fontWeight: 600,
                      }}
                    >
                      {
                        selectedEvent
                          .action
                      }
                    </Typography>
                  </Box>


                  <Box>
                    <Typography
                      variant="caption"
                      color=
                        "text.secondary"
                    >
                      Outcome
                    </Typography>

                    <Box
                      sx={{
                        mt: 0.5,
                      }}
                    >
                      <Chip
                        size="small"
                        variant=
                          "outlined"
                        color={
                          outcomeColor(
                            selectedEvent
                              .outcome
                          )
                        }
                        label={
                          selectedEvent
                            .outcome
                        }
                      />
                    </Box>
                  </Box>


                  <Box>
                    <Typography
                      variant="caption"
                      color=
                        "text.secondary"
                    >
                      Actor
                    </Typography>

                    <Typography
                      variant="body2"
                    >
                      {
                        actorLabel(
                          selectedEvent
                            .actorUserId
                        )
                      }
                    </Typography>
                  </Box>


                  <Box>
                    <Typography
                      variant="caption"
                      color=
                        "text.secondary"
                    >
                      Scope
                    </Typography>

                    <Typography
                      variant="body2"
                    >
                      {
                        tenantLabel(
                          selectedEvent
                            .tenantId
                        )
                      }
                    </Typography>
                  </Box>


                  <Box>
                    <Typography
                      variant="caption"
                      color=
                        "text.secondary"
                    >
                      Publisher
                    </Typography>

                    <Typography
                      variant="body2"
                      sx={{
                        wordBreak:
                          "break-all",
                      }}
                    >
                      {
                        selectedEvent
                          .publisherId
                          ? (
                              publisherMap
                                .get(
                                  selectedEvent
                                    .publisherId
                                )
                                ?.name ||
                              selectedEvent
                                .publisherId
                            )
                          : "—"
                      }
                    </Typography>
                  </Box>


                  <Box>
                    <Typography
                      variant="caption"
                      color=
                        "text.secondary"
                    >
                      Request ID
                    </Typography>

                    <Typography
                      variant="body2"
                      sx={{
                        wordBreak:
                          "break-all",
                      }}
                    >
                      {
                        selectedEvent
                          .requestId ||
                        "—"
                      }
                    </Typography>
                  </Box>


                  <Box>
                    <Typography
                      variant="caption"
                      color=
                        "text.secondary"
                    >
                      Resource Type
                    </Typography>

                    <Typography
                      variant="body2"
                    >
                      {
                        selectedEvent
                          .resourceType ||
                        "—"
                      }
                    </Typography>
                  </Box>


                  <Box>
                    <Typography
                      variant="caption"
                      color=
                        "text.secondary"
                    >
                      Resource ID
                    </Typography>

                    <Typography
                      variant="body2"
                      sx={{
                        wordBreak:
                          "break-all",
                      }}
                    >
                      {
                        selectedEvent
                          .resourceId ||
                        "—"
                      }
                    </Typography>
                  </Box>
                </Box>


                <Divider />


                <Box>
                  <Typography
                    variant="caption"
                    color=
                      "text.secondary"
                  >
                    Message
                  </Typography>

                  <Typography
                    variant="body2"
                    sx={{
                      mt: 0.5,
                    }}
                  >
                    {
                      selectedEvent
                        .message ||
                      "—"
                    }
                  </Typography>
                </Box>


                <Box>
  <Typography
    variant="subtitle2"
    sx={{
      mb: 1,
      fontWeight: 600,
    }}
  >
    Evidence Metadata
  </Typography>

  {selectedEvent.metadata &&
  Object.keys(
    selectedEvent.metadata
  ).length > 0 ? (

    <Paper
      variant="outlined"
      sx={{
        overflow: "hidden",
      }}
    >
      {Object.entries(
        selectedEvent.metadata
      ).map(
        (
          [
            key,
            value,
          ],
          index
        ) => (

          <Box
            key={
              key
            }
            sx={{
              display: "grid",

              gridTemplateColumns: {
                xs:
                  "1fr",

                sm:
                  "220px minmax(0, 1fr)",
              },

              px: 2,
              py: 1.25,

              borderTop:
                index === 0
                  ? "none"
                  : "1px solid",

              borderColor:
                "divider",
            }}
          >
            <Typography
              variant="body2"
              color=
                "text.secondary"
              sx={{
                fontWeight: 500,
              }}
            >
              {
                metadataLabel(
                  key
                )
              }
            </Typography>

            <Typography
              variant="body2"
              sx={{
                fontFamily:
                  key
                    .toLowerCase()
                    .includes(
                      "id"
                    )
                    ? "Consolas, monospace"
                    : "inherit",

                wordBreak:
                  "break-word",
              }}
            >
              {
                metadataValue(
                  value
                )
              }
            </Typography>
          </Box>
        )
      )}
    </Paper>

  ) : (

    <Typography
      variant="body2"
      color=
        "text.secondary"
    >
      No additional evidence metadata
      was recorded for this event.
    </Typography>
  )}
</Box>

              </Stack>
            )}
          </DialogContent>

          <DialogActions>
            <Button
              onClick={() =>
                setSelectedEvent(
                  null
                )
              }
            >
              Close
            </Button>
          </DialogActions>
        </Dialog>

      </AppShell>
    </ProtectedRoute>
  );
}