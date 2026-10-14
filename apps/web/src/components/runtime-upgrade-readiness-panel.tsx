"use client";

import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { Alert, Box, Button, Chip, CircularProgress, Paper, Typography } from "@mui/material";
import {
  getRuntimeUpgradeReadiness, updateRuntimeAutoUpgradeConsent,
  type RuntimeUpgradeReadiness,
} from "@/lib/runtime-control";

const reasons: Record<string, string> = {
  NO_ACTIVE_CONTRACT: "No active offer/subscription currently authorizes this instance.",
  MULTIPLE_ACTIVE_CONTRACTS: "Multiple active subscriptions match this application. Resolve their ownership before enabling automation.",
  SUBSCRIPTION_NOT_STARTED: "The subscription has not yet started.",
  SUBSCRIPTION_EXPIRED: "The subscription has expired.",
  INSTANCE_NOT_RUNNING: "The instance must be running before a candidate can be planned.",
  DEPLOY_ENTITLEMENT_MISSING: "Deployment entitlement is missing or expired.",
  AUTO_UPGRADE_DISABLED: "Automatic upgrades are disabled for this subscription.",
  NO_ELIGIBLE_PUBLISHED_TARGET: "No newer, published, image-ready version is permitted by the subscription policy.",
  ELIGIBLE: "A published, policy-approved image is eligible for the next worker run.",
};

function detail(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const value: unknown = err.response?.data?.detail;
    if (typeof value === "string") return value;
    if (err.response?.status === 403) return "Your tenant role cannot change this subscription.";
  }
  return err instanceof Error ? err.message : "Could not read the upgrade setting.";
}

export default function RuntimeUpgradeReadinessPanel({ instanceId }: { instanceId: string }) {
  const [readiness, setReadiness] = useState<RuntimeUpgradeReadiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setReadiness(await getRuntimeUpgradeReadiness(instanceId));
      setError("");
    } catch (err) {
      setReadiness(null);
      setError(detail(err));
    } finally { setLoading(false); }
  }, [instanceId]);

  useEffect(() => {
    let active = true;
    setLoading(true); setReadiness(null); setError(""); setNotice("");
    void getRuntimeUpgradeReadiness(instanceId)
      .then((result) => { if (active) setReadiness(result); })
      .catch((err) => { if (active) setError(detail(err)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [instanceId]);

  const toggle = async () => {
    if (!readiness?.subscriptionId) return;
    const enable = !readiness.autoUpgrade;
    // Enabling consent changes a commercial subscription and may trigger future workers.
    if (enable && !window.confirm("Enable automatic upgrades for this subscription? Any eligible running instance covered by it may be upgraded when the trusted worker runs.")) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const updated = await updateRuntimeAutoUpgradeConsent(instanceId, readiness.autoUpgrade, enable);
      setNotice(updated.autoUpgrade
        ? "Auto-upgrade consent enabled. No upgrade has been queued or executed by this action."
        : "Auto-upgrade consent disabled. A running job, if any, requires operator review.");
      await reload();
    } catch (err) { setError(detail(err)); }
    finally { setBusy(false); }
  };

  const ambiguous = readiness?.reason === "MULTIPLE_ACTIVE_CONTRACTS";
  const mayToggle = !!readiness?.subscriptionId && !ambiguous;
  return <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 0 }}>
    <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 2, flexWrap: "wrap", mb: 1.5 }}>
      <Box>
        <Typography variant="h6">Subscription upgrade readiness</Typography>
        <Typography variant="caption" color="text.secondary">The setting is subscription-wide. Upgrades are executed only by a separately activated worker.</Typography>
      </Box>
      <Button variant="outlined" size="small" onClick={() => void reload()} disabled={busy || loading}>Refresh readiness</Button>
    </Box>
    {loading && <CircularProgress size={22} />}
    {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}
    {notice && <Alert severity="success" sx={{ mb: 1 }}>{notice}</Alert>}
    {readiness && <>
      <Box sx={{ display: "flex", gap: 1, alignItems: "center", flexWrap: "wrap", mb: 1.5 }}>
        <Chip size="small" variant="outlined" color={readiness.autoUpgrade ? "success" : "default"}
          label={readiness.autoUpgrade ? "Opted in" : "Opted out"} />
        <Chip size="small" variant="outlined" label={`Policy: ${readiness.versionPolicy ?? "not available"}`} />
        <Chip size="small" variant="outlined" label={`Current: ${readiness.currentVersion ?? "unknown"}`} />
        {readiness.candidateVersion && <Chip size="small" color="success" label={`Candidate: ${readiness.candidateVersion}`} />}
      </Box>
      <Alert severity={readiness.status === "eligible" ? "success" : ambiguous ? "error" : "info"} sx={{ mb: 2 }}>
        {reasons[readiness.reason] ?? readiness.reason}
      </Alert>
      <Button variant={readiness.autoUpgrade ? "outlined" : "contained"} disabled={!mayToggle || busy || loading}
        onClick={() => void toggle()}>
        {readiness.autoUpgrade ? "Disable automatic upgrades" : "Enable automatic upgrades"}
      </Button>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
        Requires subscription.manage. This action does not build, publish, deploy, or alter the running container.
      </Typography>
    </>}
  </Paper>;
}
