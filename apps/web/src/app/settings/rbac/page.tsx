// apps/web/src/app/settings/rbac/page.tsx

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
  Divider,
  FormControlLabel,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";

import {
  AdminPanelSettingsOutlined,
  LockOutlined,
  RefreshOutlined,
  SaveOutlined,
} from "@mui/icons-material";

import AppShell
  from "@/components/app-shell";

import PermissionGuard
  from "@/components/permission-guard";

import ProtectedRoute
  from "@/components/protected-route";

import {
  loadRbacPermissions,
  loadRbacRoles,
  RbacPermission,
  RbacRole,
  RbacScope,
  replaceRbacRolePermissions,
} from "@/lib/rbac";


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
      error.response
        ?.data
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


function formatScope(
  scope: RbacScope
): string {

  if (
    scope === "platform"
  ) {
    return "Platform";
  }

  if (
    scope === "publisher"
  ) {
    return "Publisher";
  }

  return "Tenant";
}


export default function RbacPage() {

  const [
    scope,
    setScope,
  ] =
    useState<RbacScope>(
      "tenant"
    );


  const [
    roles,
    setRoles,
  ] =
    useState<RbacRole[]>([]);


  const [
    permissions,
    setPermissions,
  ] =
    useState<RbacPermission[]>([]);


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
    selectedRole,
    setSelectedRole,
  ] =
    useState<RbacRole | null>(
      null
    );


  const [
    selectedPermissionCodes,
    setSelectedPermissionCodes,
  ] =
    useState<string[]>([]);


  const [
    saving,
    setSaving,
  ] =
    useState(false);


  const loadData =
    useCallback(
      async (
        targetScope:
          RbacScope
      ) => {

        setLoading(true);
        setError("");

        try {

          const [
            roleRows,
            permissionRows,
          ] =
            await Promise.all([
              loadRbacRoles(
                targetScope
              ),

              loadRbacPermissions(
                targetScope
              ),
            ]);


          setRoles(
            roleRows
          );

          setPermissions(
            permissionRows
          );

        } catch (loadError) {

          setRoles([]);
          setPermissions([]);

          setError(
            apiError(
              loadError,
              "RBAC configuration could not be loaded."
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

      setSelectedRole(
        null
      );

      setMessage("");

      void loadData(
        scope
      );
    },
    [
      scope,
      loadData,
    ]
  );


  const sortedPermissions =
    useMemo(
      () =>
        [...permissions]
          .sort(
            (a, b) =>
              a.code.localeCompare(
                b.code
              )
          ),
      [
        permissions,
      ]
    );


  const openRole =
    (
      role: RbacRole
    ) => {

      if (
        role.protected
      ) {
        return;
      }

      setSelectedRole(
        role
      );

      setSelectedPermissionCodes(
        role.permissions.map(
          (permission) =>
            permission.code
        )
      );

      setError("");
    };


  const togglePermission =
    (
      permissionCode:
        string
    ) => {

      setSelectedPermissionCodes(
        (current) => {

          if (
            current.includes(
              permissionCode
            )
          ) {

            return current.filter(
              (code) =>
                code !==
                permissionCode
            );
          }

          return [
            ...current,
            permissionCode,
          ];
        }
      );
    };


  const saveRolePermissions =
    async () => {

      if (
        !selectedRole
      ) {
        return;
      }


      setSaving(true);
      setError("");
      setMessage("");

      try {

        const updated =
          await replaceRbacRolePermissions(
            selectedRole.id,
            {
              permissionCodes:
                selectedPermissionCodes,
            }
          );


        setRoles(
          (current) =>
            current.map(
              (role) =>
                role.id ===
                updated.id
                  ? updated
                  : role
            )
        );


        setSelectedRole(
          null
        );


        setMessage(
          `Permissions updated for ${updated.name}.`
        );

      } catch (saveError) {

        setError(
          apiError(
            saveError,
            "Role permissions could not be updated."
          )
        );

      } finally {

        setSaving(false);
      }
    };


  return (
    <ProtectedRoute>

      <AppShell>

        <PermissionGuard
          scope="platform"
          permission=
            "platform.rbac.manage"
        >

          <Box>

            <Box
              sx={{
                display: "flex",
                justifyContent:
                  "space-between",
                alignItems:
                  "flex-start",
                gap: 2,
                flexWrap: "wrap",
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
                  Platform Administration
                </Typography>

                <Typography
                  variant="h4"
                >
                  RBAC Administration
                </Typography>

                <Typography
                  sx={{
                    mt: 0.5,
                    color:
                      "text.secondary",
                  }}
                >
                  Review roles and manage
                  role-permission assignments
                  across AUGMIS security scopes.
                </Typography>

              </Box>


              <Button
                variant="outlined"
                startIcon={
                  <RefreshOutlined />
                }
                disabled={
                  loading
                }
                onClick={
                  () =>
                    loadData(
                      scope
                    )
                }
              >
                Refresh
              </Button>

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
                  px: 2,
                  pt: 1,
                }}
              >

                <Tabs
                  value={
                    scope
                  }
                  onChange={
                    (
                      _event,
                      value:
                        RbacScope
                    ) =>
                      setScope(
                        value
                      )
                  }
                >
                  <Tab
                    value="tenant"
                    label="Tenant"
                  />

                  <Tab
                    value="publisher"
                    label="Publisher"
                  />

                  <Tab
                    value="platform"
                    label="Platform"
                  />
                </Tabs>

              </Box>

              <Divider />


              {loading ? (

                <Box
                  sx={{
                    minHeight: 280,
                    display: "grid",
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
                    display:
                      "grid",

                    gridTemplateColumns:
                      {
                        xs: "1fr",

                        lg:
                          "minmax(340px, 0.8fr) minmax(500px, 1.2fr)",
                      },

                    minHeight: 420,
                  }}
                >

                  <Box
                    sx={{
                      borderRight:
                        {
                          xs: "none",
                          lg:
                            "1px solid",
                        },

                      borderColor:
                        "divider",
                    }}
                  >

                    <Box
                      sx={{
                        px: 2,
                        py: 1.5,
                        bgcolor:
                          "#f8fafb",
                        borderBottom:
                          "1px solid",
                        borderColor:
                          "divider",
                      }}
                    >
                      <Typography
                        sx={{
                          fontSize: 13,
                          fontWeight:
                            650,
                        }}
                      >
                        {formatScope(
                          scope
                        )} Roles
                      </Typography>
                    </Box>


                    {roles.length ===
                    0 ? (

                      <Box
                        sx={{
                          p: 3,
                          color:
                            "text.secondary",
                        }}
                      >
                        No roles found.
                      </Box>

                    ) : (

                      roles.map(
                        (
                          role
                        ) => (

                          <Box
                            key={
                              role.id
                            }
                            sx={{
                              px: 2,
                              py: 1.5,

                              borderBottom:
                                "1px solid",

                              borderColor:
                                "divider",

                              display:
                                "flex",

                              justifyContent:
                                "space-between",

                              gap: 2,

                              alignItems:
                                "center",

                              "&:hover":
                                {
                                  bgcolor:
                                    "#fafcfd",
                                },
                            }}
                          >

                            <Box>

                              <Stack
                                direction="row"
                                spacing={1}
                                sx={{
                                  alignItems:
                                    "center",

                                  flexWrap:
                                    "wrap",
                                }}
                              >

                                <Typography
                                  sx={{
                                    fontSize:
                                      13,

                                    fontWeight:
                                      650,
                                  }}
                                >
                                  {
                                    role.name
                                  }
                                </Typography>


                                {role.protected && (
                                  <Chip
                                    size="small"
                                    icon={
                                      <LockOutlined />
                                    }
                                    label=
                                      "Protected"
                                    variant=
                                      "outlined"
                                  />
                                )}

                              </Stack>


                              <Typography
                                sx={{
                                  mt: 0.35,

                                  fontSize:
                                    10.5,

                                  color:
                                    "text.secondary",

                                  fontFamily:
                                    "monospace",
                                }}
                              >
                                {
                                  role.code
                                }
                              </Typography>


                              <Typography
                                sx={{
                                  mt: 0.45,

                                  fontSize:
                                    10.5,

                                  color:
                                    "text.secondary",
                                }}
                              >
                                {
                                  role
                                    .permissions
                                    .length
                                }{" "}
                                permissions
                              </Typography>

                            </Box>


                            <Button
                              size="small"
                              variant=
                                "outlined"
                              startIcon={
                                <AdminPanelSettingsOutlined />
                              }
                              disabled={
                                role.protected
                              }
                              onClick={
                                () =>
                                  openRole(
                                    role
                                  )
                              }
                            >
                              Permissions
                            </Button>

                          </Box>
                        )
                      )
                    )}

                  </Box>


                  <Box>

                    <Box
                      sx={{
                        px: 2,
                        py: 1.5,
                        bgcolor:
                          "#f8fafb",
                        borderBottom:
                          "1px solid",
                        borderColor:
                          "divider",
                      }}
                    >
                      <Typography
                        sx={{
                          fontSize: 13,
                          fontWeight:
                            650,
                        }}
                      >
                        Permission Catalogue
                      </Typography>
                    </Box>


                    <Box
                      sx={{
                        p: 2,
                        display: "flex",
                        flexWrap: "wrap",
                        gap: 1,
                      }}
                    >

                      {sortedPermissions.map(
                        (
                          permission
                        ) => (
                          <Chip
                            key={
                              permission.id
                            }
                            label={
                              permission.code
                            }
                            variant=
                              "outlined"
                          />
                        )
                      )}

                    </Box>

                  </Box>

                </Box>
              )}

            </Box>


            <Dialog
              open={
                Boolean(
                  selectedRole
                )
              }
              onClose={
                () => {

                  if (
                    saving
                  ) {
                    return;
                  }

                  setSelectedRole(
                    null
                  );
                }
              }
              fullWidth
              maxWidth="md"
            >

              <DialogTitle>
                Role Permissions
              </DialogTitle>


              <DialogContent>

                <Typography
                  sx={{
                    fontSize: 14,
                    fontWeight: 650,
                  }}
                >
                  {
                    selectedRole
                      ?.name
                  }
                </Typography>


                <Typography
                  sx={{
                    mt: 0.25,
                    mb: 2.5,

                    fontSize: 11,

                    color:
                      "text.secondary",

                    fontFamily:
                      "monospace",
                  }}
                >
                  {
                    selectedRole
                      ?.code
                  }
                </Typography>


                <Box
                  sx={{
                    border:
                      "1px solid",

                    borderColor:
                      "divider",
                  }}
                >

                  {sortedPermissions.map(
                    (
                      permission,
                      index
                    ) => (

                      <Box
                        key={
                          permission.id
                        }
                      >

                        {index >
                          0 && (
                          <Divider />
                        )}


                        <Box
                          sx={{
                            px: 2,
                            py: 1,
                          }}
                        >

                          <FormControlLabel
                            control={
                              <Checkbox
                                checked={
                                  selectedPermissionCodes.includes(
                                    permission.code
                                  )
                                }
                                disabled={
                                  saving
                                }
                                onChange={
                                  () =>
                                    togglePermission(
                                      permission.code
                                    )
                                }
                              />
                            }
                            label={
                              <Box>

                                <Typography
                                  sx={{
                                    fontSize:
                                      12.5,

                                    fontWeight:
                                      600,
                                  }}
                                >
                                  {
                                    permission.name
                                  }
                                </Typography>

                                <Typography
                                  sx={{
                                    fontSize:
                                      10.5,

                                    color:
                                      "text.secondary",

                                    fontFamily:
                                      "monospace",
                                  }}
                                >
                                  {
                                    permission.code
                                  }
                                </Typography>

                              </Box>
                            }
                          />

                        </Box>

                      </Box>
                    )
                  )}

                </Box>

              </DialogContent>


              <DialogActions>

                <Button
                  disabled={
                    saving
                  }
                  onClick={
                    () =>
                      setSelectedRole(
                        null
                      )
                  }
                >
                  Cancel
                </Button>


                <Button
                  variant="contained"
                  startIcon={
                    <SaveOutlined />
                  }
                  disabled={
                    saving ||
                    !selectedRole
                  }
                  onClick={
                    saveRolePermissions
                  }
                >
                  {saving
                    ? "Saving..."
                    : "Save Permissions"}
                </Button>

              </DialogActions>

            </Dialog>

          </Box>

        </PermissionGuard>

      </AppShell>

    </ProtectedRoute>
  );
}