// apps/web/src/app/tenants/page.tsx

"use client";


import {
  useMemo,
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
  Stack,
  TextField,
  Typography,
} from "@mui/material";


import AddOutlined
  from "@mui/icons-material/AddOutlined";


import ApartmentOutlined
  from "@mui/icons-material/ApartmentOutlined";


import CheckCircleOutlineOutlined
  from "@mui/icons-material/CheckCircleOutlineOutlined";


import RefreshOutlined
  from "@mui/icons-material/RefreshOutlined";


import AppShell
  from "@/components/app-shell";


import ProtectedRoute
  from "@/components/protected-route";


import {
  useTenant,
} from "@/context/tenant-context";


import {
  createTenant,
} from "@/lib/tenants";


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


function makeSlug(
  value: string
): string {

  return String(
    value || ""
  )
    .trim()
    .toLowerCase()
    .replace(
      /[^a-z0-9]+/g,
      "-"
    )
    .replace(
      /^-+|-+$/g,
      ""
    )
    .slice(
      0,
      80
    );
}


function formatStatus(
  value: string
): string {

  return String(
    value || ""
  )
    .replace(
      /_/g,
      " "
    )
    .replace(
      /\b\w/g,
      (
        character
      ) =>
        character.toUpperCase()
    );
}


export default function TenantsPage() {

  const {
    tenants,
    selectedTenantId,
    loading,
    error:
      tenantContextError,
    selectTenant,
    refreshTenants,
  } = useTenant();


  const [
    dialogOpen,
    setDialogOpen,
  ] = useState(false);


  const [
    name,
    setName,
  ] = useState("");


  const [
    slug,
    setSlug,
  ] = useState("");


  const [
    slugEdited,
    setSlugEdited,
  ] = useState(false);


  const [
    creating,
    setCreating,
  ] = useState(false);


  const [
    pageError,
    setPageError,
  ] = useState("");


  const [
    message,
    setMessage,
  ] = useState("");


  const sortedTenants =
    useMemo(
      () => {

        return [
          ...tenants,
        ].sort(
          (
            first,
            second
          ) =>
            first.tenant.name
              .localeCompare(
                second.tenant.name
              )
        );

      },
      [
        tenants,
      ]
    );


  const openCreateDialog =
    () => {

      setName(
        ""
      );

      setSlug(
        ""
      );

      setSlugEdited(
        false
      );

      setPageError(
        ""
      );

      setDialogOpen(
        true
      );
    };


  const closeCreateDialog =
    () => {

      if (
        creating
      ) {
        return;
      }


      setDialogOpen(
        false
      );
    };


  const handleNameChange =
    (
      value: string
    ) => {

      setName(
        value
      );


      if (
        !slugEdited
      ) {

        setSlug(
          makeSlug(
            value
          )
        );
      }
    };


  const handleSlugChange =
    (
      value: string
    ) => {

      setSlugEdited(
        true
      );


      setSlug(
        makeSlug(
          value
        )
      );
    };


  const submitCreateTenant =
    async () => {

      const cleanName =
        name.trim();


      const cleanSlug =
        makeSlug(
          slug
        );


      if (
        !cleanName
      ) {

        setPageError(
          "Tenant name is required."
        );

        return;
      }


      if (
        !cleanSlug
      ) {

        setPageError(
          "Tenant slug is required."
        );

        return;
      }


      setCreating(
        true
      );

      setPageError(
        ""
      );

      setMessage(
        ""
      );


      try {

        const tenant =
          await createTenant({
            name:
              cleanName,

            slug:
              cleanSlug,
          });


        /*
         * Tenant creation also creates the owner's
         * membership on the backend.
         *
         * Refresh the global context so the new
         * tenant immediately appears everywhere.
         */

        await refreshTenants();


        setMessage(
          `${tenant.name} was created successfully.`
        );


        setDialogOpen(
          false
        );


        setName(
          ""
        );

        setSlug(
          ""
        );

        setSlugEdited(
          false
        );

      } catch (
        createError
      ) {

        setPageError(
          apiError(
            createError,
            "Tenant could not be created."
          )
        );

      } finally {

        setCreating(
          false
        );
      }
    };


  return (
    <ProtectedRoute>

      <AppShell>

        <Box>

          {/* PAGE HEADER */}

          <Box
            sx={{
              display:
                "flex",

              justifyContent:
                "space-between",

              alignItems:
                "flex-start",

              gap:
                2,

              flexWrap:
                "wrap",

              mb:
                3,
            }}
          >

            <Box>

              <Typography
                sx={{
                  fontSize:
                    12,

                  color:
                    "text.secondary",

                  textTransform:
                    "uppercase",

                  letterSpacing:
                    0.8,

                  mb:
                    0.5,
                }}
              >
                Tenant Administration
              </Typography>


              <Typography
                variant="h4"
              >
                Tenants
              </Typography>


              <Typography
                sx={{
                  mt:
                    0.5,

                  color:
                    "text.secondary",
                }}
              >
                Manage the organizations and workspaces available to your account.
              </Typography>

            </Box>


            <Stack
              direction="row"
              spacing={
                1
              }
            >

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
                    refreshTenants()
                }
              >
                Refresh
              </Button>


              <Button
                variant="contained"
                startIcon={
                  <AddOutlined />
                }
                onClick={
                  openCreateDialog
                }
              >
                Create Tenant
              </Button>

            </Stack>

          </Box>


          {/* MESSAGES */}

          {message && (

            <Alert
              severity="success"
              onClose={
                () =>
                  setMessage(
                    ""
                  )
              }
              sx={{
                mb:
                  2,
              }}
            >
              {message}
            </Alert>

          )}


          {pageError && (

            <Alert
              severity="error"
              onClose={
                () =>
                  setPageError(
                    ""
                  )
              }
              sx={{
                mb:
                  2,
              }}
            >
              {pageError}
            </Alert>

          )}


          {tenantContextError && (

            <Alert
              severity="error"
              sx={{
                mb:
                  2,
              }}
            >
              {tenantContextError}
            </Alert>

          )}


          {/* SUMMARY */}

          <Box
            sx={{
              bgcolor:
                "#ffffff",

              border:
                "1px solid",

              borderColor:
                "divider",

              px:
                2.5,

              py:
                1.75,

              mb:
                2,

              display:
                "flex",

              justifyContent:
                "space-between",

              alignItems:
                "center",

              gap:
                2,

              flexWrap:
                "wrap",
            }}
          >

            <Box>

              <Typography
                sx={{
                  fontSize:
                    10,

                  fontWeight:
                    700,

                  color:
                    "text.secondary",

                  textTransform:
                    "uppercase",

                  letterSpacing:
                    0.6,
                }}
              >
                Accessible Tenants
              </Typography>


              <Typography
                sx={{
                  mt:
                    0.3,

                  fontSize:
                    20,

                  fontWeight:
                    600,
                }}
              >
                {
                  tenants.length
                }
              </Typography>

            </Box>


            <Typography
              sx={{
                fontSize:
                  11,

                color:
                  "text.secondary",
              }}
            >
              Only active tenant memberships are shown.
            </Typography>

          </Box>


          {/* TENANT LIST */}

          {loading ? (

            <Box
              sx={{
                minHeight:
                  300,

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
                size={
                  28
                }
              />

            </Box>

          ) : sortedTenants.length ===
              0 ? (

            <Box
              sx={{
                minHeight:
                  300,

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

                p:
                  4,
              }}
            >

              <Box>

                <ApartmentOutlined
                  sx={{
                    fontSize:
                      42,

                    color:
                      "text.secondary",
                  }}
                />


                <Typography
                  sx={{
                    mt:
                      1,

                    fontSize:
                      17,

                    fontWeight:
                      600,
                  }}
                >
                  No tenant access
                </Typography>


                <Typography
                  sx={{
                    mt:
                      0.5,

                    fontSize:
                      12,

                    color:
                      "text.secondary",
                  }}
                >
                  Create a tenant to begin using tenant-scoped AUGMIS services.
                </Typography>

              </Box>

            </Box>

          ) : (

            <Box
              sx={{
                display:
                  "grid",

                gridTemplateColumns:
                  {
                    xs:
                      "1fr",

                    lg:
                      "repeat(2, minmax(0, 1fr))",
                  },

                gap:
                  2,
              }}
            >

              {
                sortedTenants.map(
                  (
                    membership
                  ) => {

                    const tenant =
                      membership.tenant;


                    const selected =
                      tenant.id ===
                      selectedTenantId;


                    return (

                      <Box
                        key={
                          membership.membershipId
                        }
                        sx={{
                          bgcolor:
                            "#ffffff",

                          border:
                            "1px solid",

                          borderColor:
                            selected
                              ? "primary.main"
                              : "divider",

                          display:
                            "flex",

                          flexDirection:
                            "column",

                          minHeight:
                            190,
                        }}
                      >

                        <Box
                          sx={{
                            p:
                              2.5,

                            display:
                              "flex",

                            justifyContent:
                              "space-between",

                            alignItems:
                              "flex-start",

                            gap:
                              2,
                          }}
                        >

                          <Box
                            sx={{
                              minWidth:
                                0,
                            }}
                          >

                            <Stack
                              direction="row"
                              spacing={
                                1
                              }
                              sx={{
                                alignItems:
                                  "center",
                              }}
                            >

                              <ApartmentOutlined
                                sx={{
                                  fontSize:
                                    20,

                                  color:
                                    "text.secondary",
                                }}
                              />


                              <Typography
                                sx={{
                                  fontSize:
                                    17,

                                  fontWeight:
                                    600,
                                }}
                              >
                                {
                                  tenant.name
                                }
                              </Typography>

                            </Stack>


                            <Typography
                              sx={{
                                mt:
                                  0.75,

                                fontSize:
                                  11,

                                color:
                                  "text.secondary",

                                fontFamily:
                                  "monospace",
                              }}
                            >
                              {
                                tenant.slug
                              }
                            </Typography>

                          </Box>


                          {selected ? (

                            <Chip
                              size="small"
                              icon={
                                <CheckCircleOutlineOutlined />
                              }
                              label="Current"
                              color="success"
                              variant="outlined"
                            />

                          ) : (

                            <Chip
                              size="small"
                              label={
                                formatStatus(
                                  membership.status
                                )
                              }
                              color="success"
                              variant="outlined"
                            />

                          )}

                        </Box>


                        <Box
                          sx={{
                            mt:
                              "auto",

                            px:
                              2.5,

                            py:
                              1.5,

                            borderTop:
                              "1px solid",

                            borderColor:
                              "divider",

                            display:
                              "flex",

                            justifyContent:
                              "space-between",

                            alignItems:
                              "center",

                            gap:
                              2,

                            flexWrap:
                              "wrap",
                          }}
                        >

                          <Box>

                            <Typography
                              sx={{
                                fontSize:
                                  9,

                                color:
                                  "text.secondary",

                                textTransform:
                                  "uppercase",

                                letterSpacing:
                                  0.5,
                              }}
                            >
                              Membership
                            </Typography>


                            <Typography
                              sx={{
                                mt:
                                  0.2,

                                fontSize:
                                  11.5,

                                fontWeight:
                                  600,
                              }}
                            >
                              {
                                formatStatus(
                                  membership.status
                                )
                              }
                            </Typography>

                          </Box>


                          <Button
                            size="small"
                            variant={
                              selected
                                ? "outlined"
                                : "contained"
                            }
                            disabled={
                              selected
                            }
                            onClick={
                              () =>
                                selectTenant(
                                  tenant.id
                                )
                            }
                          >
                            {
                              selected
                                ? "Selected"
                                : "Select Tenant"
                            }
                          </Button>

                        </Box>

                      </Box>

                    );
                  }
                )
              }

            </Box>

          )}


          {/* CREATE TENANT DIALOG */}

          <Dialog
            open={
              dialogOpen
            }
            onClose={
              closeCreateDialog
            }
            fullWidth
            maxWidth="sm"
          >

            <DialogTitle>
              Create Tenant
            </DialogTitle>


            <DialogContent>

              <Typography
                sx={{
                  mb:
                    2.5,

                  fontSize:
                    12,

                  color:
                    "text.secondary",
                }}
              >
                Create a new AUGMIS tenant workspace. You will automatically become its owner.
              </Typography>


              <Stack
                spacing={
                  2
                }
              >

                <TextField
                  label="Tenant Name"
                  fullWidth
                  autoFocus
                  value={
                    name
                  }
                  disabled={
                    creating
                  }
                  onChange={
                    (
                      event
                    ) =>
                      handleNameChange(
                        event.target.value
                      )
                  }
                  placeholder=
                    "Example Engineering"
                />


                <TextField
                  label="Tenant Slug"
                  fullWidth
                  value={
                    slug
                  }
                  disabled={
                    creating
                  }
                  onChange={
                    (
                      event
                    ) =>
                      handleSlugChange(
                        event.target.value
                      )
                  }
                  placeholder=
                    "example-engineering"
                  helperText=
                    "Lowercase letters, numbers and hyphens."
                />

              </Stack>


              {pageError && (

                <Alert
                  severity="error"
                  sx={{
                    mt:
                      2,
                  }}
                >
                  {pageError}
                </Alert>

              )}

            </DialogContent>


            <DialogActions>

              <Button
                disabled={
                  creating
                }
                onClick={
                  closeCreateDialog
                }
              >
                Cancel
              </Button>


              <Button
                variant="contained"
                disabled={
                  creating ||
                  !name.trim() ||
                  !slug.trim()
                }
                onClick={
                  submitCreateTenant
                }
              >

                {creating ? (
                  <>
                    <CircularProgress
                      size={
                        14
                      }
                      sx={{
                        mr:
                          1,

                        color:
                          "inherit",
                      }}
                    />
                    Creating...
                  </>
                ) : (
                  "Create Tenant"
                )}

              </Button>

            </DialogActions>

          </Dialog>

        </Box>

      </AppShell>

    </ProtectedRoute>
  );
}