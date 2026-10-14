"use client";
import { useEffect, useState } from "react";
import axios from "axios";
import { Alert, Box, Button, Paper, TextField, Typography } from "@mui/material";
import { updateRuntimeQuota, type RuntimeQuota } from "@/lib/runtime-control";

type Props = { tenantId: string; quota: RuntimeQuota | null; onSaved: (quota: RuntimeQuota) => void };

function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail: unknown = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (err.response?.status === 403) return "You need platform.settings.manage permission to update tenant quotas.";
  }
  return err instanceof Error ? err.message : "Unable to change the runtime quota.";
}

export default function RuntimeQuotaManager({ tenantId, quota, onSaved }: Props) {
  const [editing, setEditing] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    setEditing(false);
    setInput(quota?.maxRunningContainers == null ? "" : String(quota.maxRunningContainers));
    setError(""); setNotice("");
  }, [tenantId, quota?.maxRunningContainers]);

  const parsed = Number(input);
  const valid = /^\d+$/.test(input) && Number.isSafeInteger(parsed) && parsed >= 1 && parsed <= 1000;
  const save = async () => {
    if (!valid || busy || !quota?.canManageQuota) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const updated = await updateRuntimeQuota(tenantId, parsed);
      onSaved({ ...updated, canManageQuota: quota.canManageQuota });
      setEditing(false);
      setNotice("Quota saved. New deployments will be checked against this limit.");
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  };
  return <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 0 }}>
    <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 2 }}>
      <Box>
        <Typography variant="h6">Tenant container quota</Typography>
        <Typography variant="body2" color="text.secondary">
          Concurrent running/deploying containers: <strong>{quota?.maxRunningContainers ?? "No tenant-specific limit configured"}</strong>
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Docker CPU/memory/PID limits remain platform-controlled. Existing containers are not stopped when this setting changes.
        </Typography>
      </Box>
      {quota?.canManageQuota && !editing && <Button variant="outlined" onClick={() => setEditing(true)}>Edit quota</Button>}
    </Box>
    {!quota?.canManageQuota && <Typography variant="caption" color="text.secondary">
      Read-only: quota changes require platform.settings.manage permission.
    </Typography>}
    {error && <Alert severity="error" sx={{ mt: 1.5 }}>{error}</Alert>}
    {notice && <Alert severity="success" sx={{ mt: 1.5 }}>{notice}</Alert>}
    {editing && <Box sx={{ display: "flex", alignItems: "flex-start", gap: 1.5, flexWrap: "wrap", mt: 2 }}>
      <TextField size="small" label="Maximum concurrent containers" type="number" value={input}
        onChange={(e) => setInput(e.target.value)} error={!!input && !valid}
        helperText="Whole number between 1 and 1000. Cannot be below current usage."
        slotProps={{ htmlInput: { min: 1, max: 1000, step: 1 } }} sx={{ width: { xs: "100%", sm: 300 } }} />
      <Button variant="contained" disabled={!valid || busy || Number(input) === quota?.maxRunningContainers} onClick={() => void save()}>Save quota</Button>
      <Button variant="outlined" disabled={busy} onClick={() => { setEditing(false); setError(""); }}>Cancel</Button>
    </Box>}
  </Paper>;
}
