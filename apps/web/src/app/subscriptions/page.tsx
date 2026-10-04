// apps/web/src/app/subscriptions/page.tsx
"use client";

import {
  useCallback,
  useEffect,
  useState,
} from "react";

import axios from "axios";

import {
  useTenant,
} from "@/context/tenant-context";

import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  TextField,
  Typography,
} from "@mui/material";

import RefreshOutlined
  from "@mui/icons-material/RefreshOutlined";

import PauseCircleOutlineOutlined
  from "@mui/icons-material/PauseCircleOutlineOutlined";

import PlayCircleOutlineOutlined
  from "@mui/icons-material/PlayCircleOutlineOutlined";

import CancelOutlined
  from "@mui/icons-material/CancelOutlined";

import AppShell
  from "@/components/app-shell";

import ProtectedRoute
  from "@/components/protected-route";

import {
  cancelTenantSubscription,
  loadTenantSubscriptions,
  resumeTenantSubscription,
  suspendTenantSubscription,
  TenantSubscriptionSummary,
} from "@/lib/subscriptions";


// const TENANT_STORAGE_KEY =
//   "augmis.platform.selectedTenantId";


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


function statusColor(
  status: string
):
  | "success"
  | "warning"
  | "default"
  | "error" {

  const normalized =
    String(
      status || ""
    ).toLowerCase();

  if (
    normalized ===
    "active"
  ) {
    return "success";
  }

  if (
    normalized ===
    "suspended"
  ) {
    return "warning";
  }

  if (
    normalized ===
    "cancelled"
  ) {
    return "error";
  }

  return "default";
}


export default function SubscriptionsPage() {

  const {
  selectedTenant,
  selectedTenantId,
  loading: tenantLoading,
  error: tenantContextError,
  } = useTenant();


  const [
    subscriptions,
    setSubscriptions,
  ] = useState<
    TenantSubscriptionSummary[]
  >([]);


  const [
    loading,
    setLoading,
  ] = useState(false);


  const [
    error,
    setError,
  ] = useState("");


  const [
    message,
    setMessage,
  ] = useState("");


  const [
    busyId,
    setBusyId,
  ] = useState("");


  const [
    suspendTarget,
    setSuspendTarget,
  ] = useState<
    TenantSubscriptionSummary | null
  >(null);


  const [
    suspendReason,
    setSuspendReason,
  ] = useState("");


  


 const loadSubscriptions =
  useCallback(
    async (
      requestedTenantId: string
    ) => {

      const cleanTenantId =
        requestedTenantId.trim();


      if (!cleanTenantId) {

        setSubscriptions(
          []
        );

        setError(
          ""
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

        const rows =
          await loadTenantSubscriptions(
            cleanTenantId
          );


        setSubscriptions(
          rows
        );

      } catch (
        loadError
      ) {

        setSubscriptions(
          []
        );


        setError(
          apiError(
            loadError,
            "Subscriptions could not be loaded."
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


 useEffect(
  () => {

    if (
      tenantLoading
    ) {
      return;
    }


    if (
      !selectedTenantId
    ) {

      setSubscriptions(
        []
      );

      return;
    }


    setMessage(
      ""
    );

    setError(
      ""
    );


    loadSubscriptions(
      selectedTenantId
    );

  },
  [
    tenantLoading,
    selectedTenantId,
    loadSubscriptions,
  ]
);


  const runAction =
    async (
      subscription:
        TenantSubscriptionSummary,

      action:
        "resume" |
        "cancel"
    ) => {

      if (
        action ===
          "cancel" &&
        !window.confirm(
          `Cancel subscription for ${subscription.application.name}?`
        )
      ) {
        return;
      }


      setBusyId(
        subscription.id
      );

      setError(
        ""
      );

      setMessage(
        ""
      );


      try {

        if (
          action ===
          "resume"
        ) {

          await resumeTenantSubscription(
            subscription.id
          );

          setMessage(
            `${subscription.application.name} subscription resumed.`
          );

        } else {

          await cancelTenantSubscription(
            subscription.id
          );

          setMessage(
            `${subscription.application.name} subscription cancelled.`
          );
        }

        if (
  selectedTenantId
) {

  await loadSubscriptions(
    selectedTenantId
  );
}

      } catch (
        actionError
      ) {

        setError(
          apiError(
            actionError,
            "Subscription action failed."
          )
        );

      } finally {

        setBusyId(
          ""
        );
      }
    };


  const suspend =
    async () => {

      if (
        !suspendTarget
      ) {
        return;
      }


      setBusyId(
        suspendTarget.id
      );

      setError(
        ""
      );

      setMessage(
        ""
      );


      try {

        await suspendTenantSubscription(
          suspendTarget.id,
          suspendReason.trim()
        );

        setMessage(
          `${suspendTarget.application.name} subscription suspended.`
        );

        setSuspendTarget(
          null
        );

        setSuspendReason(
          ""
        );

        if (
  selectedTenantId
) {

  await loadSubscriptions(
    selectedTenantId
  );
}

      } catch (
        suspendError
      ) {

        setError(
          apiError(
            suspendError,
            "Subscription could not be suspended."
          )
        );

      } finally {

        setBusyId(
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
                  letterSpacing: 0.8,
                  mb: 0.5,
                }}
              >
                Tenant Commerce
              </Typography>

              <Typography
                variant="h4"
              >
                Subscriptions
              </Typography>

              <Typography
                sx={{
                  mt: 0.5,
                  color:
                    "text.secondary",
                }}
              >
                Manage tenant application subscriptions and lifecycle.
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
                    loadSubscriptions(
                      selectedTenantId
                    )
                }
              >
                Refresh
              </Button>

          </Box>

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
    You do not currently have access to an active tenant.
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

          fontWeight:
            600,
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

          fontSize: 10.5,

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

{message && (

  <Alert
    severity="success"
    onClose={
      () =>
        setMessage("")
    }
    sx={{
      mb: 2,
    }}
  >
    {message}
  </Alert>

)}


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
          ) : (
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
                  display:
                    "flex",
                  justifyContent:
                    "space-between",
                  alignItems:
                    "center",
                }}
              >
                <Typography
                  sx={{
                    fontSize: 16,
                    fontWeight: 600,
                  }}
                >
                  Tenant Subscriptions
                </Typography>

                <Typography
                  sx={{
                    fontSize: 11,
                    color:
                      "text.secondary",
                  }}
                >
                  {subscriptions.length} record{subscriptions.length === 1 ? "" : "s"}
                </Typography>
              </Box>

              {subscriptions.length === 0 ? (
                <Box
                  sx={{
                    p: 5,
                    textAlign:
                      "center",
                    color:
                      "text.secondary",
                  }}
                >
                  No subscriptions loaded for this tenant.
                </Box>
              ) : (
                subscriptions.map(
                  (subscription) => (
                    <SubscriptionRow
                      key={
                        subscription.id
                      }
                      subscription={
                        subscription
                      }
                      busy={
                        busyId ===
                        subscription.id
                      }
                      onSuspend={
                        () => {
                          setSuspendTarget(
                            subscription
                          );
                          setSuspendReason(
                            ""
                          );
                        }
                      }
                      onResume={
                        () =>
                          runAction(
                            subscription,
                            "resume"
                          )
                      }
                      onCancel={
                        () =>
                          runAction(
                            subscription,
                            "cancel"
                          )
                      }
                    />
                  )
                )
              )}
            </Box>
          )}

        </Box>


        <Dialog
          open={
            Boolean(
              suspendTarget
            )
          }
          onClose={
            () => {
              if (busyId) {
                return;
              }
              setSuspendTarget(
                null
              );
            }
          }
          fullWidth
          maxWidth="sm"
        >
          <DialogTitle>
            Suspend Subscription
          </DialogTitle>

          <DialogContent>
            <Typography
              sx={{
                mb: 2,
                color:
                  "text.secondary",
                fontSize: 12,
              }}
            >
              {suspendTarget?.application.name}
            </Typography>

            <TextField
              label="Reason"
              fullWidth
              multiline
              minRows={3}
              value={
                suspendReason
              }
              onChange={
                (event) =>
                  setSuspendReason(
                    event.target.value
                  )
              }
            />
          </DialogContent>

          <DialogActions>
            <Button
              disabled={
                Boolean(
                  busyId
                )
              }
              onClick={
                () =>
                  setSuspendTarget(
                    null
                  )
              }
            >
              Cancel
            </Button>

            <Button
              variant="contained"
              color="warning"
              disabled={
                Boolean(
                  busyId
                ) ||
                !suspendReason.trim()
              }
              onClick={
                suspend
              }
            >
              Suspend
            </Button>
          </DialogActions>
        </Dialog>

      </AppShell>
    </ProtectedRoute>
  );
}


function SubscriptionRow({
  subscription,
  busy,
  onSuspend,
  onResume,
  onCancel,
}: {
  subscription:
    TenantSubscriptionSummary;
  busy:
    boolean;
  onSuspend:
    () => void;
  onResume:
    () => void;
  onCancel:
    () => void;
}) {

  const status =
    String(
      subscription.status || ""
    ).toLowerCase();

  return (
    <Box>
      <Box
        sx={{
          display:
            "grid",
          gridTemplateColumns:
            "minmax(220px, 1.5fr) minmax(160px, 1fr) minmax(130px, .8fr) minmax(120px, .7fr) minmax(240px, 1.2fr)",
          gap: 2,
          alignItems:
            "center",
          px: 2.5,
          py: 2,
        }}
      >
        <Box>
          <Typography
            sx={{
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            {subscription.application.name}
          </Typography>

          <Typography
            sx={{
              mt: 0.25,
              fontSize: 10.5,
              color:
                "text.secondary",
              fontFamily:
                "monospace",
            }}
          >
            {subscription.application.appKey}
          </Typography>
        </Box>

        <Box>
          <Typography
            sx={{
              fontSize: 9,
              color:
                "text.secondary",
              textTransform:
                "uppercase",
            }}
          >
            Offer
          </Typography>

          <Typography
            sx={{
              mt: 0.25,
              fontSize: 11.5,
              fontWeight: 600,
            }}
          >
            {subscription.offer.name}
          </Typography>
        </Box>

        <Box>
          <Typography
            sx={{
              fontSize: 9,
              color:
                "text.secondary",
              textTransform:
                "uppercase",
            }}
          >
            Version Policy
          </Typography>

          <Typography
            sx={{
              mt: 0.25,
              fontSize: 11.5,
              fontWeight: 600,
            }}
          >
            {subscription.versionPolicy}
          </Typography>
        </Box>

        <Chip
          size="small"
          label={
            subscription.status
          }
          color={
            statusColor(
              subscription.status
            )
          }
          variant="outlined"
          sx={{
            justifySelf:
              "start",
            textTransform:
              "capitalize",
          }}
        />

        <Box
          sx={{
            display:
              "flex",
            justifyContent:
              "flex-end",
            gap: 0.75,
            flexWrap:
              "wrap",
          }}
        >
          {status === "active" && (
            <Button
              size="small"
              variant="outlined"
              color="warning"
              startIcon={
                <PauseCircleOutlineOutlined />
              }
              disabled={busy}
              onClick={onSuspend}
            >
              Suspend
            </Button>
          )}

          {status === "suspended" && (
            <Button
              size="small"
              variant="outlined"
              startIcon={
                <PlayCircleOutlineOutlined />
              }
              disabled={busy}
              onClick={onResume}
            >
              Resume
            </Button>
          )}

          {(status === "active" || status === "suspended") && (
            <Button
              size="small"
              variant="outlined"
              color="error"
              startIcon={
                <CancelOutlined />
              }
              disabled={busy}
              onClick={onCancel}
            >
              Cancel
            </Button>
          )}
        </Box>
      </Box>

      <Divider />
    </Box>
  );
}
