"use client";

import {
  useCallback,
  useEffect,
  useState,
} from "react";

import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Stack,
  Typography,
} from "@mui/material";

import RefreshOutlined
  from "@mui/icons-material/RefreshOutlined";

import AppShell
  from "@/components/app-shell";

import ProtectedRoute
  from "@/components/protected-route";

import {
  useAuth,
} from "@/context/auth-context";

import {
  ControlCenterData,
  loadControlCenterData,
} from "@/lib/control-center";


function formatAction(
  action: string
): string {

  return action
    .replace(
      /[._]/g,
      " "
    )
    .replace(
      /\b\w/g,
      (character) =>
        character.toUpperCase()
    );
}


function formatDate(
  value: string
): string {

  return new Intl.DateTimeFormat(
    undefined,
    {
      dateStyle: "medium",
      timeStyle: "short",
    }
  ).format(
    new Date(value)
  );
}


export default function Home() {

  const {
    user,
  } = useAuth();


  const [
    data,
    setData,
  ] =
    useState<
      ControlCenterData | null
    >(null);


  const [
    loading,
    setLoading,
  ] =
    useState(false);


  const [
    error,
    setError,
  ] =
    useState("");


  const loadDashboard =
    useCallback(
      async () => {

        setLoading(true);

        setError("");

        try {

          const result =
            await loadControlCenterData();

          setData(result);

        } catch {

          setError(
            "The Control Center could not load platform data."
          );

        } finally {

          setLoading(false);
        }
      },
      []
    );


  useEffect(
    () => {

      if (user) {

        loadDashboard();
      }

    },
    [
      user,
      loadDashboard,
    ]
  );


  const metrics =
    data
      ? [
          {
            label:
              "Applications",

            value:
              data.counts
                .applications,

            detail:
              `${data.counts.versions} versions registered`,
          },

          {
            label:
              "Active Offers",

            value:
              data.counts
                .activeOffers,

            detail:
              `${data.counts.publishers} publisher workspace${data.counts.publishers === 1 ? "" : "s"}`,
          },

          {
            label:
              "Active Subscriptions",

            value:
              data.counts
                .activeSubscriptions,

            detail:
              `${data.counts.tenants} tenant workspace${data.counts.tenants === 1 ? "" : "s"}`,
          },

          {
            label:
              "Running Instances",

            value:
              data.counts
                .runningInstances,

            detail:
              `${data.counts.totalInstances} total logical instances`,
          },
        ]

      : [];


  return (
    <ProtectedRoute>

      <AppShell
        platformHealth={
          data?.health
        }
      >

        <Stack spacing={3}>

          {/* ===========================================
              PAGE HEADING
          ============================================ */}

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
                Platform Operations
              </Typography>


              <Typography
                variant="h4"
              >
                Control Center
              </Typography>


              <Typography
                sx={{
                  color:
                    "text.secondary",

                  mt: 0.5,
                }}
              >
                Live publisher,
                commerce and runtime
                overview.
              </Typography>

            </Box>


            <Button
              variant="outlined"

              startIcon={
                loading
                  ? (
                      <CircularProgress
                        size={15}
                      />
                    )
                  : (
                      <RefreshOutlined />
                    )
              }

              onClick={
                loadDashboard
              }

              disabled={
                loading
              }
            >
              Refresh
            </Button>

          </Box>


          {/* ===========================================
              ERROR
          ============================================ */}

          {error && (

            <Alert
              severity="error"

              action={
                <Button
                  size="small"
                  onClick={
                    loadDashboard
                  }
                >
                  Retry
                </Button>
              }
            >
              {error}
            </Alert>

          )}


          {/* ===========================================
              INITIAL LOADING
          ============================================ */}

          {loading && !data && (

            <Box
              sx={{
                minHeight:
                  300,

                display:
                  "grid",

                placeItems:
                  "center",

                bgcolor:
                  "#ffffff",

                border:
                  "1px solid",

                borderColor:
                  "divider",
              }}
            >

              <Stack
                spacing={2}
                sx={{
                  alignItems:
                    "center",
                }}
              >

                <CircularProgress
                  size={28}
                />

                <Typography
                  sx={{
                    fontSize: 13,

                    color:
                      "text.secondary",
                  }}
                >
                  Loading platform
                  data...
                </Typography>

              </Stack>

            </Box>

          )}


          {data && (

            <>

              {/* =======================================
                  LIVE METRICS
              ======================================== */}

              <Box
                sx={{
                  display:
                    "grid",

                  gridTemplateColumns: {
                    xs:
                      "1fr",

                    sm:
                      "repeat(2, 1fr)",

                    xl:
                      "repeat(4, 1fr)",
                  },

                  borderTop:
                    "1px solid",

                  borderLeft:
                    "1px solid",

                  borderColor:
                    "divider",
                }}
              >

                {metrics.map(
                  (metric) => (

                    <Box
                      key={
                        metric.label
                      }
                      sx={{
                        bgcolor:
                          "#ffffff",

                        minHeight:
                          125,

                        p: 2.5,

                        borderRight:
                          "1px solid",

                        borderBottom:
                          "1px solid",

                        borderColor:
                          "divider",
                      }}
                    >

                      <Typography
                        sx={{
                          fontSize:
                            12,

                          color:
                            "text.secondary",

                          textTransform:
                            "uppercase",

                          letterSpacing:
                            0.5,
                        }}
                      >
                        {metric.label}
                      </Typography>


                      <Typography
                        sx={{
                          fontSize:
                            34,

                          fontWeight:
                            600,

                          mt: 1,

                          lineHeight:
                            1,
                        }}
                      >
                        {metric.value}
                      </Typography>


                      <Typography
                        sx={{
                          fontSize:
                            12,

                          color:
                            "text.secondary",

                          mt: 1.4,
                        }}
                      >
                        {metric.detail}
                      </Typography>

                    </Box>

                  )
                )}

              </Box>


              {/* =======================================
                  MAIN CONTENT
              ======================================== */}

              <Box
                sx={{
                  display:
                    "grid",

                  gridTemplateColumns: {
                    xs:
                      "1fr",

                    lg:
                      "2fr 1fr",
                  },

                  gap: 2,
                }}
              >

                {/* =====================================
                    ACTIVITY
                ====================================== */}

                <Box
                  sx={{
                    bgcolor:
                      "#ffffff",

                    border:
                      "1px solid",

                    borderColor:
                      "divider",
                  }}
                >

                  <Box
                    sx={{
                      px: 2.5,
                      py: 1.7,

                      borderBottom:
                        "1px solid",

                      borderColor:
                        "divider",
                    }}
                  >

                    <Typography
                      sx={{
                        fontWeight:
                          600,
                      }}
                    >
                      Platform Activity
                    </Typography>

                    <Typography
                      sx={{
                        fontSize:
                          12,

                        color:
                          "text.secondary",
                      }}
                    >
                      Recent tenant
                      control-plane events
                    </Typography>

                  </Box>


                  {data.activity.length === 0 ? (

                    <Box
                      sx={{
                        p: 3,

                        color:
                          "text.secondary",

                        fontSize:
                          13,
                      }}
                    >
                      No visible audit
                      events.
                    </Box>

                  ) : (

                    data.activity.map(
                      (
                        event,
                        index
                      ) => (

                        <Box
                          key={
                            event.id
                          }
                          sx={{
                            px: 2.5,
                            py: 1.5,

                            display:
                              "grid",

                            gridTemplateColumns: {
                              xs:
                                "1fr",

                              md:
                                "170px 1fr 90px",
                            },

                            gap: 2,

                            borderBottom:
                              index <
                              data.activity.length - 1
                                ? "1px solid"
                                : "none",

                            borderColor:
                              "divider",
                          }}
                        >

                          <Typography
                            sx={{
                              fontSize:
                                11,

                              color:
                                "text.secondary",
                            }}
                          >
                            {formatDate(
                              event.createdAt
                            )}
                          </Typography>


                          <Box>

                            <Typography
                              sx={{
                                fontSize:
                                  13,

                                fontWeight:
                                  600,
                              }}
                            >
                              {formatAction(
                                event.action
                              )}
                            </Typography>


                            <Typography
                              sx={{
                                mt: 0.25,

                                fontSize:
                                  12,

                                color:
                                  "text.secondary",
                              }}
                            >
                              {event.message ??
                                event.resourceType}
                            </Typography>

                          </Box>


                          <Typography
                            sx={{
                              fontSize:
                                11,

                              fontWeight:
                                600,

                              color:
                                event.outcome ===
                                "success"
                                  ? "#397451"
                                  : "#b44545",

                              textTransform:
                                "uppercase",
                            }}
                          >
                            {event.outcome}
                          </Typography>

                        </Box>

                      )
                    )

                  )}

                </Box>


                {/* =====================================
                    RIGHT COLUMN
                ====================================== */}

                <Stack spacing={2}>

                  {/* HEALTH */}

                  <Box
                    sx={{
                      bgcolor:
                        "#ffffff",

                      border:
                        "1px solid",

                      borderColor:
                        "divider",
                    }}
                  >

                    <Box
                      sx={{
                        px: 2.5,
                        py: 1.7,

                        borderBottom:
                          "1px solid",

                        borderColor:
                          "divider",
                      }}
                    >
                      <Typography
                        sx={{
                          fontWeight:
                            600,
                        }}
                      >
                        Runtime Health
                      </Typography>

                      <Typography
                        sx={{
                          fontSize:
                            12,

                          color:
                            "text.secondary",
                        }}
                      >
                        Live readiness
                        checks
                      </Typography>
                    </Box>


                    <Stack
                      spacing={2}
                      sx={{
                        p: 2.5,
                      }}
                    >

                      <StatusRow
                        label=
                          "Control Plane API"

                        healthy={
                          data.health.api
                        }
                      />

                      <StatusRow
                        label=
                          "PostgreSQL"

                        healthy={
                          data.health.database
                        }
                      />

                      <StatusRow
                        label=
                          "Docker Runtime"

                        healthy={
                          data.health.docker
                        }
                      />

                    </Stack>

                  </Box>


                  {/* WORKSPACES */}

                  <Box
                    sx={{
                      bgcolor:
                        "#ffffff",

                      border:
                        "1px solid",

                      borderColor:
                        "divider",
                    }}
                  >

                    <Box
                      sx={{
                        px: 2.5,
                        py: 1.7,

                        borderBottom:
                          "1px solid",

                        borderColor:
                          "divider",
                      }}
                    >
                      <Typography
                        sx={{
                          fontWeight:
                            600,
                        }}
                      >
                        Workspace Access
                      </Typography>

                      <Typography
                        sx={{
                          fontSize:
                            12,

                          color:
                            "text.secondary",
                        }}
                      >
                        Current user
                        memberships
                      </Typography>
                    </Box>


                    <Box
                      sx={{
                        p: 2.5,
                      }}
                    >

                      <Typography
                        sx={{
                          fontSize:
                            11,

                          color:
                            "text.secondary",

                          textTransform:
                            "uppercase",

                          letterSpacing:
                            0.5,
                        }}
                      >
                        Publishers
                      </Typography>


                      {data.workspaces.publishers.map(
                        (publisher) => (

                          <Typography
                            key={
                              publisher.id
                            }
                            sx={{
                              mt: 0.75,

                              fontSize:
                                13,

                              fontWeight:
                                600,
                            }}
                          >
                            {publisher.name}
                          </Typography>

                        )
                      )}


                      <Typography
                        sx={{
                          mt: 2.5,

                          fontSize:
                            11,

                          color:
                            "text.secondary",

                          textTransform:
                            "uppercase",

                          letterSpacing:
                            0.5,
                        }}
                      >
                        Tenants
                      </Typography>


                      {data.workspaces.tenants.map(
                        (tenant) => (

                          <Typography
                            key={
                              tenant.id
                            }
                            sx={{
                              mt: 0.75,

                              fontSize:
                                13,

                              fontWeight:
                                600,
                            }}
                          >
                            {tenant.name}
                          </Typography>

                        )
                      )}

                    </Box>

                  </Box>

                </Stack>

              </Box>

            </>

          )}

        </Stack>

      </AppShell>

    </ProtectedRoute>
  );
}


function StatusRow({
  label,
  healthy,
}: {
  label: string;
  healthy: boolean;
}) {

  return (
    <Box
      sx={{
        display:
          "flex",

        alignItems:
          "center",

        justifyContent:
          "space-between",

        gap: 2,
      }}
    >

      <Typography
        sx={{
          fontSize: 12,

          color:
            "text.secondary",
        }}
      >
        {label}
      </Typography>


      <Typography
        sx={{
          fontSize: 12,

          fontWeight:
            600,

          color:
            healthy
              ? "#397451"
              : "#b44545",
        }}
      >
        {healthy
          ? "● Healthy"
          : "● Unavailable"}
      </Typography>

    </Box>
  );
}