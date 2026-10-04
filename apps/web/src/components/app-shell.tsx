"use client";

import {
  AppsOutlined,
  DashboardOutlined,
  DomainOutlined,
  GridViewOutlined,
  HistoryOutlined,
  Inventory2Outlined,
  LogoutOutlined,
  MenuOutlined,
  NotificationsNoneOutlined,
  PeopleOutlined,
  SettingsOutlined,
  StorefrontOutlined,
} from "@mui/icons-material";

import {
  Avatar,
  Box,
  IconButton,
  Stack,
  Typography,
} from "@mui/material";

import {  usePathname, useRouter } from "next/navigation";

import type { ReactNode } from "react";

import {
  useAuth,
} from "@/context/auth-context";

import TenantSelector
  from "@/components/tenant-selector";

const navigation = [
  {
    label: "Control Center",
    href: "/",
    icon: (
      <DashboardOutlined
        fontSize="small"
      />
    ),
  },
  {
    label: "Applications",
    href: "/publisher",
    icon: (
      <AppsOutlined
        fontSize="small"
      />
    ),
  },
  {
    label: "Marketplace",
    href: "/marketplace",
    icon: (
      <StorefrontOutlined
        fontSize="small"
      />
    ),
  },
  {
    label: "Subscriptions",
    href: "/subscriptions",
    icon: (
      <Inventory2Outlined
        fontSize="small"
      />
    ),
  },
  {
    label: "Tenants",
    href: "/tenants",
    icon: (
      <DomainOutlined
        fontSize="small"
      />
    ),
  },
  {
    label: "Runtime",
    href: "/runtime",
    icon: (
      <GridViewOutlined
        fontSize="small"
      />
    ),
  },
  {
    label: "Users",
    href: "/users",
    icon: (
      <PeopleOutlined
        fontSize="small"
      />
    ),
  },
  {
    label: "Audit",
    href: "/audit",
    icon: (
      <HistoryOutlined
        fontSize="small"
      />
    ),
  },
];


type PlatformHealth = {
  api: boolean;
  database: boolean;
  docker: boolean;
};


type AppShellProps = {
  children: ReactNode;
  platformHealth?: PlatformHealth;
};


export default function AppShell({
  children,
  platformHealth,
}: AppShellProps) {

  const router = useRouter();
  const pathname = usePathname();

  const {
    user,
    logout,
  } = useAuth();


  const handleLogout = () => {

    logout();

    router.replace(
      "/login"
    );
  };


  const initials = user
    ? (
        `${user.first_name.charAt(0)}${user.last_name.charAt(0)}`
      ).toUpperCase()
    : "AU";


  return (
    <Box
      sx={{
        minHeight: "100vh",
        bgcolor:
          "background.default",
      }}
    >

      {/* ================================================
          TOP BRAND BAR
      ================================================= */}

      <Box
        sx={{
          height: 64,
          bgcolor: "#ffffff",

          borderBottom:
            "1px solid",

          borderColor:
            "divider",

          display: "flex",

          alignItems:
            "center",

          px: 3,
        }}
      >

        <Stack
          direction="row"
          spacing={2}
          sx={{
            alignItems:
              "center",

            flex: 1,
          }}
        >

          <IconButton
            size="small"
          >
            <MenuOutlined />
          </IconButton>


          <Box
            sx={{
              width: 34,
              height: 34,

              bgcolor:
                "primary.main",

              color: "#ffffff",

              display: "grid",

              placeItems:
                "center",

              fontSize: 13,

              fontWeight: 700,

              letterSpacing:
                0.5,
            }}
          >
            AU
          </Box>


          <Box>

            <Typography
              sx={{
                fontSize: 18,

                fontWeight:
                  650,

                lineHeight:
                  1.1,
              }}
            >
              AUGMIS
            </Typography>


            <Typography
              sx={{
                fontSize: 11,

                color:
                  "text.secondary",

                letterSpacing:
                  0.6,
              }}
            >
              PLATFORM CONTROL PLANE
            </Typography>

          </Box>

        </Stack>


        <Stack
          direction="row"
          spacing={1}
          sx={{
            alignItems:
              "center",
          }}
        >
<TenantSelector />
          <Box
            sx={{
              px: 1.5,
              py: 0.6,

              border:
                "1px solid",

              borderColor:
                "divider",

              fontSize: 12,

              color:
                "text.secondary",
            }}
          >
            Development
          </Box>


          <IconButton
            aria-label="Notifications"
          >
            <NotificationsNoneOutlined />
          </IconButton>


          <IconButton
            aria-label="Settings"
            onClick={() =>
              router.push(
                "/settings/email"
              )
            }
          >
            <SettingsOutlined />
          </IconButton>


          <Box
            sx={{
              width: 1,

              height: 28,

              bgcolor:
                "divider",

              mx: 1,
            }}
          />


          <Avatar
            sx={{
              width: 34,
              height: 34,

              fontSize: 12,
            }}
          >
            {initials}
          </Avatar>


          <Box
            sx={{
              display: {
                xs: "none",
                md: "block",
              },
            }}
          >

            <Typography
              sx={{
                fontSize: 13,

                fontWeight:
                  600,
              }}
            >
              {user
                ? `${user.first_name} ${user.last_name}`
                : "AUGMIS User"}
            </Typography>


            <Typography
              sx={{
                fontSize: 11,

                color:
                  "text.secondary",
              }}
            >
              {user?.email}
            </Typography>

          </Box>


          <IconButton
            size="small"
            onClick={
              handleLogout
            }
            aria-label="Sign out"
          >
            <LogoutOutlined
              fontSize="small"
            />
          </IconButton>

        </Stack>

      </Box>


      {/* ================================================
          HORIZONTAL NAVIGATION
      ================================================= */}

      <Box
        sx={{
          bgcolor: "#ffffff",

          borderBottom:
            "1px solid",

          borderColor:
            "divider",

          px: 3,

          overflowX:
            "auto",
        }}
      >

        <Stack
          direction="row"
          spacing={0}
        >

          {navigation.map(
  (item) => {

    const active =
      item.href === "/"
        ? pathname === "/"
        : pathname.startsWith(
            item.href
          );

    return (
      <Box
        key={item.label}
        onClick={() =>
          router.push(
            item.href
          )
        }
        sx={{
          minHeight: 48,

          px: 2,

          display: "flex",

          gap: 1,

          alignItems: "center",

          borderBottom:
            active
              ? "3px solid #1f5f8b"
              : "3px solid transparent",

          color:
            active
              ? "primary.main"
              : "text.secondary",

          cursor: "pointer",

          userSelect: "none",

          "&:hover": {
            bgcolor:
              "#f6f8fa",

            color:
              "text.primary",
          },
        }}
      >
        {item.icon}

        <Typography
          sx={{
            fontSize: 13,

            fontWeight:
              active
                ? 600
                : 500,

            whiteSpace:
              "nowrap",
          }}
        >
          {item.label}
        </Typography>
      </Box>
    );
  }
)}

        </Stack>

      </Box>


      {/* ================================================
          STATUS STRIP
      ================================================= */}

      <Box
        sx={{
          minHeight: 34,

          px: 3,

          bgcolor:
            "#edf3f7",

          borderBottom:
            "1px solid",

          borderColor:
            "#d7e2e9",

          display:
            "flex",

          alignItems:
            "center",
        }}
      >

        <Stack
          direction="row"
          spacing={3}
          sx={{
            alignItems:
              "center",

            flexWrap:
              "wrap",

            py: 0.5,
          }}
        >

          <Typography
  sx={{
    fontSize: 11,

    color:
      platformHealth?.api
        ? "#397451"
        : platformHealth
          ? "#b44545"
          : "text.secondary",
  }}
>
  {platformHealth
    ? (
        platformHealth.api
          ? "● API Healthy"
          : "● API Unavailable"
      )
    : "● API Checking"}
</Typography>


<Typography
  sx={{
    fontSize: 11,

    color:
      platformHealth?.database
        ? "#397451"
        : platformHealth
          ? "#b44545"
          : "text.secondary",
  }}
>
  {platformHealth
    ? (
        platformHealth.database
          ? "● Database Up"
          : "● Database Down"
      )
    : "● Database Checking"}
</Typography>


<Typography
  sx={{
    fontSize: 11,

    color:
      platformHealth?.docker
        ? "#397451"
        : platformHealth
          ? "#b44545"
          : "text.secondary",
  }}
>
  {platformHealth
    ? (
        platformHealth.docker
          ? "● Runtime Ready"
          : "● Runtime Unavailable"
      )
    : "● Runtime Checking"}

</Typography>


          <Typography
            sx={{
              fontSize: 11,

              color:
                "text.secondary",
            }}
          >
            Environment: Development
          </Typography>

        </Stack>

      </Box>


      {/* ================================================
          WORKSPACE
      ================================================= */}

      <Box
        component="main"
        sx={{
          px: {
            xs: 2,
            md: 3,
          },

          py: 3,
        }}
      >
        {children}
      </Box>

    </Box>
  );
}