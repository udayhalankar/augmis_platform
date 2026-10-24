"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Divider,
  MenuItem,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import RefreshOutlined from "@mui/icons-material/RefreshOutlined";
import AdministrationTabs from "@/components/administration-tabs";
import { usePermissions } from "@/context/permission-context";
import {
  clearTenantIdle,
  listSessionPolicies,
  SessionPolicies,
  updateDefaultIdle,
  updateTenantIdle,
} from "@/lib/session-policies";

function PolicyEditor() {
  const { hasPlatformPermission } = usePermissions();
  const allowed = hasPlatformPermission("platform.settings.manage");
  const [data, setData] = useState<SessionPolicies | null>(null);
  const [tenant, setTenant] = useState("");
  const [minutes, setMinutes] = useState("30");
  const [defaultMinutes, setDefaultMinutes] = useState("30");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  // Preserve the existing session-policy API flow and permission checks.
  const load = useCallback(async () => {
    try {
      const result = await listSessionPolicies();
      setData(result);
      setDefaultMinutes(String(result.platformDefaultMinutes));
    } catch {
      setError("Could not load session policies. Verify platform settings permission and API availability.");
    }
  }, []);

  useEffect(() => {
    if (allowed) void load();
  }, [allowed, load]);

  const save = async (operation: () => Promise<void>) => {
    setSaving(true);
    setError("");
    try {
      await operation();
      await load();
    } catch {
      setError("Policy change failed. No success is assumed; inspect the backend response.");
    } finally {
      setSaving(false);
    }
  };

  const valid = (v: string) =>
    Number.isInteger(Number(v)) && Number(v) >= 5 && Number(v) <= 120;

  return (
    <Box sx={{ minWidth: 0 }}>
      {!allowed ? (
        <Alert severity="error">Permission platform.settings.manage is required.</Alert>
      ) : (
        <Stack spacing={2}>
          {error && <Alert severity="error">{error}</Alert>}

          {/* One shared bordered work area, matching the RBAC editor. */}
          <Box
            sx={{
              bgcolor: "background.paper",
              border: "1px solid",
              borderColor: "divider",
              minWidth: 0,
            }}
          >
            <AdministrationTabs
              value="security"
              tabs={[{ value: "security", label: "Session Security" }]}
              ariaLabel="Platform settings tabs"
              action={
                <Button variant="outlined" startIcon={<RefreshOutlined />} disabled={saving} onClick={() => void load()}>
                  Refresh
                </Button>
              }
            />

            <Box sx={{ px: 2.5, py: 2 }}>
              <Typography sx={{ fontSize: 14, fontWeight: 600 }}>
                Session Inactivity Policies
              </Typography>
              <Typography sx={{ mt: 0.35, fontSize: 12, color: "text.secondary" }}>
                Changes take effect on subsequent server checks. Background API traffic does not extend idle activity.
              </Typography>
            </Box>
            <Divider />

            <Box sx={{ px: 2.5, py: 2.5 }}>
              <Typography sx={{ fontSize: 15, fontWeight: 600 }}>Platform Default</Typography>
              <Typography sx={{ mt: 0.35, fontSize: 12, color: "text.secondary" }}>
                Used by tenants that do not have an explicit override.
              </Typography>
              <Stack
                direction={{ xs: "column", sm: "row" }}
                spacing={2}
                sx={{ mt: 2, alignItems: { xs: "stretch", sm: "center" } }}
              >
                <TextField
                  label="Idle timeout (minutes)"
                  type="number"
                  size="small"
                  sx={{ width: { xs: "100%", sm: 210 } }}
                  slotProps={{ htmlInput: { min: 5, max: 120 } }}
                  value={defaultMinutes}
                  onChange={(e) => setDefaultMinutes(e.target.value)}
                />
                <Button
                  variant="contained"
                  disabled={saving || !valid(defaultMinutes)}
                  onClick={() => void save(() => updateDefaultIdle(Number(defaultMinutes)))}
                >
                  Save Platform Default
                </Button>
              </Stack>
            </Box>
            <Divider />

            <Box sx={{ px: 2.5, pt: 2.5, pb: 2 }}>
              <Typography sx={{ fontSize: 15, fontWeight: 600 }}>Tenant Overrides</Typography>
              <Typography sx={{ mt: 0.35, fontSize: 12, color: "text.secondary" }}>
                Configure a separate inactivity period for a selected tenant.
              </Typography>
              <Stack
                direction={{ xs: "column", md: "row" }}
                spacing={1.5}
                sx={{ mt: 2, alignItems: { xs: "stretch", md: "center" }, flexWrap: "wrap" }}
              >
                <Select
                  size="small"
                  displayEmpty
                  value={tenant}
                  onChange={(e) => {
                    const id = e.target.value;
                    setTenant(id);
                    setMinutes(String(data?.tenants.find((t) => t.id === id)?.idleMinutes ?? 30));
                  }}
                  sx={{ minWidth: { xs: "100%", md: 245 }, bgcolor: "background.paper" }}
                >
                  <MenuItem value="" disabled>Select tenant</MenuItem>
                  {data?.tenants.map((t) => (
                    <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>
                  ))}
                </Select>
                <TextField
                  label="Tenant timeout (minutes)"
                  type="number"
                  size="small"
                  sx={{ width: { xs: "100%", md: 200 } }}
                  slotProps={{ htmlInput: { min: 5, max: 120 } }}
                  value={minutes}
                  onChange={(e) => setMinutes(e.target.value)}
                />
                <Button
                  variant="contained"
                  disabled={!tenant || saving || !valid(minutes)}
                  onClick={() => void save(() => updateTenantIdle(tenant, Number(minutes)))}
                >
                  Save Override
                </Button>
                <Button
                  variant="outlined"
                  disabled={!tenant || saving}
                  onClick={() => void save(() => clearTenantIdle(tenant))}
                >
                  Use Default
                </Button>
              </Stack>
            </Box>

            <Box sx={{ overflowX: "auto" }}>
              <Table size="small" sx={{ minWidth: 650 }}>
                <TableHead>
                  <TableRow sx={{ bgcolor: "#f7f9fa" }}>
                    <TableCell sx={{ fontWeight: 600 }}>Tenant</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Status</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Effective idle</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Policy</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {data?.tenants.map((t) => (
                    <TableRow key={t.id} hover>
                      <TableCell>{t.name}</TableCell>
                      <TableCell>{t.status}</TableCell>
                      <TableCell>{t.idleMinutes} min</TableCell>
                      <TableCell>{t.overrideMinutes == null ? "Inherited" : "Override"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          </Box>
          <Alert severity="info">
            Users with memberships in multiple active tenants follow the strictest effective inactivity timeout.
          </Alert>
        </Stack>
      )}
    </Box>
  );
}

export default function Page() {
  return <PolicyEditor />;
}
