"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  AdminPanelSettingsOutlined,
  EmailOutlined,
  SettingsOutlined,
} from "@mui/icons-material";
import { Alert, Box, Stack, Typography } from "@mui/material";
import AppShell from "@/components/app-shell";
import ProtectedRoute from "@/components/protected-route";
import { usePermissions } from "@/context/permission-context";

type Area = "overview" | "platform" | "email" | "rbac";

type AdministrationSection = {
  area: Exclude<Area, "overview">;
  label: string;
  description: string;
  href: string;
  icon: ReactNode;
};

const navigation: AdministrationSection[] = [
  {
    area: "platform",
    label: "Platform Settings",
    description: "Session and tenant policies",
    href: "/settings/security",
    icon: <SettingsOutlined fontSize="small" />,
  },
  {
    area: "email",
    label: "Email Delivery",
    description: "SMTP and delivery controls",
    href: "/settings/email",
    icon: <EmailOutlined fontSize="small" />,
  },
  {
    area: "rbac",
    label: "RBAC Administration",
    description: "Roles and permissions",
    href: "/settings/rbac",
    icon: <AdminPanelSettingsOutlined fontSize="small" />,
  },
];

/** One authenticated AppShell for the entire /settings route tree. */
export default function AdministrationLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { hasPlatformPermission } = usePermissions();
  const canManageSettings = hasPlatformPermission("platform.settings.manage");
  const canManageRbac = hasPlatformPermission("platform.rbac.manage");

  const area: Area = pathname.startsWith("/settings/security")
    ? "platform"
    : pathname.startsWith("/settings/email")
      ? "email"
      : pathname.startsWith("/settings/rbac")
        ? "rbac"
        : "overview";

  const allowed = area === "rbac"
    ? canManageRbac
    : area === "overview"
      ? canManageSettings || canManageRbac
      : canManageSettings;

  const visibleItems = navigation.filter((item) =>
    item.area === "rbac" ? canManageRbac : canManageSettings,
  );

  // One canonical Administration page header. Subpages own only their work controls.
  const sectionMeta = {
    platform: {
      title: "Platform Settings",
      description: "Configure session inactivity, tenant overrides and platform security controls.",
    },
    email: {
      title: "Email Delivery",
      description: "Configure transactional email for invitations and platform notifications.",
    },
    rbac: {
      title: "RBAC Administration",
      description: "Review roles and manage role-permission assignments across AUGMIS security scopes.",
    },
  } as const;
  const currentSection = area === "overview" ? null : sectionMeta[area];

  return (
    <ProtectedRoute>
      <AppShell>
        <Stack spacing={3}>
          {/* Same eyebrow / h4 / subtitle structure as Publisher Center. */}
          <Box>
            <Typography sx={{ fontSize: 12, color: "text.secondary", textTransform: "uppercase", letterSpacing: 0.8, mb: 0.5 }}>
              Platform Workspace
            </Typography>
            <Typography variant="h4">AUGMIS Administration</Typography>
            <Typography sx={{ mt: 0.5, color: "text.secondary" }}>
              Manage platform security, email delivery and role-based access controls.
            </Typography>
          </Box>

          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "minmax(0, 1fr)", lg: "330px minmax(0, 1fr)" }, gap: 2, alignItems: "start" }}>
            <Box component="nav" aria-label="Administration sections" sx={{ bgcolor: "background.paper", border: "1px solid", borderColor: "divider", minWidth: 0 }}>
              <Box component={Link} href="/settings" sx={{ display: "block", px: 2.5, py: 1.8, textDecoration: "none", color: "text.primary", borderBottom: "1px solid", borderColor: "divider", "&:hover": { bgcolor: "#f8fafb" } }}>
                <Typography sx={{ fontWeight: 600 }}>Administration</Typography>
                <Typography sx={{ mt: 0.25, fontSize: 12, color: "text.secondary" }}>
                  Platform configuration
                </Typography>
              </Box>

              <Box sx={{ display: { xs: "flex", lg: "block" }, overflowX: { xs: "auto", lg: "visible" } }}>
                {visibleItems.map((item, index) => {
                  const selected = area === item.area;
                  return (
                    <Box
                      component={Link}
                      key={item.area}
                      href={item.href}
                      aria-current={selected ? "page" : undefined}
                      sx={{
                        display: "flex", alignItems: "center", gap: 1.5,
                        flexShrink: 0, minWidth: { xs: 190, lg: 0 },
                        px: 2.5, py: 2, textDecoration: "none",
                        bgcolor: selected ? "#edf4f8" : "background.paper",
                        color: selected ? "primary.main" : "text.primary",
                        borderLeft: selected ? "3px solid" : "3px solid transparent",
                        borderLeftColor: selected ? "primary.main" : "transparent",
                        borderBottom: index < visibleItems.length - 1 ? "1px solid" : "none",
                        borderBottomColor: "divider",
                        "&:hover": { bgcolor: selected ? "#edf4f8" : "#f8fafb" },
                        "&:focus-visible": { outline: "2px solid", outlineColor: "primary.main", outlineOffset: -2 },
                      }}
                    >
                      <Box aria-hidden="true" sx={{ color: selected ? "primary.main" : "text.secondary", display: "flex" }}>
                        {item.icon}
                      </Box>
                      <Box sx={{ minWidth: 0 }}>
                        <Typography sx={{ fontSize: 14, fontWeight: selected ? 600 : 500 }}>
                          {item.label}
                        </Typography>
                        <Typography sx={{ mt: 0.4, fontSize: 11, color: "text.secondary" }}>
                          {item.description}
                        </Typography>
                      </Box>
                    </Box>
                  );
                })}
              </Box>
            </Box>

            <Box component="section" aria-label="Administration content" sx={{ minWidth: 0, "& .MuiPaper-root": { boxShadow: "none", border: "1px solid", borderColor: "divider", borderRadius: 0 } }}>
              {allowed ? (
                <Stack spacing={2}>
                  {currentSection && (
                    <Box>
                      <Typography sx={{ fontSize: 12, color: "text.secondary", textTransform: "uppercase", letterSpacing: 0.8, mb: 0.5 }}>
                        Platform Administration
                      </Typography>
                      <Typography variant="h4">{currentSection.title}</Typography>
                      <Typography sx={{ mt: 0.5, color: "text.secondary" }}>{currentSection.description}</Typography>
                    </Box>
                  )}
                  {children}
                </Stack>
              ) : (
                <Alert severity="error">You do not have permission to access this administration section.</Alert>
              )}
            </Box>
          </Box>
        </Stack>
      </AppShell>
    </ProtectedRoute>
  );
}
