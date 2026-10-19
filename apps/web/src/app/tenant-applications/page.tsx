// apps/web/src/app/tenant-applications/page.tsx
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
  Chip,
  CircularProgress,
  InputAdornment,
  TextField,
  Typography,
} from "@mui/material";

import AppsOutlined from "@mui/icons-material/AppsOutlined";
import RefreshOutlined from "@mui/icons-material/RefreshOutlined";
import SearchOutlined from "@mui/icons-material/SearchOutlined";

import AppShell from "@/components/app-shell";
import ProtectedRoute from "@/components/protected-route";

import {
  useTenant,
} from "@/context/tenant-context";

import {
  loadTenantApplications,
  openTenantContainerApplication,
  openTenantStaticApplication,
  TenantApplicationCatalog,
  TenantAvailableApplication,
} from "@/lib/tenant-applications";

import {
  toIsolatedRuntimeGatewayUrl,
} from "@/lib/runtime-gateway";


function apiError(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail: unknown = error.response?.data?.detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const item = detail as Record<string, unknown>;
      const code = typeof item.code === "string" ? item.code : "";
      const reason = typeof item.error === "string" ? item.error : "";
      const message = typeof item.message === "string" ? item.message : "";
      if (code === "APPLICATION_STOPPED") {
        return "Application is currently stopped. Contact your administrator to start the application.";
      }
      if (code === "TENANT_CONTAINER_QUOTA_EXCEEDED" ||
          /tenant runtime container quota exceeded/i.test(reason) ||
          /tenant runtime container quota exceeded/i.test(message)) {
        return "Container limit reached. Your organization has no free container slots. Stop another running application from Runtime Control or ask an administrator to increase the quota. Your subscription remains active.";
      }
      // Prefer the user-safe message from structured API errors, not raw runtime/Docker details.
      if (message) return message;
    }
    if (typeof detail === "string") return detail;
    if (error.response?.status === 403) return "You are not authorized to launch this application for the selected tenant.";
    if (error.response?.status === 422) return "The application could not be launched. Check runtime availability or contact your platform administrator.";
    if (error.response?.status === 409) return "The application cannot be launched in its current state. Refresh and try again.";
    if (error.response?.status === 503) return "The runtime service is currently unavailable. Try again shortly.";
  }
  return error instanceof Error ? error.message : fallback;
}

function formatStatus(
  value: string
): string {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(
      /\b\w/g,
      (character) =>
        character.toUpperCase()
    );
}


export default function TenantApplicationsPage() {
  const {
    selectedTenant,
    selectedTenantId,
    loading: tenantLoading,
    error: tenantContextError,
  } = useTenant();

  const [
    catalog,
    setCatalog,
  ] =
    useState<
      TenantApplicationCatalog | null
    >(null);

  const [
    loading,
    setLoading,
  ] = useState(false);

  const [
    error,
    setError,
  ] = useState("");

  const [
    search,
    setSearch,
  ] = useState("");

  const [
    openingSubscriptionId,
    setOpeningSubscriptionId,
  ] = useState("");


  const loadCatalog =
    useCallback(
      async (
        requestedTenantId: string
      ) => {
        const cleanTenantId =
          requestedTenantId.trim();

        if (!cleanTenantId) {
          setCatalog(null);
          setError("");
          return;
        }

        setLoading(true);
        setError("");

        try {
          const result =
            await loadTenantApplications(
              cleanTenantId
            );

          setCatalog(result);
        } catch (loadError) {
          setCatalog(null);

          setError(
            apiError(
              loadError,
              "Tenant applications could not be loaded."
            )
          );
        } finally {
          setLoading(false);
        }
      },
      []
    );


  /*
   * Remove the legacy Step 3C tenantId query-string parameter.
   * Tenant selection is now owned by the global TenantProvider.
   */
  useEffect(
    () => {
      const url =
        new URL(
          window.location.href
        );

      if (
        !url.searchParams.has(
          "tenantId"
        )
      ) {
        return;
      }

      url.searchParams.delete(
        "tenantId"
      );

      window.history.replaceState(
        {},
        "",
        `${url.pathname}${url.search}${url.hash}`
      );
    },
    []
  );


  /*
   * Automatically reload applications whenever the
   * global tenant selection changes.
   */
  useEffect(
    () => {
      if (tenantLoading) {
        return;
      }

      if (!selectedTenantId) {
        setCatalog(null);
        setSearch("");
        setError("");
        return;
      }

      setSearch("");
      setError("");

      loadCatalog(
        selectedTenantId
      );
    },
    [
      tenantLoading,
      selectedTenantId,
      loadCatalog,
    ]
  );


  const filteredItems =
    useMemo(
      () => {
        const items =
          catalog?.items || [];

        const query =
          search
            .trim()
            .toLowerCase();

        if (!query) {
          return items;
        }

        return items.filter(
          (item) => {
            const text = [
              item.application.name,
              item.application.appKey,
              item.application.description,
              item.offer.name,
              item.version.version,
              item.version.buildType,
            ]
              .filter(Boolean)
              .join(" ")
              .toLowerCase();

            return text.includes(
              query
            );
          }
        );
      },
      [
        catalog,
        search,
      ]
    );


  const openApplication =
    async (
      item: TenantAvailableApplication
    ) => {
      if (item.version.buildType !== "static_web" && item.runtimeState === "stopped") {
        setError("Application is currently stopped. Contact your administrator to start the application.");
        return;
      }
      if (!item.runtimeReady) {
        setError(
          "This application version is not runtime-ready."
        );
        return;
      }

      const cleanTenantId =
        selectedTenantId.trim();

      if (!cleanTenantId) {
        setError(
          "Select an active tenant before opening an application."
        );
        return;
      }

      /*
       * Open the tab synchronously so browser popup blockers
       * do not reject the runtime window after the API call.
       */
      const runtimeWindow =
        window.open(
          "about:blank",
          "_blank"
        );

      if (!runtimeWindow) {
        setError(
          "The application window was blocked by the browser. Allow pop-ups for this AUGMIS site and try again."
        );
        return;
      }

      runtimeWindow.opener =
        null;

      try {
        runtimeWindow.document.title =
          `Opening ${item.application.name}`;

        runtimeWindow.document.body.innerHTML =
          "<div style='font-family:Arial,sans-serif;padding:32px;color:#334155'>Opening application...</div>";
      } catch {
        // about:blank should normally be writable.
        // Failure here must not block the runtime launch.
      }

      setOpeningSubscriptionId(
        item.subscriptionId
      );

      setError("");

      try {
        const buildType =
          String(
            item.version.buildType || ""
          ).toLowerCase();

        const result =
          buildType === "static_web"
            ? await openTenantStaticApplication(
                cleanTenantId,
                item.application.id
              )
            : await openTenantContainerApplication(
                cleanTenantId,
                item.application.id
              );

        const runtimeUrl =
          String(
            result.runtimeUrl || ""
          ).trim();

        if (!runtimeUrl) {
          throw new Error(
            "The runtime started but no runtime URL was returned."
          );
        }

        /*
         * Static applications must pass through the AUGMIS
         * isolated Next.js runtime gateway.
         *
         * Container applications continue using their
         * returned runtime URL directly.
         */
        if (
          buildType === "static_web"
        ) {
          const gatewayUrl =
            toIsolatedRuntimeGatewayUrl(
              runtimeUrl,
              cleanTenantId,
              item.application.id
            );

          runtimeWindow.location.replace(
            gatewayUrl
          );
        } else {
          let parsedUrl: URL;

          try {
            parsedUrl =
              new URL(runtimeUrl);
          } catch {
            throw new Error(
              "The runtime returned an invalid application URL."
            );
          }

          if (
            parsedUrl.protocol !==
              "http:" &&
            parsedUrl.protocol !==
              "https:"
          ) {
            throw new Error(
              "The runtime returned an unsupported application URL."
            );
          }

          runtimeWindow.location.replace(
            parsedUrl.toString()
          );
        }
      } catch (openError) {
        runtimeWindow.close();
        // Refresh stale catalog state if another administrator stopped the app.
        void loadCatalog(cleanTenantId);

        setError(
          apiError(
            openError,
            "Application could not be opened."
          )
        );
      } finally {
        setOpeningSubscriptionId(
          ""
        );
      }
    };


  return (
    <ProtectedRoute>
      <AppShell>
        <Box>

          {/* PAGE HEADER */}
          <Box
            sx={{
              display: "flex",
              alignItems:
                "flex-start",
              justifyContent:
                "space-between",
              gap: 2,
              flexWrap:
                "wrap",
              mb: 3,
            }}
          >
            <Box>
              <Typography
                sx={{
                  fontSize: 12,
                  color:
                    "text.secondary",
                  textTransform:
                    "uppercase",
                  letterSpacing:
                    0.8,
                  mb: 0.5,
                }}
              >
                Tenant Workspace
              </Typography>

              <Typography
                variant="h4"
              >
                Tenant Applications
              </Typography>

              <Typography
                sx={{
                  mt: 0.5,
                  color:
                    "text.secondary",
                }}
              >
                Applications available
                through this tenant&apos;s
                active subscriptions.
              </Typography>
            </Box>

            <Button
              variant="outlined"
              startIcon={
                <RefreshOutlined />
              }
              disabled={
                loading ||
                tenantLoading ||
                !selectedTenantId
              }
              onClick={
                () =>
                  loadCatalog(
                    selectedTenantId
                  )
              }
            >
              Refresh
            </Button>
          </Box>


          {/* TENANT CONTEXT */}
          {tenantContextError ? (
            <Alert
              severity="error"
              sx={{
                mb: 2,
              }}
            >
              {tenantContextError}
            </Alert>
          ) : !tenantLoading &&
            !selectedTenant ? (
            <Alert
              severity="warning"
              sx={{
                mb: 2,
              }}
            >
              You do not currently have
              access to an active tenant.
            </Alert>
          ) : selectedTenant ? (
            <Box
              sx={{
                bgcolor:
                  "#ffffff",
                border:
                  "1px solid",
                borderColor:
                  "divider",
                px: 2.5,
                py: 1.75,
                mb: 2,
                display:
                  "flex",
                alignItems:
                  "center",
                justifyContent:
                  "space-between",
                gap: 2,
                flexWrap:
                  "wrap",
              }}
            >
              <Box>
                <Typography
                  sx={{
                    fontSize: 10,
                    fontWeight: 700,
                    color:
                      "text.secondary",
                    textTransform:
                      "uppercase",
                    letterSpacing:
                      0.6,
                  }}
                >
                  Current Tenant
                </Typography>

                <Typography
                  sx={{
                    mt: 0.35,
                    fontSize: 15,
                    fontWeight: 600,
                  }}
                >
                  {
                    selectedTenant
                      .tenant
                      .name
                  }
                </Typography>

                <Typography
                  sx={{
                    mt: 0.15,
                    fontSize:
                      10.5,
                    color:
                      "text.secondary",
                    fontFamily:
                      "monospace",
                  }}
                >
                  {
                    selectedTenant
                      .tenant
                      .slug
                  }
                </Typography>
              </Box>

              <Chip
                size="small"
                label="Active Tenant"
                color="success"
                variant="outlined"
              />
            </Box>
          ) : null}


          {/* PAGE ERROR */}
          {error && (
            <Alert
              severity="error"
              onClose={
                () =>
                  setError("")
              }
              sx={{
                mb: 2,
              }}
            >
              {error}
              {error.startsWith("Container limit reached.") && (
                <Box sx={{mt:1.5}}>
                  <Button size="small" variant="outlined" href="/runtime-control">
                    Manage running instances
                  </Button>
                </Box>
              )}
            </Alert>
          )}


          {/* CATALOG HEADER / SEARCH */}
          {catalog && (
            <Box
              sx={{
                mb: 2,
                display:
                  "flex",
                justifyContent:
                  "space-between",
                alignItems:
                  "center",
                gap: 2,
                flexWrap:
                  "wrap",
              }}
            >
              <Box>
                <Typography
                  sx={{
                    fontSize: 15,
                    fontWeight: 600,
                  }}
                >
                  {catalog.tenant.name}
                </Typography>

                <Typography
                  sx={{
                    mt: 0.25,
                    fontSize: 11,
                    color:
                      "text.secondary",
                  }}
                >
                  {catalog.count}{" "}
                  available application
                  {catalog.count === 1
                    ? ""
                    : "s"}
                </Typography>
              </Box>

              <TextField
                size="small"
                placeholder=
                  "Search tenant applications"
                value={
                  search
                }
                onChange={
                  (event) =>
                    setSearch(
                      event.target.value
                    )
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
                sx={{
                  width: 340,
                }}
              />
            </Box>
          )}


          {/* LOADING */}
          {loading ? (
            <Box
              sx={{
                minHeight: 300,
                bgcolor:
                  "#ffffff",
                border:
                  "1px solid",
                borderColor:
                  "divider",
                display:
                  "grid",
                placeItems:
                  "center",
              }}
            >
              <CircularProgress
                size={28}
              />
            </Box>

          ) : catalog &&
            filteredItems.length ===
              0 ? (

            /* EMPTY */
            <Box
              sx={{
                minHeight: 260,
                bgcolor:
                  "#ffffff",
                border:
                  "1px solid",
                borderColor:
                  "divider",
                display:
                  "grid",
                placeItems:
                  "center",
                textAlign:
                  "center",
                p: 4,
              }}
            >
              <Box>
                <AppsOutlined
                  sx={{
                    fontSize: 40,
                    color:
                      "text.secondary",
                  }}
                />

                <Typography
                  sx={{
                    mt: 1,
                    fontSize: 16,
                    fontWeight: 600,
                  }}
                >
                  No available applications
                </Typography>

                <Typography
                  sx={{
                    mt: 0.5,
                    fontSize: 12,
                    color:
                      "text.secondary",
                  }}
                >
                  This tenant has no active
                  application subscription
                  matching the current view.
                </Typography>
              </Box>
            </Box>

          ) : catalog ? (

            /* APPLICATION GRID */
            <Box
              sx={{
                display:
                  "grid",
                gridTemplateColumns:
                  {
                    xs: "1fr",
                    md:
                      "repeat(2, minmax(0, 1fr))",
                    xl:
                      "repeat(3, minmax(0, 1fr))",
                  },
                gap: 2,
              }}
            >
              {filteredItems.map(
                (item) => (
                  <Box
                    key={
                      item.subscriptionId
                    }
                    sx={{
                      bgcolor:
                        "#ffffff",
                      border:
                        "1px solid",
                      borderColor:
                        "divider",
                      minHeight:
                        270,
                      display:
                        "flex",
                      flexDirection:
                        "column",
                    }}
                  >

                    {/* CARD HEADER */}
                    <Box
                      sx={{
                        px: 2.5,
                        py: 2.2,
                        borderBottom:
                          "1px solid",
                        borderColor:
                          "divider",
                      }}
                    >
                      <Box
                        sx={{
                          display:
                            "flex",
                          justifyContent:
                            "space-between",
                          gap: 2,
                          alignItems:
                            "flex-start",
                        }}
                      >
                        <Box
                          sx={{
                            minWidth: 0,
                          }}
                        >
                          <Typography
                            sx={{
                              fontSize:
                                17,
                              fontWeight:
                                600,
                            }}
                          >
                            {
                              item
                                .application
                                .name
                            }
                          </Typography>

                          <Typography
                            sx={{
                              mt: 0.35,
                              fontSize:
                                11,
                              color:
                                "text.secondary",
                              fontFamily:
                                "monospace",
                            }}
                          >
                            {
                              item
                                .application
                                .appKey
                            }
                          </Typography>
                        </Box>

                        <Chip
                          size="small"
                          label={
                             item.version.buildType !== "static_web" && item.runtimeState === "stopped"
                               ? "Stopped"
                               : item.runtimeReady ? "Available" : "Not Ready"
                          }
                          color={
                             item.version.buildType !== "static_web" && item.runtimeState === "stopped"
                               ? "error"
                               : item.runtimeReady ? "success" : "warning"
                          }
                          variant="outlined"
                        />
                      </Box>

                      <Typography
                        sx={{
                          mt: 1.25,
                          fontSize: 12,
                          color:
                            "text.secondary",
                          lineHeight:
                            1.55,
                        }}
                      >
                        {
                          item.application
                            .description ||
                          "No application description."
                        }
                      </Typography>
                    </Box>


                    {/* CARD META */}
                    <Box
                      sx={{
                        p: 2.5,
                        display:
                          "grid",
                        gridTemplateColumns:
                          "1fr 1fr",
                        gap: 1.5,
                      }}
                    >
                      <Meta
                        label="Version"
                        value={
                          item.runningVersion || item.version.version
                        }
                      />

                      <Meta
                        label="Technical"
                        value={
                          formatStatus(
                            item.version
                              .technicalStatus
                          )
                        }
                      />

                      <Meta
                        label="Build Type"
                        value={
                          formatStatus(
                            item.version
                              .buildType
                          )
                        }
                      />

                      <Meta
                        label="Deployment"
                        value={
                          formatStatus(
                            item.version
                              .deploymentMode
                          )
                        }
                      />

                      <Meta
                        label="Subscription"
                        value={
                          formatStatus(
                            item.subscription
                              .status
                          )
                        }
                      />

                      <Meta
                        label="Offer"
                        value={
                          item.offer.name
                        }
                      />
                    </Box>


                    {item.version.buildType !== "static_web" && item.runtimeState === "stopped" && (
                       <Alert severity="warning" sx={{mx:2.5,mb:1.5}}>
                         Application is currently stopped. Contact your administrator to start the application.
                       </Alert>
                     )}

                    {/* CARD ACTION */}
                    <Box
                      sx={{
                        mt: "auto",
                        px: 2.5,
                        py: 1.7,
                        borderTop:
                          "1px solid",
                        borderColor:
                          "divider",
                        display:
                          "flex",
                        justifyContent:
                          "flex-end",
                      }}
                    >
                      <Button
                        size="small"
                        variant="contained"
                        disabled={
                           !item.runtimeReady ||
                           (item.version.buildType !== "static_web" && item.runtimeState === "stopped") ||
                           Boolean(
                            openingSubscriptionId
                          )
                        }
                        onClick={
                          () =>
                            openApplication(
                              item
                            )
                        }
                      >
                        {
                          openingSubscriptionId ===
                          item.subscriptionId ? (
                            <>
                              <CircularProgress
                                size={14}
                                sx={{
                                  mr: 1,
                                  color:
                                    "inherit",
                                }}
                              />
                              Opening...
                            </>
                          ) : (
                            "Open Application"
                          )
                        }
                      </Button>
                    </Box>
                  </Box>
                )
              )}
            </Box>

          ) : null}

        </Box>
      </AppShell>
    </ProtectedRoute>
  );
}


function Meta({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <Box>
      <Typography
        sx={{
          fontSize: 9,
          color:
            "text.secondary",
          textTransform:
            "uppercase",
          letterSpacing:
            0.45,
        }}
      >
        {label}
      </Typography>

      <Typography
        sx={{
          mt: 0.25,
          fontSize: 11.5,
          fontWeight: 600,
        }}
      >
        {value}
      </Typography>
    </Box>
  );
}
