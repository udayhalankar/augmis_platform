// apps/web/src/app/users/page.tsx

"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import axios from "axios";

import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputAdornment,
  InputLabel,
  ListItemText,
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

import AddOutlined from "@mui/icons-material/AddOutlined";
import ContentCopyOutlined from "@mui/icons-material/ContentCopyOutlined";
import BlockOutlined from "@mui/icons-material/BlockOutlined";
import ManageAccountsOutlined from "@mui/icons-material/ManageAccountsOutlined";
import MailOutlineOutlined from "@mui/icons-material/MailOutlineOutlined";
import PauseCircleOutlineOutlined from "@mui/icons-material/PauseCircleOutlineOutlined";
import PeopleOutlined from "@mui/icons-material/PeopleOutlined";
import PlayCircleOutlineOutlined from "@mui/icons-material/PlayCircleOutlineOutlined";
import RefreshOutlined from "@mui/icons-material/RefreshOutlined";
import ReplayOutlined from "@mui/icons-material/ReplayOutlined";
import SearchOutlined from "@mui/icons-material/SearchOutlined";

import AppShell from "@/components/app-shell";
import ProtectedRoute from "@/components/protected-route";

import {
  useTenant,
} from "@/context/tenant-context";

import {
  activateTenantUser,
  addExistingTenantUser,
  loadTenantRoles,
  loadTenantUsers,
  replaceTenantUserRoles,
  revokeTenantUser,
  suspendTenantUser,
  TenantRole,
  TenantUserMembership,
} from "@/lib/tenant-users";

import {
  createTenantInvitation,
  CreateTenantInvitationResult,
  loadTenantInvitations,
  reissueTenantInvitation,
  revokeTenantInvitation,
  TenantInvitation,
} from "@/lib/invitations";


function apiError(
  error: unknown,
  fallback: string
): string {
  if (axios.isAxiosError(error)) {
    const detail =
      error.response?.data?.detail;

    if (typeof detail === "string") {
      return detail;
    }
  }

  if (error instanceof Error) {
    return error.message;
  }

  return fallback;
}


function formatStatus(
  value: string
): string {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(
      /\b\w/g,
      (character) =>
        character.toUpperCase()
    );
}


function membershipColor(
  status: string
):
  | "success"
  | "warning"
  | "error"
  | "default" {
  const normalized =
    String(status || "")
      .toLowerCase();

  if (normalized === "active") {
    return "success";
  }

  if (normalized === "suspended") {
    return "warning";
  }

  if (normalized === "revoked") {
    return "error";
  }

  return "default";
}



function invitationEffectiveStatus(
  invitation: TenantInvitation
): string {
  const normalized =
    String(invitation.status || "")
      .toLowerCase();

  if (normalized !== "pending") {
    return normalized;
  }

  const expiresAt =
    new Date(
      invitation.expiresAt
    ).getTime();

  if (
    Number.isFinite(expiresAt) &&
    expiresAt <= Date.now()
  ) {
    return "expired";
  }

  return "pending";
}


function invitationColor(
  status: string
):
  | "success"
  | "warning"
  | "error"
  | "info"
  | "default" {
  const normalized =
    String(status || "")
      .toLowerCase();

  if (normalized === "accepted") {
    return "success";
  }

  if (normalized === "pending") {
    return "info";
  }

  if (normalized === "expired") {
    return "warning";
  }

  if (normalized === "revoked") {
    return "error";
  }

  return "default";
}


function deliveryColor(
  status: string
):
  | "success"
  | "warning"
  | "error"
  | "info"
  | "default" {
  const normalized =
    String(status || "")
      .toLowerCase();

  if (normalized === "delivered") {
    return "success";
  }

  if (
    normalized === "submitted" ||
    normalized === "sent"
  ) {
    return "info";
  }

  if (normalized === "delayed") {
    return "warning";
  }

  if (
    normalized === "failed" ||
    normalized === "bounced" ||
    normalized === "suppressed" ||
    normalized === "complained"
  ) {
    return "error";
  }

  return "default";
}


function formatDate(
  value: string
): string {
  if (!value) {
    return "—";
  }

  const date =
    new Date(value);

  if (
    Number.isNaN(
      date.getTime()
    )
  ) {
    return value;
  }

  return date.toLocaleString();
}


export default function UsersPage() {
  const {
    selectedTenant,
    selectedTenantId,
    loading: tenantLoading,
    error: tenantContextError,
  } = useTenant();

  const [
    memberships,
    setMemberships,
  ] =
    useState<
      TenantUserMembership[]
    >([]);

  const [
    roles,
    setRoles,
  ] =
    useState<TenantRole[]>([]);

  const [
    invitations,
    setInvitations,
  ] =
    useState<TenantInvitation[]>([]);

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

  const [
    message,
    setMessage,
  ] =
    useState("");

  const [
    search,
    setSearch,
  ] =
    useState("");

  const [
    busyMembershipId,
    setBusyMembershipId,
  ] =
    useState("");

  const [
    addDialogOpen,
    setAddDialogOpen,
  ] =
    useState(false);

  const [
    addEmail,
    setAddEmail,
  ] =
    useState("");

  const [
    addRoleCodes,
    setAddRoleCodes,
  ] =
    useState<string[]>([]);

  const [
    addBusy,
    setAddBusy,
  ] =
    useState(false);

  const [
    dialogError,
    setDialogError,
  ] =
    useState("");

  const [
    inviteDialogOpen,
    setInviteDialogOpen,
  ] =
    useState(false);

  const [
    inviteEmail,
    setInviteEmail,
  ] =
    useState("");

  const [
    inviteRoleCodes,
    setInviteRoleCodes,
  ] =
    useState<string[]>([]);

  const [
    inviteBusy,
    setInviteBusy,
  ] =
    useState(false);

  const [
    inviteDialogError,
    setInviteDialogError,
  ] =
    useState("");

  const [
    busyInvitationId,
    setBusyInvitationId,
  ] =
    useState("");

  const [
    createdInvitation,
    setCreatedInvitation,
  ] =
    useState<CreateTenantInvitationResult | null>(null);

  const [
    invitationLinkMode,
    setInvitationLinkMode,
  ] =
    useState<
      "created" | "reissued"
    >("created");

  const [
    roleTarget,
    setRoleTarget,
  ] =
    useState<
      TenantUserMembership | null
    >(null);

  const [
    editRoleCodes,
    setEditRoleCodes,
  ] =
    useState<string[]>([]);

  const [
    roleBusy,
    setRoleBusy,
  ] =
    useState(false);


  const loadData =
    useCallback(
      async (
        tenantId: string
      ) => {
        const cleanTenantId =
          tenantId.trim();

        if (!cleanTenantId) {
          setMemberships([]);
          setRoles([]);
          setInvitations([]);
          return;
        }

        setLoading(true);
        setError("");

        try {
          const [
            membershipRows,
            roleRows,
            invitationRows,
          ] =
            await Promise.all([
              loadTenantUsers(
                cleanTenantId
              ),
              loadTenantRoles(
                cleanTenantId
              ),
              loadTenantInvitations(
                cleanTenantId
              ),
            ]);

          setMemberships(
            membershipRows
          );

          setRoles(
            roleRows
          );

          setInvitations(
            invitationRows
          );
        } catch (loadError) {
          setMemberships([]);
          setRoles([]);
          setInvitations([]);

          setError(
            apiError(
              loadError,
              "Tenant users could not be loaded."
            )
          );
        } finally {
          setLoading(false);
        }
      },
      []
    );


  useEffect(
    () => {
      if (tenantLoading) {
        return;
      }

      setSearch("");
      setMessage("");
      setError("");
      setAddDialogOpen(false);
      setInviteDialogOpen(false);
      setCreatedInvitation(null);
      setRoleTarget(null);

      if (!selectedTenantId) {
        setMemberships([]);
        setRoles([]);
        setInvitations([]);
        return;
      }

      loadData(
        selectedTenantId
      );
    },
    [
      tenantLoading,
      selectedTenantId,
      loadData,
    ]
  );


  const filteredMemberships =
    useMemo(
      () => {
        const query =
          search
            .trim()
            .toLowerCase();

        if (!query) {
          return memberships;
        }

        return memberships.filter(
          (membership) => {
            const searchable =
              [
                membership.user.firstName,
                membership.user.lastName,
                membership.user.email,
                membership.status,
                ...membership.roles.map(
                  (role) =>
                    role.name
                ),
                ...membership.roles.map(
                  (role) =>
                    role.code
                ),
              ]
                .join(" ")
                .toLowerCase();

            return searchable.includes(
              query
            );
          }
        );
      },
      [
        memberships,
        search,
      ]
    );


  const summary =
    useMemo(
      () => ({
        total:
          memberships.length,

        active:
          memberships.filter(
            (item) =>
              item.status ===
              "active"
          ).length,

        suspended:
          memberships.filter(
            (item) =>
              item.status ===
              "suspended"
          ).length,

        revoked:
          memberships.filter(
            (item) =>
              item.status ===
              "revoked"
          ).length,
      }),
      [
        memberships,
      ]
    );


  const activeOwnerCount =
    useMemo(
      () =>
        memberships.filter(
          (membership) =>
            membership.status ===
              "active" &&
            membership.roles.some(
              (role) =>
                role.code ===
                "tenant_owner"
            )
        ).length,
      [
        memberships,
      ]
    );


  const openAddDialog =
    () => {
      const defaultRole =
        roles.find(
          (role) =>
            role.code ===
            "tenant_user"
        );

      setAddEmail("");
      setAddRoleCodes(
        defaultRole
          ? [defaultRole.code]
          : []
      );
      setDialogError("");
      setAddDialogOpen(true);
    };


  const submitAddUser =
    async () => {
      if (!selectedTenantId) {
        return;
      }

      const email =
        addEmail.trim();

      if (!email) {
        setDialogError(
          "Email is required."
        );
        return;
      }

      if (
        addRoleCodes.length ===
        0
      ) {
        setDialogError(
          "Select at least one tenant role."
        );
        return;
      }

      setAddBusy(true);
      setDialogError("");
      setError("");
      setMessage("");

      try {
        const created =
          await addExistingTenantUser(
            selectedTenantId,
            {
              email,
              roleCodes:
                addRoleCodes,
            }
          );

        setAddDialogOpen(false);

        setMessage(
          `${created.user.firstName} ${created.user.lastName} was added to the tenant.`
        );

        await loadData(
          selectedTenantId
        );
      } catch (addError) {
        setDialogError(
          apiError(
            addError,
            "User could not be added to the tenant."
          )
        );
      } finally {
        setAddBusy(false);
      }
    };


  const openInviteDialog =
    () => {
      const defaultRole =
        roles.find(
          (role) =>
            role.code ===
            "tenant_user"
        );

      setInviteEmail("");
      setInviteRoleCodes(
        defaultRole
          ? [defaultRole.code]
          : []
      );
      setInviteDialogError("");
      setInviteDialogOpen(true);
    };


  const submitInvitation =
    async () => {
      if (!selectedTenantId) {
        return;
      }

      const email =
        inviteEmail.trim();

      if (!email) {
        setInviteDialogError(
          "Email is required."
        );
        return;
      }

      if (
        inviteRoleCodes.length ===
        0
      ) {
        setInviteDialogError(
          "Select at least one tenant role."
        );
        return;
      }

      setInviteBusy(true);
      setInviteDialogError("");
      setError("");
      setMessage("");

      try {
        const created =
          await createTenantInvitation(
            selectedTenantId,
            {
              email,
              roleCodes:
                inviteRoleCodes,
            }
          );

        setInviteDialogOpen(false);

        setInvitationLinkMode(
          "created"
        );

        setCreatedInvitation(
          created
        );

        if (
          created.deliveryStatus ===
            "submitted" ||
          created.deliveryStatus ===
            "sent"
        ) {
          setMessage(
            `Invitation created for ${created.email} and submitted to the email provider.`
          );
        } else if (
          [
            "failed",
            "bounced",
            "suppressed",
            "complained",
          ].includes(
            created.deliveryStatus
          )
        ) {
          setMessage(
            `Invitation created for ${created.email}, but email delivery has a problem.`
          );
        } else {
          setMessage(
            `Invitation created for ${created.email}.`
          );
        }

        await loadData(
          selectedTenantId
        );
      } catch (inviteError) {
        setInviteDialogError(
          apiError(
            inviteError,
            "Invitation could not be created."
          )
        );
      } finally {
        setInviteBusy(false);
      }
    };


  const revokeInvitation =
    async (
      invitation: TenantInvitation
    ) => {
      if (!selectedTenantId) {
        return;
      }

      if (
        !window.confirm(
          `Revoke the invitation for ${invitation.email}?`
        )
      ) {
        return;
      }

      setBusyInvitationId(
        invitation.invitationId
      );
      setError("");
      setMessage("");

      try {
        const updated =
          await revokeTenantInvitation(
            selectedTenantId,
            invitation.invitationId
          );

        setMessage(
          `Invitation for ${updated.email} was revoked.`
        );

        await loadData(
          selectedTenantId
        );
      } catch (revokeError) {
        setError(
          apiError(
            revokeError,
            "Invitation could not be revoked."
          )
        );
      } finally {
        setBusyInvitationId("");
      }
    };
  

  const reissueInvitation =
  async (
    invitation: TenantInvitation
  ) => {
    if (!selectedTenantId) {
      return;
    }

    const effectiveStatus =
      invitationEffectiveStatus(
        invitation
      );

    if (
      effectiveStatus !==
        "pending" &&
      effectiveStatus !==
        "expired"
    ) {
      setError(
        "Only pending or expired invitations can be reissued."
      );
      return;
    }

    const deliveryRetry =
      invitation.deliveryStatus ===
      "failed";

    if (
      !window.confirm(
        deliveryRetry
          ? `Retry delivery for ${invitation.email}? This will reissue the invitation, invalidate the previous acceptance link and generate a new expiry.`
          : `Reissue the invitation for ${invitation.email}? The previous acceptance link will stop working and a new expiry will be generated.`
      )
    ) {
      return;
    }

    setBusyInvitationId(
      invitation.invitationId
    );

    setError("");
    setMessage("");

    try {
      const reissued =
        await reissueTenantInvitation(
          selectedTenantId,
          invitation.invitationId
        );

      setInvitationLinkMode(
        "reissued"
      );

      setCreatedInvitation(
        reissued
      );

      if (
        reissued.deliveryStatus ===
          "submitted" ||
        reissued.deliveryStatus ===
          "sent"
      ) {
        setMessage(
          `Invitation for ${reissued.email} was reissued and submitted to the email provider.`
        );
      } else if (
        [
          "failed",
          "bounced",
          "suppressed",
          "complained",
        ].includes(
          reissued.deliveryStatus
        )
      ) {
        setMessage(
          `Invitation for ${reissued.email} was reissued, but email delivery has a problem.`
        );
      } else {
        setMessage(
          `Invitation for ${reissued.email} was reissued.`
        );
      }

      await loadData(
        selectedTenantId
      );
    } catch (reissueError) {
      setError(
        apiError(
          reissueError,
          "Invitation could not be reissued."
        )
      );
    } finally {
      setBusyInvitationId("");
    }
  };

  const copyInvitationLink =
    async () => {
      const url =
        createdInvitation
          ?.acceptanceUrl;

      if (!url) {
        return;
      }

      try {
        await navigator.clipboard.writeText(
          url
        );

        setMessage(
          "Invitation link copied to clipboard."
        );
      } catch {
        window.prompt(
          "Copy invitation link:",
          url
        );
      }
    };


  const openRoleDialog =
    (
      membership:
        TenantUserMembership
    ) => {
      setRoleTarget(
        membership
      );

      setEditRoleCodes(
        membership.roles.map(
          (role) =>
            role.code
        )
      );

      setDialogError("");
    };


  const saveRoles =
    async () => {
      if (
        !selectedTenantId ||
        !roleTarget
      ) {
        return;
      }

      if (
        editRoleCodes.length ===
        0
      ) {
        setDialogError(
          "Select at least one tenant role."
        );
        return;
      }

      setRoleBusy(true);
      setDialogError("");
      setError("");
      setMessage("");

      try {
        const updated =
          await replaceTenantUserRoles(
            selectedTenantId,
            roleTarget.membershipId,
            {
              roleCodes:
                editRoleCodes,
            }
          );

        setRoleTarget(null);

        setMessage(
          `Roles updated for ${updated.user.firstName} ${updated.user.lastName}.`
        );

        await loadData(
          selectedTenantId
        );
      } catch (roleError) {
        setDialogError(
          apiError(
            roleError,
            "Tenant roles could not be updated."
          )
        );
      } finally {
        setRoleBusy(false);
      }
    };


  const runMembershipAction =
    async (
      membership:
        TenantUserMembership,
      action:
        | "suspend"
        | "activate"
        | "revoke"
    ) => {
      if (!selectedTenantId) {
        return;
      }

      const fullName =
        `${membership.user.firstName} ${membership.user.lastName}`.trim();

      if (
        action ===
          "suspend" &&
        !window.confirm(
          `Suspend ${fullName}'s tenant membership?`
        )
      ) {
        return;
      }

      if (
        action ===
          "revoke" &&
        !window.confirm(
          `Revoke ${fullName}'s tenant membership? The global AUGMIS user account will not be deleted.`
        )
      ) {
        return;
      }

      setBusyMembershipId(
        membership.membershipId
      );

      setError("");
      setMessage("");

      try {
        let updated:
          TenantUserMembership;

        if (
          action ===
          "suspend"
        ) {
          updated =
            await suspendTenantUser(
              selectedTenantId,
              membership.membershipId
            );
        } else if (
          action ===
          "activate"
        ) {
          updated =
            await activateTenantUser(
              selectedTenantId,
              membership.membershipId
            );
        } else {
          updated =
            await revokeTenantUser(
              selectedTenantId,
              membership.membershipId
            );
        }

        setMessage(
          `${updated.user.firstName} ${updated.user.lastName} membership is now ${formatStatus(updated.status)}.`
        );

        await loadData(
          selectedTenantId
        );
      } catch (actionError) {
        setError(
          apiError(
            actionError,
            "Tenant membership action failed."
          )
        );
      } finally {
        setBusyMembershipId("");
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
              justifyContent:
                "space-between",
              alignItems:
                "flex-start",
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
                  letterSpacing:
                    0.8,
                  mb: 0.5,
                }}
              >
                Tenant Administration
              </Typography>

              <Typography
                variant="h4"
              >
                Users
              </Typography>

              <Typography
                sx={{
                  mt: 0.5,
                  color:
                    "text.secondary",
                }}
              >
                Manage tenant memberships, roles and access lifecycle.
              </Typography>
            </Box>

            <Stack
              direction="row"
              spacing={1}
            >
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
                    loadData(
                      selectedTenantId
                    )
                }
              >
                Refresh
              </Button>

              <Button
                variant="outlined"
                startIcon={
                  <MailOutlineOutlined />
                }
                disabled={
                  loading ||
                  tenantLoading ||
                  !selectedTenantId ||
                  roles.length === 0
                }
                onClick={
                  openInviteDialog
                }
              >
                Invite User
              </Button>

              <Button
                variant="contained"
                startIcon={
                  <AddOutlined />
                }
                disabled={
                  loading ||
                  tenantLoading ||
                  !selectedTenantId ||
                  roles.length === 0
                }
                onClick={
                  openAddDialog
                }
              >
                Add Existing User
              </Button>
            </Stack>
          </Box>


          {tenantContextError ? (
            <Alert
              severity="error"
              sx={{ mb: 2 }}
            >
              {tenantContextError}
            </Alert>
          ) : !tenantLoading &&
              !selectedTenant ? (
            <Alert
              severity="warning"
              sx={{ mb: 2 }}
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
                    fontWeight: 600,
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


          {!loading &&
            selectedTenantId &&
            !error && (
            <Box
              sx={{
                display:
                  "grid",
                gridTemplateColumns:
                  {
                    xs:
                      "repeat(2, minmax(0, 1fr))",
                    md:
                      "repeat(4, minmax(0, 1fr))",
                  },
                gap: 1.5,
                mb: 2,
              }}
            >
              <SummaryCard
                label="Members"
                value={
                  summary.total
                }
              />
              <SummaryCard
                label="Active"
                value={
                  summary.active
                }
              />
              <SummaryCard
                label="Suspended"
                value={
                  summary.suspended
                }
              />
              <SummaryCard
                label="Revoked"
                value={
                  summary.revoked
                }
              />
            </Box>
          )}


          {!loading &&
            memberships.length >
              0 && (
            <Box
              sx={{
                display:
                  "flex",
                justifyContent:
                  "space-between",
                alignItems:
                  "center",
                gap: 2,
                mb: 2,
                flexWrap:
                  "wrap",
              }}
            >
              <Typography
                sx={{
                  fontSize: 14,
                  fontWeight: 600,
                }}
              >
                Tenant Members
              </Typography>

              <TextField
                size="small"
                placeholder=
                  "Search users or roles"
                value={
                  search
                }
                onChange={
                  (event) =>
                    setSearch(
                      event.target.value
                    )
                }
                slotProps={{
                  input: {
                    startAdornment: (
                      <InputAdornment
                        position="start"
                      >
                        <SearchOutlined
                          fontSize="small"
                        />
                      </InputAdornment>
                    ),
                  },
                }}
                sx={{
                  width: {
                    xs:
                      "100%",
                    sm:
                      340,
                  },
                }}
              />
            </Box>
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
          ) : !selectedTenantId ? (
            <Box
              sx={{
                minHeight: 260,
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
                textAlign:
                  "center",
                p: 4,
              }}
            >
              <Typography
                color="text.secondary"
              >
                Select an active tenant to manage users.
              </Typography>
            </Box>
          ) : !error &&
              memberships.length ===
                0 ? (
            <Box
              sx={{
                minHeight: 260,
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
                textAlign:
                  "center",
                p: 4,
              }}
            >
              <Box>
                <PeopleOutlined
                  sx={{
                    fontSize: 42,
                    color:
                      "text.secondary",
                  }}
                />
                <Typography
                  sx={{
                    mt: 1,
                    fontSize: 17,
                    fontWeight: 600,
                  }}
                >
                  No tenant members
                </Typography>
                <Typography
                  sx={{
                    mt: 0.5,
                    fontSize: 12,
                    color:
                      "text.secondary",
                  }}
                >
                  Add an existing AUGMIS user to this tenant.
                </Typography>
              </Box>
            </Box>
          ) : !error ? (
            <Box
              sx={{
                bgcolor:
                  "#ffffff",
                border:
                  "1px solid",
                borderColor:
                  "divider",
                overflowX:
                  "auto",
              }}
            >
              <Table
                size="small"
                sx={{
                  minWidth: 1050,
                }}
              >
                <TableHead>
                  <TableRow>
                    <TableCell>
                      User
                    </TableCell>
                    <TableCell>
                      Roles
                    </TableCell>
                    <TableCell>
                      Membership
                    </TableCell>
                    <TableCell>
                      User Status
                    </TableCell>
                    <TableCell>
                      Added
                    </TableCell>
                    <TableCell
                      align="right"
                    >
                      Actions
                    </TableCell>
                  </TableRow>
                </TableHead>

                <TableBody>
                  {
                    filteredMemberships.map(
                      (membership) => {
                        const isBusy =
                          busyMembershipId ===
                          membership.membershipId;

                        const isActiveOwner =
                          membership.status ===
                            "active" &&
                          membership.roles.some(
                            (role) =>
                              role.code ===
                              "tenant_owner"
                          );

                        const isLastActiveOwner =
                          isActiveOwner &&
                          activeOwnerCount ===
                            1;

                        return (
                          <TableRow
                            key={
                              membership.membershipId
                            }
                            hover
                          >
                            <TableCell>
                              <Typography
                                sx={{
                                  fontSize: 13,
                                  fontWeight: 600,
                                }}
                              >
                                {
                                  membership.user.firstName
                                }{" "}
                                {
                                  membership.user.lastName
                                }
                              </Typography>

                              <Typography
                                sx={{
                                  mt: 0.25,
                                  fontSize: 11,
                                  color:
                                    "text.secondary",
                                }}
                              >
                                {
                                  membership.user.email
                                }
                              </Typography>
                            </TableCell>

                            <TableCell>
                              <Stack
                                direction="row"
                                sx={{
                                  flexWrap: "wrap",
                                  gap: 0.5,
                                }}
                              >
                                {
                                  membership.roles.map(
                                    (role) => (
                                      <Chip
                                        key={
                                          role.id
                                        }
                                        size="small"
                                        label={
                                          role.name
                                        }
                                        variant="outlined"
                                      />
                                    )
                                  )
                                }
                              </Stack>
                            </TableCell>

                            <TableCell>
                              <Chip
                                size="small"
                                label={
                                  formatStatus(
                                    membership.status
                                  )
                                }
                                color={
                                  membershipColor(
                                    membership.status
                                  )
                                }
                                variant="outlined"
                              />

                              {isLastActiveOwner && (
                                <Typography
                                  sx={{
                                    mt: 0.5,
                                    fontSize: 9.5,
                                    color:
                                      "text.secondary",
                                  }}
                                >
                                  Last active Tenant Owner
                                </Typography>
                              )}
                            </TableCell>

                            <TableCell>
                              <Typography
                                sx={{
                                  fontSize: 11.5,
                                  fontWeight: 600,
                                }}
                              >
                                {
                                  formatStatus(
                                    membership.user.status
                                  )
                                }
                              </Typography>
                            </TableCell>

                            <TableCell>
                              <Typography
                                sx={{
                                  fontSize: 10.5,
                                  color:
                                    "text.secondary",
                                }}
                              >
                                {
                                  formatDate(
                                    membership.createdAt
                                  )
                                }
                              </Typography>
                            </TableCell>

                            <TableCell
                              align="right"
                            >
                              <Stack
                                direction="row"
                                spacing={0.75}
                                sx={{
                                  justifyContent:
                                    "flex-end",
                                }}
                              >
                                <Button
                                  size="small"
                                  variant="outlined"
                                  startIcon={
                                    <ManageAccountsOutlined />
                                  }
                                  disabled={
                                    isBusy ||
                                    membership.status ===
                                      "revoked"
                                  }
                                  onClick={
                                    () =>
                                      openRoleDialog(
                                        membership
                                      )
                                  }
                                >
                                  Roles
                                </Button>

                                {membership.status ===
                                  "active" && (
                                  <Button
                                    size="small"
                                    variant="outlined"
                                    color="warning"
                                    startIcon={
                                      <PauseCircleOutlineOutlined />
                                    }
                                    disabled={
                                      isBusy ||
                                      isLastActiveOwner
                                    }
                                    onClick={
                                      () =>
                                        runMembershipAction(
                                          membership,
                                          "suspend"
                                        )
                                    }
                                  >
                                    Suspend
                                  </Button>
                                )}

                                {(
                                  membership.status ===
                                    "suspended" ||
                                  membership.status ===
                                    "revoked"
                                ) && (
                                  <Button
                                    size="small"
                                    variant="outlined"
                                    startIcon={
                                      <PlayCircleOutlineOutlined />
                                    }
                                    disabled={
                                      isBusy
                                    }
                                    onClick={
                                      () =>
                                        runMembershipAction(
                                          membership,
                                          "activate"
                                        )
                                    }
                                  >
                                    Activate
                                  </Button>
                                )}

                                {membership.status !==
                                  "revoked" && (
                                  <Button
                                    size="small"
                                    variant="outlined"
                                    color="error"
                                    startIcon={
                                      <BlockOutlined />
                                    }
                                    disabled={
                                      isBusy ||
                                      isLastActiveOwner
                                    }
                                    onClick={
                                      () =>
                                        runMembershipAction(
                                          membership,
                                          "revoke"
                                        )
                                    }
                                  >
                                    Revoke
                                  </Button>
                                )}
                              </Stack>
                            </TableCell>
                          </TableRow>
                        );
                      }
                    )
                  }
                </TableBody>
              </Table>

              {filteredMemberships.length ===
                0 && (
                <Box
                  sx={{
                    p: 4,
                    textAlign:
                      "center",
                    color:
                      "text.secondary",
                  }}
                >
                  No users match the current search.
                </Box>
              )}
            </Box>
          ) : null}


          {!loading &&
            selectedTenantId &&
            !error && (
            <Box
              sx={{
                mt: 3,
              }}
            >
              <Box
                sx={{
                  display:
                    "flex",
                  justifyContent:
                    "space-between",
                  alignItems:
                    "center",
                  gap: 2,
                  mb: 1.5,
                  flexWrap:
                    "wrap",
                }}
              >
                <Box>
                  <Typography
                    sx={{
                      fontSize: 14,
                      fontWeight: 600,
                    }}
                  >
                    Tenant Invitations
                  </Typography>

                  <Typography
                    sx={{
                      mt: 0.25,
                      fontSize: 11,
                      color:
                        "text.secondary",
                    }}
                  >
                    Pending, accepted, expired and revoked invitations for this tenant.
                  </Typography>
                </Box>
              </Box>

              {invitations.length === 0 ? (
                <Box
                  sx={{
                    minHeight: 130,
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
                    textAlign:
                      "center",
                    p: 3,
                  }}
                >
                  <Box>
                    <MailOutlineOutlined
                      sx={{
                        fontSize: 34,
                        color:
                          "text.secondary",
                      }}
                    />
                    <Typography
                      sx={{
                        mt: 0.75,
                        fontSize: 14,
                        fontWeight: 600,
                      }}
                    >
                      No tenant invitations
                    </Typography>
                    <Typography
                      sx={{
                        mt: 0.35,
                        fontSize: 11,
                        color:
                          "text.secondary",
                      }}
                    >
                      Use Invite User to start the invitation onboarding flow.
                    </Typography>
                  </Box>
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
                    overflowX:
                      "auto",
                  }}
                >
                  <Table
                    size="small"
                    sx={{
                      minWidth: 1280,
                    }}
                  >
                    <TableHead>
                      <TableRow>
                        <TableCell>
                          Email
                        </TableCell>
                        <TableCell>
                          Roles
                        </TableCell>
                        <TableCell>
                          Account
                        </TableCell>
                        <TableCell>
                          Status
                        </TableCell>
                        <TableCell>
                          Delivery
                        </TableCell>
                        <TableCell>
                          Created
                        </TableCell>
                        <TableCell>
                          Expires
                        </TableCell>
                        <TableCell
                          align="right"
                        >
                          Actions
                        </TableCell>
                      </TableRow>
                    </TableHead>

                    <TableBody>
                      {invitations.map(
                        (invitation) => {
                          const effectiveStatus =
                            invitationEffectiveStatus(
                              invitation
                            );

                          const isBusy =
                            busyInvitationId ===
                            invitation.invitationId;

                          const canReissue =
                            effectiveStatus ===
                              "pending" ||
                            effectiveStatus ===
                              "expired";

                          const canRevoke =
                            effectiveStatus ===
                            "pending";

                          return (
                            <TableRow
                              key={
                                invitation.invitationId
                              }
                              hover
                            >
                              <TableCell>
                                <Typography
                                  sx={{
                                    fontSize: 12.5,
                                    fontWeight: 600,
                                  }}
                                >
                                  {invitation.email}
                                </Typography>
                              </TableCell>

                              <TableCell>
                                <Stack
                                  direction="row"
                                  sx={{
                                    flexWrap: "wrap",
                                    gap: 0.5,
                                  }}
                                >
                                  {invitation.roles.map(
                                    (role) => (
                                      <Chip
                                        key={
                                          role.id
                                        }
                                        size="small"
                                        label={
                                          role.name
                                        }
                                        variant="outlined"
                                      />
                                    )
                                  )}
                                </Stack>
                              </TableCell>

                              <TableCell>
                                <Typography
                                  sx={{
                                    fontSize: 11.5,
                                  }}
                                >
                                  {invitation.existingUser
                                    ? "Existing AUGMIS account"
                                    : "New AUGMIS account"}
                                </Typography>
                              </TableCell>

                              <TableCell>
                                <Chip
                                  size="small"
                                  label={
                                    formatStatus(
                                      effectiveStatus
                                    )
                                  }
                                  color={
                                    invitationColor(
                                      effectiveStatus
                                    )
                                  }
                                  variant="outlined"
                                />
                              </TableCell>

                              <TableCell>
                                <Chip
                                  size="small"
                                  label={
                                    formatStatus(
                                      invitation.deliveryStatus ||
                                      "not_attempted"
                                    )
                                  }
                                  color={
                                    deliveryColor(
                                      invitation.deliveryStatus
                                    )
                                  }
                                  variant="outlined"
                                />

                                {invitation.deliveryAttempts >
                                  0 && (
                                  <Typography
                                    sx={{
                                      mt: 0.4,
                                      fontSize: 9.5,
                                      color:
                                        "text.secondary",
                                    }}
                                  >
                                    Attempts:{" "}
                                    {
                                      invitation.deliveryAttempts
                                    }
                                    {invitation.lastSentAt
                                      ? ` · Last sent ${formatDate(
                                          invitation.lastSentAt
                                        )}`
                                      : ""}
                                  </Typography>
                                )}
                              </TableCell>

                              <TableCell>
                                <Typography
                                  sx={{
                                    fontSize: 10.5,
                                    color:
                                      "text.secondary",
                                  }}
                                >
                                  {formatDate(
                                    invitation.createdAt
                                  )}
                                </Typography>
                              </TableCell>

                              <TableCell>
                                <Typography
                                  sx={{
                                    fontSize: 10.5,
                                    color:
                                      effectiveStatus ===
                                      "expired"
                                        ? "warning.main"
                                        : "text.secondary",
                                  }}
                                >
                                  {formatDate(
                                    invitation.expiresAt
                                  )}
                                </Typography>
                              </TableCell>

                              <TableCell
  align="right"
>
  {canReissue ||
  canRevoke ? (
    <Stack
      direction="row"
      spacing={0.75}
      sx={{
        justifyContent:
          "flex-end",
      }}
    >
      {canReissue && (
        <Button
          size="small"
          variant="outlined"
          startIcon={
            <ReplayOutlined />
          }
          disabled={
            isBusy
          }
          onClick={
            () =>
              reissueInvitation(
                invitation
              )
          }
        >
          {[
            "failed",
            "bounced",
            "suppressed",
          ].includes(
            invitation.deliveryStatus
          )
            ? "Retry & Reissue"
            : "Reissue"}
        </Button>
      )}

      {canRevoke && (
        <Button
          size="small"
          variant="outlined"
          color="error"
          startIcon={
            <BlockOutlined />
          }
          disabled={
            isBusy
          }
          onClick={
            () =>
              revokeInvitation(
                invitation
              )
          }
        >
          Revoke
        </Button>
      )}
    </Stack>
  ) : (
    <Typography
      sx={{
        fontSize: 11,
        color:
          "text.secondary",
      }}
    >
      —
    </Typography>
  )}
</TableCell>

                            </TableRow>
                          );
                        }
                      )}
                    </TableBody>
                  </Table>
                </Box>
              )}
            </Box>
          )}


          <Dialog
            open={
              inviteDialogOpen
            }
            onClose={
              () => {
                if (inviteBusy) {
                  return;
                }

                setInviteDialogOpen(
                  false
                );
              }
            }
            fullWidth
            maxWidth="sm"
          >
            <DialogTitle>
              Invite User
            </DialogTitle>

            <DialogContent>
              <Typography
                sx={{
                  mb: 2.5,
                  fontSize: 12,
                  color:
                    "text.secondary",
                }}
              >
                Create a time-limited tenant invitation. Existing AUGMIS users can sign in and accept; new users can create their account from the same link.
              </Typography>

              <Stack
                spacing={2}
              >
                <TextField
                  label="Invite Email"
                  type="email"
                  fullWidth
                  autoFocus
                  value={
                    inviteEmail
                  }
                  disabled={
                    inviteBusy
                  }
                  onChange={
                    (event) =>
                      setInviteEmail(
                        event.target.value
                      )
                  }
                />

                <FormControl
                  fullWidth
                >
                  <InputLabel>
                    Tenant Roles
                  </InputLabel>

                  <Select
                    multiple
                    label="Tenant Roles"
                    value={
                      inviteRoleCodes
                    }
                    disabled={
                      inviteBusy
                    }
                    renderValue={
                      (selected) =>
                        selected
                          .map(
                            (roleCode) =>
                              roles.find(
                                (role) =>
                                  role.code ===
                                  roleCode
                              )?.name ||
                              roleCode
                          )
                          .join(", ")
                    }
                    onChange={
                      (event) => {
                        const value =
                          event.target.value;

                        setInviteRoleCodes(
                          typeof value ===
                            "string"
                            ? value.split(
                                ","
                              )
                            : value
                        );
                      }
                    }
                  >
                    {roles.map(
                      (role) => (
                        <MenuItem
                          key={
                            role.id
                          }
                          value={
                            role.code
                          }
                        >
                          <Checkbox
                            checked={
                              inviteRoleCodes.includes(
                                role.code
                              )
                            }
                          />

                          <ListItemText
                            primary={
                              role.name
                            }
                            secondary={
                              role.code
                            }
                          />
                        </MenuItem>
                      )
                    )}
                  </Select>
                </FormControl>
              </Stack>

              {inviteDialogError && (
                <Alert
                  severity="error"
                  sx={{ mt: 2 }}
                >
                  {inviteDialogError}
                </Alert>
              )}
            </DialogContent>

            <DialogActions>
              <Button
                disabled={
                  inviteBusy
                }
                onClick={
                  () =>
                    setInviteDialogOpen(
                      false
                    )
                }
              >
                Cancel
              </Button>

              <Button
                variant="contained"
                disabled={
                  inviteBusy ||
                  !inviteEmail.trim() ||
                  inviteRoleCodes.length ===
                    0
                }
                onClick={
                  submitInvitation
                }
              >
                {inviteBusy ? (
                  <>
                    <CircularProgress
                      size={14}
                      sx={{
                        mr: 1,
                        color:
                          "inherit",
                      }}
                    />
                    Creating...
                  </>
                ) : (
                  "Create Invitation"
                )}
              </Button>
            </DialogActions>
          </Dialog>


          <Dialog
            open={
              Boolean(
                createdInvitation
              )
            }
            onClose={
              () =>
                setCreatedInvitation(
                  null
                )
            }
            fullWidth
            maxWidth="sm"
          >
            <DialogTitle>
              {invitationLinkMode ===
              "reissued"
                ? "Invitation Reissued"
                : "Invitation Created"}
            </DialogTitle>

            <DialogContent>
              <Typography
                sx={{
                  mb: 2,
                  fontSize: 12,
                  color:
                    "text.secondary",
                }}
              >
                {createdInvitation
                  ?.acceptanceUrl
                  ? invitationLinkMode ===
                    "reissued"
                    ? "Copy this new acceptance link now. The previous invitation link is no longer valid. The invitation list intentionally does not expose the token again."
                    : "Copy this acceptance link now. The invitation list intentionally does not expose the original token again."
                  : createdInvitation
                        ?.deliveryStatus ===
                      "sent"
                    ? "The invitation was submitted for email delivery. Provider delivery events will update the Delivery status. For security, production does not expose the raw invitation token or acceptance link."
                    : createdInvitation
                          ?.deliveryStatus ===
                        "failed"
                      ? "The invitation was created, but email delivery failed. Reissue the invitation after the mail configuration is corrected."
                      : "The invitation was created. Email delivery was not attempted, and production does not expose the raw invitation token or acceptance link."}
              </Typography>

              <Stack
                direction="row"
                spacing={1}
                sx={{
                  mb:
                    createdInvitation
                      ?.acceptanceUrl
                      ? 2
                      : 0,
                  alignItems:
                    "center",
                  flexWrap:
                    "wrap",
                }}
              >
                <Typography
                  sx={{
                    fontSize: 11,
                    color:
                      "text.secondary",
                  }}
                >
                  Delivery
                </Typography>

                <Chip
                  size="small"
                  label={
                    formatStatus(
                      createdInvitation
                        ?.deliveryStatus ||
                      "not_attempted"
                    )
                  }
                  color={
                    deliveryColor(
                      createdInvitation
                        ?.deliveryStatus ||
                      ""
                    )
                  }
                  variant="outlined"
                />
              </Stack>

              {createdInvitation
                ?.acceptanceUrl && (
                <TextField
                  label="Acceptance Link"
                  fullWidth
                  value={
                    createdInvitation
                      .acceptanceUrl
                  }
                  slotProps={{
                    input: {
                      readOnly: true,
                    },
                  }}
                />
              )}
            </DialogContent>

            <DialogActions>
              <Button
                startIcon={
                  <ContentCopyOutlined />
                }
                disabled={
                  !createdInvitation
                    ?.acceptanceUrl
                }
                onClick={
                  copyInvitationLink
                }
              >
                Copy Link
              </Button>

              <Button
                variant="contained"
                onClick={
                  () =>
                    setCreatedInvitation(
                      null
                    )
                }
              >
                Done
              </Button>
            </DialogActions>
          </Dialog>

          <Dialog
            open={
              addDialogOpen
            }
            onClose={
              () => {
                if (addBusy) {
                  return;
                }

                setAddDialogOpen(
                  false
                );
              }
            }
            fullWidth
            maxWidth="sm"
          >
            <DialogTitle>
              Add Existing User
            </DialogTitle>

            <DialogContent>
              <Typography
                sx={{
                  mb: 2.5,
                  fontSize: 12,
                  color:
                    "text.secondary",
                }}
              >
                The user must already have an AUGMIS account. Adding a membership does not create a new login account.
              </Typography>

              <Stack
                spacing={2}
              >
                <TextField
                  label="User Email"
                  type="email"
                  fullWidth
                  autoFocus
                  value={
                    addEmail
                  }
                  disabled={
                    addBusy
                  }
                  onChange={
                    (event) =>
                      setAddEmail(
                        event.target.value
                      )
                  }
                />

                <FormControl
                  fullWidth
                >
                  <InputLabel>
                    Tenant Roles
                  </InputLabel>

                  <Select
                    multiple
                    label="Tenant Roles"
                    value={
                      addRoleCodes
                    }
                    disabled={
                      addBusy
                    }
                    renderValue={
                      (selected) =>
                        selected
                          .map(
                            (roleCode) =>
                              roles.find(
                                (role) =>
                                  role.code ===
                                  roleCode
                              )?.name ||
                              roleCode
                          )
                          .join(", ")
                    }
                    onChange={
                      (event) => {
                        const value =
                          event.target.value;

                        setAddRoleCodes(
                          typeof value ===
                            "string"
                            ? value.split(
                                ","
                              )
                            : value
                        );
                      }
                    }
                  >
                    {
                      roles.map(
                        (role) => (
                          <MenuItem
                            key={
                              role.id
                            }
                            value={
                              role.code
                            }
                          >
                            <Checkbox
                              checked={
                                addRoleCodes.includes(
                                  role.code
                                )
                              }
                            />

                            <ListItemText
                              primary={
                                role.name
                              }
                              secondary={
                                role.code
                              }
                            />
                          </MenuItem>
                        )
                      )
                    }
                  </Select>
                </FormControl>
              </Stack>

              {dialogError && (
                <Alert
                  severity="error"
                  sx={{ mt: 2 }}
                >
                  {dialogError}
                </Alert>
              )}
            </DialogContent>

            <DialogActions>
              <Button
                disabled={
                  addBusy
                }
                onClick={
                  () =>
                    setAddDialogOpen(
                      false
                    )
                }
              >
                Cancel
              </Button>

              <Button
                variant="contained"
                disabled={
                  addBusy ||
                  !addEmail.trim() ||
                  addRoleCodes.length ===
                    0
                }
                onClick={
                  submitAddUser
                }
              >
                {addBusy ? (
                  <>
                    <CircularProgress
                      size={14}
                      sx={{
                        mr: 1,
                        color:
                          "inherit",
                      }}
                    />
                    Adding...
                  </>
                ) : (
                  "Add User"
                )}
              </Button>
            </DialogActions>
          </Dialog>


          <Dialog
            open={
              Boolean(
                roleTarget
              )
            }
            onClose={
              () => {
                if (roleBusy) {
                  return;
                }

                setRoleTarget(
                  null
                );
              }
            }
            fullWidth
            maxWidth="sm"
          >
            <DialogTitle>
              Edit Tenant Roles
            </DialogTitle>

            <DialogContent>
              <Typography
                sx={{
                  mb: 2.5,
                  fontSize: 12,
                  color:
                    "text.secondary",
                }}
              >
                {roleTarget
                  ? `${roleTarget.user.firstName} ${roleTarget.user.lastName} — ${roleTarget.user.email}`
                  : ""}
              </Typography>

              <FormControl
                fullWidth
              >
                <InputLabel>
                  Tenant Roles
                </InputLabel>

                <Select
                  multiple
                  label="Tenant Roles"
                  value={
                    editRoleCodes
                  }
                  disabled={
                    roleBusy
                  }
                  renderValue={
                    (selected) =>
                      selected
                        .map(
                          (roleCode) =>
                            roles.find(
                              (role) =>
                                role.code ===
                                roleCode
                            )?.name ||
                            roleCode
                        )
                        .join(", ")
                  }
                  onChange={
                    (event) => {
                      const value =
                        event.target.value;

                      setEditRoleCodes(
                        typeof value ===
                          "string"
                          ? value.split(
                              ","
                            )
                          : value
                      );
                    }
                  }
                >
                  {
                    roles.map(
                      (role) => (
                        <MenuItem
                          key={
                            role.id
                          }
                          value={
                            role.code
                          }
                        >
                          <Checkbox
                            checked={
                              editRoleCodes.includes(
                                role.code
                              )
                            }
                          />

                          <ListItemText
                            primary={
                              role.name
                            }
                            secondary={
                              role.code
                            }
                          />
                        </MenuItem>
                      )
                    )
                  }
                </Select>
              </FormControl>

              {dialogError && (
                <Alert
                  severity="error"
                  sx={{ mt: 2 }}
                >
                  {dialogError}
                </Alert>
              )}
            </DialogContent>

            <DialogActions>
              <Button
                disabled={
                  roleBusy
                }
                onClick={
                  () =>
                    setRoleTarget(
                      null
                    )
                }
              >
                Cancel
              </Button>

              <Button
                variant="contained"
                disabled={
                  roleBusy ||
                  editRoleCodes.length ===
                    0
                }
                onClick={
                  saveRoles
                }
              >
                {roleBusy ? (
                  <>
                    <CircularProgress
                      size={14}
                      sx={{
                        mr: 1,
                        color:
                          "inherit",
                      }}
                    />
                    Saving...
                  </>
                ) : (
                  "Save Roles"
                )}
              </Button>
            </DialogActions>
          </Dialog>

        </Box>
      </AppShell>
    </ProtectedRoute>
  );
}


function SummaryCard({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  return (
    <Box
      sx={{
        bgcolor:
          "#ffffff",
        border:
          "1px solid",
        borderColor:
          "divider",
        px: 2,
        py: 1.5,
      }}
    >
      <Typography
        sx={{
          fontSize: 10,
          color:
            "text.secondary",
          textTransform:
            "uppercase",
          letterSpacing:
            0.5,
        }}
      >
        {label}
      </Typography>

      <Typography
        sx={{
          mt: 0.25,
          fontSize: 22,
          fontWeight: 600,
        }}
      >
        {value}
      </Typography>
    </Box>
  );
}
