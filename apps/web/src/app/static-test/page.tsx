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
  TextField,
  Typography,
} from "@mui/material";

import OpenInNewOutlined
  from "@mui/icons-material/OpenInNewOutlined";

import RefreshOutlined
  from "@mui/icons-material/RefreshOutlined";

import AppShell
  from "@/components/app-shell";

import ProtectedRoute
  from "@/components/protected-route";

import {
  loadTenantApplications,
  openTenantStaticApplication,
  TenantApplicationCatalog,
  TenantAvailableApplication,
} from "@/lib/tenant-applications";


const TENANT_STORAGE_KEY =
  "augmis.platform.selectedTenantId";


function apiError(
  error: unknown,
  fallback: string
): string {

  if (axios.isAxiosError(error)) {

    const detail =
      error.response?.data?.detail;

    if (typeof detail === "string") {
      return detail;
    }

    if (
      detail &&
      typeof detail === "object" &&
      "message" in detail
    ) {
      return String(
        (detail as { message?: unknown })
          .message || fallback
      );
    }
  }

  if (error instanceof Error) {
    return error.message;
  }

  return fallback;
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


export default function StaticApplicationTestPage() {

  const [
    tenantId,
    setTenantId,
  ] = useState("");

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
    openingId,
    setOpeningId,
  ] = useState("");

  const [
    error,
    setError,
  ] = useState("");

  const [
    success,
    setSuccess,
  ] = useState("");


  useEffect(
    () => {

      const params =
        new URLSearchParams(
          window.location.search
        );

      const initialTenantId =
        params.get("tenantId") ||
        window.localStorage.getItem(
          TENANT_STORAGE_KEY
        ) ||
        "";

      setTenantId(
        initialTenantId
      );

    },
    []
  );


  const loadStaticApplications =
    useCallback(
      async (
        requestedTenantId: string
      ) => {

        const cleanTenantId =
          requestedTenantId.trim();

        if (!cleanTenantId) {

          setCatalog(null);

          setError(
            "Enter a tenant ID."
          );

          return;
        }

        setLoading(true);
        setError("");
        setSuccess("");

        try {

          const result =
            await loadTenantApplications(
              cleanTenantId
            );

          setCatalog(result);

          window.localStorage.setItem(
            TENANT_STORAGE_KEY,
            cleanTenantId
          );

          const url =
            new URL(
              window.location.href
            );

          url.searchParams.set(
            "tenantId",
            cleanTenantId
          );

          window.history.replaceState(
            {},
            "",
            url.toString()
          );

        } catch (
          loadError
        ) {

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


  useEffect(
    () => {

      if (tenantId) {
        loadStaticApplications(
          tenantId
        );
      }

    },
    [
      tenantId,
      loadStaticApplications,
    ]
  );


  const staticApplications =
    useMemo(
      () => {

        return (
          catalog?.items || []
        ).filter(
          (item) =>
            String(
              item.version.buildType || ""
            ).toLowerCase() ===
            "static_web"
        );

      },
      [catalog]
    );


  const openStaticApplication =
    async (
      item: TenantAvailableApplication
    ) => {

      const cleanTenantId =
        tenantId.trim();

      if (!cleanTenantId) {

        setError(
          "Tenant ID is required."
        );

        return;
      }

      if (!item.runtimeReady) {

        setError(
          "This static application is not runtime-ready."
        );

        return;
      }

      /*
       * Open immediately so the browser does not block
       * the new tab after the async launch request.
       */
      const runtimeWindow =
        window.open(
          "about:blank",
          "_blank"
        );

      if (!runtimeWindow) {

        setError(
          "The browser blocked the application window. Allow pop-ups for localhost and try again."
        );

        return;
      }

      runtimeWindow.opener = null;

      try {

        runtimeWindow.document.title =
          `Opening ${item.application.name}`;

        runtimeWindow.document.body.innerHTML =
          "<div style='font-family:Arial,sans-serif;padding:32px;color:#334155'>Opening static application...</div>";

      } catch {
        // about:blank is normally writable.
      }

      setOpeningId(
        item.subscriptionId
      );

      setError("");
      setSuccess("");

      try {

        const result =
          await openTenantStaticApplication(
            cleanTenantId,
            item.application.id
          );

        const runtimeUrl =
          String(
            result.runtimeUrl || ""
          ).trim();

        if (!runtimeUrl) {

          throw new Error(
            "Static launch succeeded but no runtime URL was returned."
          );
        }

        const parsedUrl =
          new URL(runtimeUrl);

        if (
          parsedUrl.protocol !== "http:" &&
          parsedUrl.protocol !== "https:"
        ) {

          throw new Error(
            "The static runtime returned an unsupported URL."
          );
        }

        setSuccess(
          `${item.application.name} static runtime launched successfully.`
        );

        runtimeWindow.location.replace(
          parsedUrl.toString()
        );

      } catch (
        openError
      ) {

        runtimeWindow.close();

        setError(
          apiError(
            openError,
            "Static application could not be opened."
          )
        );

      } finally {

        setOpeningId("");
      }
    };


  return (
    <ProtectedRoute>

      <AppShell>

        <Box>

          <Box
            sx={{
              display: "flex",
              justifyContent:
                "space-between",
              alignItems:
                "flex-start",
              gap: 2,
              flexWrap: "wrap",
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
                Static Runtime Test
              </Typography>

              <Typography
                variant="h4"
              >
                Static Applications
              </Typography>

              <Typography
                sx={{
                  mt: 0.5,
                  color:
                    "text.secondary",
                }}
              >
                Isolated Step 3C-3B test page.
                Your existing Tenant Applications
                page is not changed.
              </Typography>

            </Box>

            <Button
              variant="outlined"
              startIcon={
                <RefreshOutlined />
              }
              disabled={
                loading ||
                !tenantId.trim()
              }
              onClick={
                () =>
                  loadStaticApplications(
                    tenantId
                  )
              }
            >
              Refresh
            </Button>

          </Box>


          <Box
            sx={{
              bgcolor: "#ffffff",
              border: "1px solid",
              borderColor:
                "divider",
              p: 2.5,
              mb: 2,
            }}
          >

            <Typography
              sx={{
                fontSize: 11,
                fontWeight: 700,
                color:
                  "text.secondary",
                textTransform:
                  "uppercase",
                letterSpacing:
                  0.5,
                mb: 1,
              }}
            >
              Tenant Scope
            </Typography>

            <Box
              sx={{
                display: "flex",
                gap: 1,
                alignItems:
                  "center",
                flexWrap: "wrap",
              }}
            >

              <TextField
                size="small"
                value={tenantId}
                onChange={
                  (event) =>
                    setTenantId(
                      event.target.value
                    )
                }
                placeholder=
                  "Tenant UUID"
                sx={{
                  minWidth: 390,
                }}
              />

              <Button
                variant="contained"
                disabled={
                  loading ||
                  !tenantId.trim()
                }
                onClick={
                  () =>
                    loadStaticApplications(
                      tenantId
                    )
                }
              >
                Load Static Apps
              </Button>

            </Box>

          </Box>


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
            </Alert>

          )}


          {success && (

            <Alert
              severity="success"
              onClose={
                () =>
                  setSuccess("")
              }
              sx={{
                mb: 2,
              }}
            >
              {success}
            </Alert>

          )}


          {loading ? (

            <Box
              sx={{
                minHeight: 280,
                bgcolor: "#ffffff",
                border: "1px solid",
                borderColor:
                  "divider",
                display: "grid",
                placeItems:
                  "center",
              }}
            >
              <CircularProgress
                size={28}
              />
            </Box>

          ) : catalog &&
          staticApplications.length === 0 ? (

            <Alert
              severity="info"
            >
              This tenant currently has no
              active, runtime-ready static
              application subscriptions.
            </Alert>

          ) : (

            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: {
                  xs: "1fr",
                  md:
                    "repeat(2, minmax(0, 1fr))",
                  xl:
                    "repeat(3, minmax(0, 1fr))",
                },
                gap: 2,
              }}
            >

              {staticApplications.map(
                (item) => (

                  <Box
                    key={
                      item.subscriptionId
                    }
                    sx={{
                      bgcolor: "#ffffff",
                      border: "1px solid",
                      borderColor:
                        "divider",
                      minHeight: 250,
                      display: "flex",
                      flexDirection:
                        "column",
                    }}
                  >

                    <Box
                      sx={{
                        p: 2.5,
                        borderBottom:
                          "1px solid",
                        borderColor:
                          "divider",
                      }}
                    >

                      <Box
                        sx={{
                          display: "flex",
                          justifyContent:
                            "space-between",
                          gap: 2,
                          alignItems:
                            "flex-start",
                        }}
                      >

                        <Box>

                          <Typography
                            sx={{
                              fontSize: 18,
                              fontWeight:
                                600,
                            }}
                          >
                            {
                              item.application
                                .name
                            }
                          </Typography>

                          <Typography
                            sx={{
                              mt: 0.35,
                              fontSize: 11,
                              color:
                                "text.secondary",
                              fontFamily:
                                "monospace",
                            }}
                          >
                            {
                              item.application
                                .appKey
                            }
                          </Typography>

                        </Box>

                        <Chip
                          size="small"
                          label={
                            item.runtimeReady
                              ? "Static Ready"
                              : "Not Ready"
                          }
                          color={
                            item.runtimeReady
                              ? "success"
                              : "warning"
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
                        }}
                      >
                        {
                          item.application
                            .description ||
                          "No application description."
                        }
                      </Typography>

                    </Box>


                    <Box
                      sx={{
                        p: 2.5,
                        display: "grid",
                        gridTemplateColumns:
                          "1fr 1fr",
                        gap: 1.5,
                      }}
                    >

                      <Meta
                        label="Version"
                        value={
                          item.version.version
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
                        label="Subscription"
                        value={
                          formatStatus(
                            item.subscription
                              .status
                          )
                        }
                      />

                    </Box>


                    <Box
                      sx={{
                        mt: "auto",
                        px: 2.5,
                        py: 1.7,
                        borderTop:
                          "1px solid",
                        borderColor:
                          "divider",
                        display: "flex",
                        justifyContent:
                          "flex-end",
                      }}
                    >

                      <Button
                        size="small"
                        variant="contained"
                        startIcon={
                          openingId ===
                          item.subscriptionId
                            ? (
                              <CircularProgress
                                size={14}
                                sx={{
                                  color:
                                    "inherit",
                                }}
                              />
                            )
                            : (
                              <OpenInNewOutlined />
                            )
                        }
                        disabled={
                          !item.runtimeReady ||
                          Boolean(openingId)
                        }
                        onClick={
                          () =>
                            openStaticApplication(
                              item
                            )
                        }
                      >
                        {openingId ===
                        item.subscriptionId
                          ? "Opening..."
                          : "Open Static App"}
                      </Button>

                    </Box>

                  </Box>

                )
              )}

            </Box>

          )}

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
