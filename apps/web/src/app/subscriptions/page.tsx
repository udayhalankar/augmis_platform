"use client";

import {
  useCallback,
  useEffect,
  useState,
} from "react";

import axios from "axios";

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

  const [
    tenantId,
    setTenantId,
  ] = useState("");


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

      const savedTenantId =
        window.localStorage.getItem(
          TENANT_STORAGE_KEY
        );

      setTenantId(
        queryTenantId ||
        savedTenantId ||
        ""
      );

    },
    []
  );


  const loadSubscriptions =
    useCallback(
      async (
        requestedTenantId:
          string
      ) => {

        const cleanTenantId =
          requestedTenantId
            .trim();

        if (!cleanTenantId) {

          setSubscriptions(
            []
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

          const rows =
            await loadTenantSubscriptions(
              cleanTenantId
            );

          setSubscriptions(
            rows
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

      if (
        tenantId
      ) {
        loadSubscriptions(
          tenantId
        );
      }

    },
    [
      tenantId,
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

        await loadSubscriptions(
          tenantId
        );

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

        await loadSubscriptions(
          tenantId
        );

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
                !tenantId.trim()
              }
              onClick={
                () =>
                  loadSubscriptions(
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
                letterSpacing: 0.5,
                mb: 1,
              }}
            >
              Tenant Scope
            </Typography>

            <Box
              sx={{
                display:
                  "flex",
                gap: 1,
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
                  minWidth: 380,
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
                    loadSubscriptions(
                      tenantId
                    )
                }
              >
                Load Subscriptions
              </Button>
            </Box>

            <Typography
              sx={{
                mt: 1,
                fontSize: 10.5,
                color:
                  "text.secondary",
              }}
            >
              Temporary Step 3B control: use the tenant UUID. We will replace this with a tenant dropdown once the tenant-list API contract is wired.
            </Typography>
          </Box>


          {message && (
            <Alert
              severity="success"
              onClose={
                () =>
                  setMessage("")
              }
              sx={{ mb: 2 }}
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
              sx={{ mb: 2 }}
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
