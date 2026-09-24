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

import AppsOutlined
  from "@mui/icons-material/AppsOutlined";

import RefreshOutlined
  from "@mui/icons-material/RefreshOutlined";

import SearchOutlined
  from "@mui/icons-material/SearchOutlined";

import AppShell
  from "@/components/app-shell";

import ProtectedRoute
  from "@/components/protected-route";

import {
  loadTenantApplications,
  openTenantContainerApplication,
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

  if (
    axios.isAxiosError(
      error
    )
  ) {

    const detail =
      error.response?.data
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


function formatStatus(
  value: string
): string {

  return String(
    value || ""
  )
    .replace(
      /_/g,
      " "
    )
    .replace(
      /\b\w/g,
      (character) =>
        character.toUpperCase()
    );
}


export default function TenantApplicationsPage() {

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


  useEffect(
    () => {

      const params =
        new URLSearchParams(
          window.location.search
        );

      const queryTenantId =
        params.get(
          "tenantId"
        );

      const storedTenantId =
        window.localStorage.getItem(
          TENANT_STORAGE_KEY
        );


      const initialTenantId =
        queryTenantId ||
        storedTenantId ||
        "";


      setTenantId(
        initialTenantId
      );

    },
    []
  );


  const loadCatalog =
    useCallback(
      async (
        requestedTenantId:
          string
      ) => {

        const cleanTenantId =
          requestedTenantId.trim();


        if (
          !cleanTenantId
        ) {

          setCatalog(
            null
          );

          setError(
            "Enter a tenant ID."
          );

          return;
        }


        setLoading(
          true
        );

        setError(
          ""
        );


        try {

          const result =
            await loadTenantApplications(
              cleanTenantId
            );


          setCatalog(
            result
          );


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

          setCatalog(
            null
          );

          setError(
            apiError(
              loadError,
              "Tenant applications could not be loaded."
            )
          );

        } finally {

          setLoading(
            false
          );
        }
      },
      []
    );


  useEffect(
    () => {

      if (
        tenantId
      ) {

        loadCatalog(
          tenantId
        );
      }

    },
    [
      tenantId,
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

      if (
        !item.runtimeReady
      ) {

        setError(
          "This application version is not runtime-ready."
        );

        return;
      }


      const cleanTenantId =
        tenantId.trim();


      if (
        !cleanTenantId
      ) {

        setError(
          "Tenant ID is required before opening an application."
        );

        return;
      }


      // Open the browser tab immediately so popup blockers do not
      // reject the runtime URL after the async API call completes.
      const runtimeWindow =
        window.open(
          "about:blank",
          "_blank"
        );


      if (
        !runtimeWindow
      ) {

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
        // about:blank should normally be writable, but failure here
        // must not block the tenant-safe launch request.
      }


      setOpeningSubscriptionId(
        item.subscriptionId
      );

      setError(
        ""
      );


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


        if (
          !runtimeUrl
        ) {
          throw new Error(
            "The runtime started but no runtime URL was returned."
          );
        }


        let parsedUrl: URL;

        try {
          parsedUrl =
            new URL(
              runtimeUrl
            );
        } catch {
          throw new Error(
            "The runtime returned an invalid application URL."
          );
        }


        if (
          parsedUrl.protocol !== "http:" &&
          parsedUrl.protocol !== "https:"
        ) {
          throw new Error(
            "The runtime returned an unsupported application URL."
          );
        }


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

          <Box
            sx={{
              display:
                "flex",

              alignItems:
                "flex-start",

              justifyContent:
                "space-between",

              gap:
                2,

              flexWrap:
                "wrap",

              mb:
                3,
            }}
          >

            <Box>

              <Typography
                sx={{
                  fontSize:
                    12,

                  color:
                    "text.secondary",

                  textTransform:
                    "uppercase",

                  letterSpacing:
                    0.8,

                  mb:
                    0.5,
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
                  mt:
                    0.5,

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
                !tenantId.trim()
              }

              onClick={
                () =>
                  loadCatalog(
                    tenantId
                  )
              }
            >
              Refresh
            </Button>

          </Box>


          <Box
            sx={{
              bgcolor:
                "#ffffff",

              border:
                "1px solid",

              borderColor:
                "divider",

              p:
                2.5,

              mb:
                2,
            }}
          >

            <Typography
              sx={{
                fontSize:
                  11,

                fontWeight:
                  700,

                color:
                  "text.secondary",

                textTransform:
                  "uppercase",

                letterSpacing:
                  0.5,

                mb:
                  1,
              }}
            >
              Tenant Scope
            </Typography>


            <Box
              sx={{
                display:
                  "flex",

                gap:
                  1,

                alignItems:
                  "center",

                flexWrap:
                  "wrap",
              }}
            >

              <TextField
                size="small"

                value={
                  tenantId
                }

                onChange={
                  (event) =>
                    setTenantId(
                      event.target.value
                    )
                }

                placeholder=
                  "Tenant UUID"

                sx={{
                  minWidth:
                    390,
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
                    loadCatalog(
                      tenantId
                    )
                }
              >
                Load Applications
              </Button>

            </Box>


            <Typography
              sx={{
                mt:
                  1,

                fontSize:
                  10.5,

                color:
                  "text.secondary",
              }}
            >
              Temporary Step 3C tenant
              input. The API still enforces
              tenant RBAC; entering another
              tenant&apos;s UUID does not
              bypass access control.
            </Typography>

          </Box>


          {error && (

            <Alert
              severity="error"

              onClose={
                () =>
                  setError("")
              }

              sx={{
                mb:
                  2,
              }}
            >
              {error}
            </Alert>

          )}


          {catalog && (

            <Box
              sx={{
                mb:
                  2,

                display:
                  "flex",

                justifyContent:
                  "space-between",

                alignItems:
                  "center",

                gap:
                  2,

                flexWrap:
                  "wrap",
              }}
            >

              <Box>

                <Typography
                  sx={{
                    fontSize:
                      15,

                    fontWeight:
                      600,
                  }}
                >
                  {catalog.tenant.name}
                </Typography>


                <Typography
                  sx={{
                    mt:
                      0.25,

                    fontSize:
                      11,

                    color:
                      "text.secondary",
                  }}
                >
                  {catalog.count}
                  {" "}
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
                  width:
                    340,
                }}
              />

            </Box>

          )}


          {loading ? (

            <Box
              sx={{
                minHeight:
                  300,

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
          filteredItems.length === 0 ? (

            <Box
              sx={{
                minHeight:
                  260,

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

                p:
                  4,
              }}
            >

              <Box>

                <AppsOutlined
                  sx={{
                    fontSize:
                      40,

                    color:
                      "text.secondary",
                  }}
                />


                <Typography
                  sx={{
                    mt:
                      1,

                    fontSize:
                      16,

                    fontWeight:
                      600,
                  }}
                >
                  No available applications
                </Typography>


                <Typography
                  sx={{
                    mt:
                      0.5,

                    fontSize:
                      12,

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

            <Box
              sx={{
                display:
                  "grid",

                gridTemplateColumns: {
                  xs:
                    "1fr",

                  md:
                    "repeat(2, minmax(0, 1fr))",

                  xl:
                    "repeat(3, minmax(0, 1fr))",
                },

                gap:
                  2,
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

                    <Box
                      sx={{
                        px:
                          2.5,

                        py:
                          2.2,

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

                          gap:
                            2,

                          alignItems:
                            "flex-start",
                        }}
                      >

                        <Box
                          sx={{
                            minWidth:
                              0,
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
                            {item.application
                              .name}
                          </Typography>


                          <Typography
                            sx={{
                              mt:
                                0.35,

                              fontSize:
                                11,

                              color:
                                "text.secondary",

                              fontFamily:
                                "monospace",
                            }}
                          >
                            {item.application
                              .appKey}
                          </Typography>

                        </Box>


                        <Chip
                          size="small"

                          label={
                            item.runtimeReady
                              ? "Available"
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
                          mt:
                            1.25,

                          fontSize:
                            12,

                          color:
                            "text.secondary",

                          lineHeight:
                            1.55,
                        }}
                      >
                        {item.application
                          .description ||
                          "No application description."}
                      </Typography>

                    </Box>


                    <Box
                      sx={{
                        p:
                          2.5,

                        display:
                          "grid",

                        gridTemplateColumns:
                          "1fr 1fr",

                        gap:
                          1.5,
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


                    <Box
                      sx={{
                        mt:
                          "auto",

                        px:
                          2.5,

                        py:
                          1.7,

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
                        {openingSubscriptionId ===
                        item.subscriptionId ? (
                          <>
                            <CircularProgress
                              size={14}
                              sx={{
                                mr: 1,
                                color: "inherit",
                              }}
                            />
                            Opening...
                          </>
                        ) : (
                          "Open Application"
                        )}
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
  label:
    string;

  value:
    string;
}) {

  return (
    <Box>

      <Typography
        sx={{
          fontSize:
            9,

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
          mt:
            0.25,

          fontSize:
            11.5,

          fontWeight:
            600,
        }}
      >
        {value}
      </Typography>

    </Box>
  );
}
