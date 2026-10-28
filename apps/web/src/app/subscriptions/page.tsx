// apps/web/src/app/subscriptions/page.tsx
"use client";

import {
  useCallback,
  useEffect,
  useRef,
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
  MenuItem,
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

import SwapHorizOutlined
  from "@mui/icons-material/SwapHorizOutlined";

import AppShell
  from "@/components/app-shell";

import ProtectedRoute
  from "@/components/protected-route";

import {
  cancelTenantSubscription,
  changeTenantSubscriptionOffer,
  loadSubscriptionChangeOffers,
  loadTenantSubscriptions,
  resumeTenantSubscription,
  suspendTenantSubscription,
  TenantSubscriptionSummary,
  SubscriptionChangeOfferOption,
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

  const [
    changeOfferTarget,
    setChangeOfferTarget,
  ] = useState<TenantSubscriptionSummary | null>(null);

  // Changing tenants dismisses the operation; the authoritative backend
  // independently validates the subscription's tenant permission.
  const [changeOfferTenantId, setChangeOfferTenantId] = useState("");
  const [changeOfferOptions, setChangeOfferOptions] =
    useState<SubscriptionChangeOfferOption[]>([]);
  const [changeOfferSelection, setChangeOfferSelection] = useState("");
  const [changeOfferLoading, setChangeOfferLoading] = useState(false);
  const [changeOfferError, setChangeOfferError] = useState("");
  const changeOfferRequestId = useRef(0);


  


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


  useEffect(() => {
    changeOfferRequestId.current += 1;
    setChangeOfferTarget(null);
    setChangeOfferTenantId("");
    setChangeOfferOptions([]);
    setChangeOfferSelection("");
    setChangeOfferError("");
    setChangeOfferLoading(false);
  }, [selectedTenantId]);

  const openChangeOffer = async (subscription: TenantSubscriptionSummary) => {
    if (!selectedTenantId || busyId) return;
    const requestId = ++changeOfferRequestId.current;

    setChangeOfferTarget(subscription);
    setChangeOfferTenantId(selectedTenantId);
    setChangeOfferOptions([]);
    setChangeOfferSelection("");
    setChangeOfferError("");
    setChangeOfferLoading(true);
    setError("");
    setMessage("");

    try {
      const options = await loadSubscriptionChangeOffers(subscription.application.id);
      if (requestId === changeOfferRequestId.current) {
        setChangeOfferOptions(options.filter((offer) => offer.id !== subscription.offer.id));
      }
    } catch (loadError) {
      if (requestId === changeOfferRequestId.current) {
        setChangeOfferError(apiError(loadError, "Available offers could not be loaded."));
      }
    } finally {
      if (requestId === changeOfferRequestId.current) setChangeOfferLoading(false);
    }
  };

  const submitChangeOffer = async () => {
    const subscription = changeOfferTarget;
    const option = changeOfferOptions.find((offer) => offer.id === changeOfferSelection);
    if (
      !subscription || !option || busyId || changeOfferLoading ||
      !selectedTenantId || selectedTenantId !== changeOfferTenantId ||
      option.application.id !== subscription.application.id ||
      option.id === subscription.offer.id
    ) return;

    setBusyId(subscription.id);
    setChangeOfferError("");
    setMessage("");
    setError("");

    try {
      const result = await changeTenantSubscriptionOffer(subscription.id, option.id);
      if (
        result.status !== "CHANGED" ||
        result.subscriptionId !== subscription.id ||
        result.applicationId !== subscription.application.id ||
        result.tenantId !== selectedTenantId ||
        result.offer.id !== option.id
      ) {
        throw new Error("Subscription change returned an unexpected response. Refresh and verify before continuing.");
      }
      changeOfferRequestId.current += 1;
      setChangeOfferTarget(null);
      setChangeOfferSelection("");
      setChangeOfferOptions([]);
      setMessage(`${subscription.application.name}: changed to ${result.offer.name} (${result.versionPolicy}).`);
      await loadSubscriptions(selectedTenantId);
    } catch (actionError) {
      setChangeOfferError(apiError(actionError, "Offer change failed. No further action was taken by the page."));
    } finally {
      setBusyId("");
    }
  };

  const selectedChangeOffer = changeOfferOptions.find(
    (offer) => offer.id === changeOfferSelection
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
                      onChangeOffer={
                        () => openChangeOffer(subscription)
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

        <Dialog
          open={Boolean(changeOfferTarget)}
          onClose={() => {
            if (!busyId) {
              changeOfferRequestId.current += 1;
              setChangeOfferTarget(null);
            }
          }}
          fullWidth
          maxWidth="sm"
        >
          <DialogTitle>Change Subscription Offer</DialogTitle>
          <DialogContent>
            <Typography sx={{ fontSize: 13, fontWeight: 600, mb: 0.5 }}>
              {changeOfferTarget?.application.name}
            </Typography>
            <Typography sx={{ fontSize: 11, color: "text.secondary", mb: 2 }}>
              Subscription: {changeOfferTarget?.id}
            </Typography>

            <Box sx={{ bgcolor: "#f4f6f8", p: 1.5, border: "1px solid", borderColor: "divider", mb: 2 }}>
              <Typography sx={{ fontSize: 11, fontWeight: 600 }}>
                Current: {changeOfferTarget?.offer.name}
              </Typography>
              <Typography sx={{ fontSize: 11, color: "text.secondary" }}>
                Policy: {changeOfferTarget?.versionPolicy} · Auto-upgrade: {changeOfferTarget?.autoUpgrade ? "On" : "Off"}
              </Typography>
            </Box>

            {changeOfferLoading ? (
              <Box sx={{ display: "flex", alignItems: "center", gap: 1, py: 1 }}>
                <CircularProgress size={18} />
                <Typography sx={{ fontSize: 12 }}>Loading active offers for this application…</Typography>
              </Box>
            ) : (
              <TextField
                select
                fullWidth
                size="small"
                label="Target offer"
                value={changeOfferSelection}
                onChange={(event) => {
                  setChangeOfferSelection(event.target.value);
                  setChangeOfferError("");
                }}
                disabled={Boolean(busyId) || changeOfferOptions.length === 0}
                helperText="Only active offers for this exact application with a deployment entitlement are selectable."
              >
                {changeOfferOptions.map((offer) => (
                  <MenuItem key={offer.id} value={offer.id}>
                    {offer.name} — {offer.offerKey} ({offer.versionPolicy})
                  </MenuItem>
                ))}
              </TextField>
            )}

            {!changeOfferLoading && !changeOfferError && changeOfferOptions.length === 0 && (
              <Alert severity="info" sx={{ mt: 2 }}>
                No other eligible active offer is available for this application.
              </Alert>
            )}

            {selectedChangeOffer && (
              <Box sx={{ mt: 2, p: 1.5, bgcolor: "#f4f6f8", border: "1px solid", borderColor: "divider" }}>
                <Typography sx={{ fontWeight: 600, fontSize: 12, mb: 0.75 }}>
                  Proposed commercial terms
                </Typography>
                <Typography sx={{ fontSize: 12 }}>Version policy: {selectedChangeOffer.versionPolicy}</Typography>
                <Typography sx={{ fontSize: 12 }}>Auto-upgrade: {selectedChangeOffer.autoUpgrade ? "On" : "Off"}</Typography>
                <Typography sx={{ fontSize: 12, mt: 0.75 }}>
                  Entitlements: {selectedChangeOffer.entitlements.map((entry) =>
                    `${entry.code}${typeof entry.value?.maxInstances === "number" ? ` (max ${entry.value?.maxInstances})` : ""}`
                  ).join(", ")}
                </Typography>
              </Box>
            )}

            <Alert severity="warning" sx={{ mt: 2 }}>
              Confirming changes this existing subscription's commercial policy and
              entitlement snapshot. The backend checks running-instance compatibility.
              It does not upgrade, restart, or create an application instance.
            </Alert>
            {changeOfferError && <Alert severity="error" sx={{ mt: 2 }}>{changeOfferError}</Alert>}
          </DialogContent>
          <DialogActions>
            <Button
              disabled={Boolean(busyId)}
              onClick={() => {
                changeOfferRequestId.current += 1;
                setChangeOfferTarget(null);
              }}
            >
              Cancel
            </Button>
            <Button
              variant="contained"
              disabled={
                Boolean(busyId) || changeOfferLoading || !selectedChangeOffer ||
                !selectedTenantId || selectedTenantId !== changeOfferTenantId
              }
              onClick={submitChangeOffer}
            >
              {busyId ? "Changing…" : "Confirm Change Offer"}
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
  onChangeOffer,
  onSuspend,
  onResume,
  onCancel,
}: {
  subscription:
    TenantSubscriptionSummary;
  busy:
    boolean;
  onChangeOffer:
    () => void;
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
              startIcon={<SwapHorizOutlined />}
              disabled={busy}
              onClick={onChangeOffer}
            >
              Change Offer
            </Button>
          )}

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
