"use client";
import Link from "next/link";
import { Box, Paper, Stack, Typography, Button } from "@mui/material";
import { usePermissions } from "@/context/permission-context";

function AdminHome() {
  const { hasPlatformPermission } = usePermissions();
  const settings = hasPlatformPermission("platform.settings.manage");
  const rbac = hasPlatformPermission("platform.rbac.manage");
  return <Box>
    <Box sx={{ bgcolor: "background.paper", border: "1px solid", borderColor: "divider", px: 2.5, py: 2, mb: 2 }}>
      <Typography sx={{ fontWeight: 600 }}>Administration Overview</Typography>
      <Typography sx={{ mt: 0.25, fontSize: 12, color: "text.secondary" }}>Select a configuration area to manage platform services.</Typography>
    </Box>
    <Stack spacing={2}>
      {settings && <Paper variant="outlined" sx={{ p: 3, borderRadius: 0 }}><Typography variant="h6">Platform Settings</Typography>
        <Typography sx={{ my: 1 }}>Server-enforced session inactivity policies and tenant overrides.</Typography>
        <Button component={Link} href="/settings/security">Manage Session Security</Button>
      </Paper>}
      {settings && <Paper variant="outlined" sx={{ p: 3, borderRadius: 0 }}><Typography variant="h6">Email Delivery</Typography>
        <Typography sx={{ my: 1 }}>Existing platform delivery configuration and delivery status.</Typography>
        <Button component={Link} href="/settings/email">Open Email Settings</Button>
      </Paper>}
      {rbac && <Paper variant="outlined" sx={{ p: 3, borderRadius: 0 }}><Typography variant="h6">RBAC Administration</Typography>
        <Typography sx={{ my: 1 }}>Existing role, permission and assignment administration.</Typography>
        <Button component={Link} href="/settings/rbac">Open RBAC</Button>
      </Paper>}
      {!settings && !rbac && <Typography color="error">You do not have platform administration permission.</Typography>}
    </Stack>
  </Box>;
}
export default function Page() { return <AdminHome/>; }
