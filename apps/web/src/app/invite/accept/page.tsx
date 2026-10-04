// apps/web/src/app/invite/accept/page.tsx

"use client";

import {
  useEffect,
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
  Divider,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

import CheckCircleOutlineOutlined
  from "@mui/icons-material/CheckCircleOutlineOutlined";
import LoginOutlined
  from "@mui/icons-material/LoginOutlined";
import LogoutOutlined
  from "@mui/icons-material/LogoutOutlined";
import PersonAddAltOutlined
  from "@mui/icons-material/PersonAddAltOutlined";

import {
  useAuth,
} from "@/context/auth-context";
import {
  useTenant,
} from "@/context/tenant-context";

import {
  setAccessToken,
} from "@/lib/auth-storage";

import {
  acceptExistingTenantInvitation,
  acceptNewTenantInvitation,
  InvitationAcceptanceResult,
  InvitationResolveResult,
  resolveTenantInvitation,
} from "@/lib/invitations";


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


function formatDate(
  value: string
): string {
  const parsed =
    new Date(
      value
    );

  if (
    Number.isNaN(
      parsed.getTime()
    )
  ) {
    return value;
  }

  return parsed.toLocaleString();
}


export default function InvitationAcceptPage() {
  const {
    user,
    loading: authLoading,
    login,
    logout,
    refreshUser,
  } = useAuth();

  const {
    refreshTenants,
  } = useTenant();

  const [
    token,
    setToken,
  ] = useState("");

  const [
    invitation,
    setInvitation,
  ] =
    useState<
      InvitationResolveResult | null
    >(null);

  const [
    loading,
    setLoading,
  ] = useState(true);

  const [
    busy,
    setBusy,
  ] = useState(false);

  const [
    error,
    setError,
  ] = useState("");

  const [
    password,
    setPassword,
  ] = useState("");

  const [
    firstName,
    setFirstName,
  ] = useState("");

  const [
    lastName,
    setLastName,
  ] = useState("");

  const [
    confirmPassword,
    setConfirmPassword,
  ] = useState("");

  const [
    accepted,
    setAccepted,
  ] =
    useState<
      InvitationAcceptanceResult | null
    >(null);


  useEffect(
    () => {
      const params =
        new URLSearchParams(
          window.location.search
        );

      const inviteToken =
        String(
          params.get(
            "token"
          ) || ""
        ).trim();

      setToken(
        inviteToken
      );

      if (
        !inviteToken
      ) {
        setLoading(
          false
        );

        setError(
          "The invitation link is missing its token."
        );

        return;
      }

      const load =
        async () => {
          setLoading(
            true
          );

          setError(
            ""
          );

          try {
            const result =
              await resolveTenantInvitation(
                inviteToken
              );

            setInvitation(
              result
            );

          } catch (
            loadError
          ) {
            setInvitation(
              null
            );

            setError(
              apiError(
                loadError,
                "The invitation could not be loaded."
              )
            );

          } finally {
            setLoading(
              false
            );
          }
        };

      void load();
    },
    []
  );


  const signedInEmailMatches =
    useMemo(
      () => {
        if (
          !user ||
          !invitation
        ) {
          return false;
        }

        return (
          user.email
            .trim()
            .toLowerCase()
          ===
          invitation.email
            .trim()
            .toLowerCase()
        );
      },
      [
        user,
        invitation,
      ]
    );


  const finish =
    async (
      result:
        InvitationAcceptanceResult
    ) => {
      setAccepted(
        result
      );

      setError(
        ""
      );

      try {
        await refreshTenants();
      } catch {
        // A full navigation later reloads tenant context.
      }
    };


  const acceptExisting =
    async () => {
      if (
        !token ||
        !invitation
      ) {
        return;
      }

      setBusy(
        true
      );

      setError(
        ""
      );

      try {
        if (!user) {
          if (!password) {
            setError(
              "Enter your AUGMIS password."
            );

            return;
          }

          await login(
            invitation.email,
            password
          );
        }

        const result =
          await acceptExistingTenantInvitation(
            token
          );

        await finish(
          result
        );

      } catch (
        acceptError
      ) {
        setError(
          apiError(
            acceptError,
            "The invitation could not be accepted."
          )
        );

      } finally {
        setBusy(
          false
        );
      }
    };


  const acceptNew =
    async () => {
      if (
        !token ||
        !invitation
      ) {
        return;
      }

      const cleanFirstName =
        firstName.trim();

      const cleanLastName =
        lastName.trim();

      if (
        !cleanFirstName ||
        !cleanLastName
      ) {
        setError(
          "First name and last name are required."
        );

        return;
      }

      if (
        password.length <
        10
      ) {
        setError(
          "Password must be at least 10 characters."
        );

        return;
      }

      if (
        password !==
        confirmPassword
      ) {
        setError(
          "Passwords do not match."
        );

        return;
      }

      setBusy(
        true
      );

      setError(
        ""
      );

      try {
        const result =
          await acceptNewTenantInvitation(
            {
              token,
              firstName:
                cleanFirstName,
              lastName:
                cleanLastName,
              password,
            }
          );

        if (
          result.accessToken
        ) {
          setAccessToken(
            result.accessToken
          );

          await refreshUser();
        }

        await finish(
          result
        );

      } catch (
        acceptError
      ) {
        setError(
          apiError(
            acceptError,
            "Your AUGMIS account could not be created from this invitation."
          )
        );

      } finally {
        setBusy(
          false
        );
      }
    };


  const goToAUGMIS =
    () => {
      window.location.assign(
        "/tenants"
      );
    };


  return (
    <Box
      sx={{
        minHeight:
          "100vh",
        bgcolor:
          "background.default",
        display:
          "grid",
        placeItems:
          "center",
        px: 2,
        py: 4,
      }}
    >
      <Box
        sx={{
          width:
            "100%",
          maxWidth:
            660,
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
            px: {
              xs: 2.5,
              sm: 4,
            },
            py: 3,
            borderBottom:
              "1px solid",
            borderColor:
              "divider",
          }}
        >
          <Stack
            direction="row"
            spacing={1.5}
            sx={{
              alignItems:
                "center",
            }}
          >
            <Box
              sx={{
                width: 42,
                height: 42,
                bgcolor:
                  "primary.main",
                color:
                  "#ffffff",
                display:
                  "grid",
                placeItems:
                  "center",
                fontWeight:
                  700,
                fontSize:
                  14,
              }}
            >
              AU
            </Box>

            <Box>
              <Typography
                sx={{
                  fontSize: 20,
                  fontWeight: 700,
                  lineHeight: 1.1,
                }}
              >
                AUGMIS
              </Typography>

              <Typography
                sx={{
                  mt: 0.2,
                  fontSize: 10.5,
                  color:
                    "text.secondary",
                  textTransform:
                    "uppercase",
                  letterSpacing:
                    0.7,
                }}
              >
                Platform Control Plane
              </Typography>
            </Box>
          </Stack>
        </Box>

        <Box
          sx={{
            px: {
              xs: 2.5,
              sm: 4,
            },
            py: {
              xs: 3,
              sm: 4,
            },
          }}
        >
          {loading ||
          authLoading ? (
            <Box
              sx={{
                minHeight: 280,
                display:
                  "grid",
                placeItems:
                  "center",
              }}
            >
              <CircularProgress
                size={30}
              />
            </Box>
          ) : accepted ? (
            <Box
              sx={{
                textAlign:
                  "center",
                py: 2,
              }}
            >
              <CheckCircleOutlineOutlined
                color="success"
                sx={{
                  fontSize: 58,
                }}
              />

              <Typography
                variant="h4"
                sx={{
                  mt: 1.5,
                }}
              >
                Invitation accepted
              </Typography>

              <Typography
                sx={{
                  mt: 1,
                  color:
                    "text.secondary",
                }}
              >
                You now have access to{" "}
                <strong>
                  {
                    accepted
                      .tenant
                      .name
                  }
                </strong>.
              </Typography>

              <Stack
                direction="row"
                spacing={0.75}
                useFlexGap
                sx={{
                  mt: 2,
                  justifyContent:
                    "center",
                  flexWrap:
                    "wrap",
                }}
              >
                {
                  accepted.roles.map(
                    (role) => (
                      <Chip
                        key={
                          role.id
                        }
                        label={
                          role.name
                        }
                        size="small"
                        variant="outlined"
                      />
                    )
                  )
                }
              </Stack>

              <Button
                variant="contained"
                sx={{
                  mt: 3,
                }}
                onClick={
                  goToAUGMIS
                }
              >
                Continue to AUGMIS
              </Button>
            </Box>
          ) : error &&
              !invitation ? (
            <Alert
              severity="error"
            >
              {error}
            </Alert>
          ) : invitation ? (
            <>
              <Typography
                sx={{
                  fontSize: 12,
                  color:
                    "text.secondary",
                  textTransform:
                    "uppercase",
                  letterSpacing:
                    0.7,
                }}
              >
                Tenant Invitation
              </Typography>

              <Typography
                variant="h4"
                sx={{
                  mt: 0.5,
                }}
              >
                Join {
                  invitation
                    .tenant
                    .name
                }
              </Typography>

              <Typography
                sx={{
                  mt: 1,
                  color:
                    "text.secondary",
                }}
              >
                This invitation was issued to{" "}
                <strong>
                  {
                    invitation.email
                  }
                </strong>.
              </Typography>

              <Box
                sx={{
                  mt: 3,
                  border:
                    "1px solid",
                  borderColor:
                    "divider",
                  p: 2,
                }}
              >
                <Stack
                  spacing={1.4}
                >
                  <InfoRow
                    label="Tenant"
                    value={
                      invitation
                        .tenant
                        .name
                    }
                  />

                  <InfoRow
                    label="Workspace"
                    value={
                      invitation
                        .tenant
                        .slug
                    }
                  />

                  <InfoRow
                    label="Expires"
                    value={
                      formatDate(
                        invitation
                          .expiresAt
                      )
                    }
                  />

                  <Box>
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
                      Roles
                    </Typography>

                    <Stack
                      direction="row"
                      spacing={0.75}
                      useFlexGap
                      sx={{
                        mt: 0.75,
                        flexWrap:
                          "wrap",
                      }}
                    >
                      {
                        invitation.roles.map(
                          (role) => (
                            <Chip
                              key={
                                role.id
                              }
                              label={
                                role.name
                              }
                              size="small"
                              variant="outlined"
                            />
                          )
                        )
                      }
                    </Stack>
                  </Box>
                </Stack>
              </Box>

              {!invitation.canAccept ? (
                <Alert
                  severity={
                    invitation.status ===
                    "expired"
                      ? "warning"
                      : "error"
                  }
                  sx={{
                    mt: 2.5,
                  }}
                >
                  This invitation is {
                    invitation.status
                  } and can no longer be accepted.
                </Alert>
              ) : invitation.existingUser ? (
                <Box
                  sx={{
                    mt: 3,
                  }}
                >
                  <Divider
                    sx={{
                      mb: 3,
                    }}
                  />

                  <Typography
                    sx={{
                      fontSize: 17,
                      fontWeight: 600,
                    }}
                  >
                    Existing AUGMIS account
                  </Typography>

                  <Typography
                    sx={{
                      mt: 0.5,
                      fontSize: 12,
                      color:
                        "text.secondary",
                    }}
                  >
                    Sign in with the invited email address and accept access to this tenant.
                  </Typography>

                  {user &&
                  !signedInEmailMatches ? (
                    <Alert
                      severity="warning"
                      sx={{
                        mt: 2,
                      }}
                      action={
                        <Button
                          color="inherit"
                          size="small"
                          startIcon={
                            <LogoutOutlined />
                          }
                          onClick={
                            logout
                          }
                        >
                          Sign out
                        </Button>
                      }
                    >
                      You are signed in as {
                        user.email
                      }, but this invitation belongs to {
                        invitation.email
                      }.
                    </Alert>
                  ) : (
                    <Stack
                      spacing={2}
                      sx={{
                        mt: 2,
                      }}
                    >
                      <TextField
                        label="Email"
                        fullWidth
                        value={
                          invitation.email
                        }
                        slotProps={{
                          input: {
                            readOnly: true,
                          },
                        }}
                      />

                      {!user && (
                        <TextField
                          label="Password"
                          type="password"
                          fullWidth
                          value={
                            password
                          }
                          onChange={
                            (event) =>
                              setPassword(
                                event
                                  .target
                                  .value
                              )
                          }
                        />
                      )}

                      {error && (
                        <Alert
                          severity="error"
                        >
                          {error}
                        </Alert>
                      )}

                      <Button
                        variant="contained"
                        size="large"
                        startIcon={
                          <LoginOutlined />
                        }
                        disabled={
                          busy ||
                          (
                            !user &&
                            !password
                          )
                        }
                        onClick={
                          acceptExisting
                        }
                      >
                        {
                          busy
                            ? "Accepting..."
                            : (
                              user
                                ? "Accept Invitation"
                                : "Sign In & Accept"
                            )
                        }
                      </Button>
                    </Stack>
                  )}
                </Box>
              ) : (
                <Box
                  sx={{
                    mt: 3,
                  }}
                >
                  <Divider
                    sx={{
                      mb: 3,
                    }}
                  />

                  <Typography
                    sx={{
                      fontSize: 17,
                      fontWeight: 600,
                    }}
                  >
                    Create your AUGMIS account
                  </Typography>

                  <Typography
                    sx={{
                      mt: 0.5,
                      fontSize: 12,
                      color:
                        "text.secondary",
                    }}
                  >
                    Your account and tenant membership will be created together when you accept the invitation.
                  </Typography>

                  {user ? (
                    <Alert
                      severity="warning"
                      sx={{
                        mt: 2,
                      }}
                      action={
                        <Button
                          color="inherit"
                          size="small"
                          startIcon={
                            <LogoutOutlined />
                          }
                          onClick={
                            logout
                          }
                        >
                          Sign out
                        </Button>
                      }
                    >
                      You are currently signed in as {
                        user.email
                      }. Sign out before creating the invited account.
                    </Alert>
                  ) : (
                    <Stack
                      spacing={2}
                      sx={{
                        mt: 2,
                      }}
                    >
                      <TextField
                        label="Email"
                        fullWidth
                        value={
                          invitation.email
                        }
                        slotProps={{
                          input: {
                            readOnly: true,
                          },
                        }}
                      />

                      <Box
                        sx={{
                          display:
                            "grid",
                          gridTemplateColumns:
                            {
                              xs:
                                "1fr",
                              sm:
                                "1fr 1fr",
                            },
                          gap: 2,
                        }}
                      >
                        <TextField
                          label="First Name"
                          fullWidth
                          value={
                            firstName
                          }
                          onChange={
                            (event) =>
                              setFirstName(
                                event
                                  .target
                                  .value
                              )
                          }
                        />

                        <TextField
                          label="Last Name"
                          fullWidth
                          value={
                            lastName
                          }
                          onChange={
                            (event) =>
                              setLastName(
                                event
                                  .target
                                  .value
                              )
                          }
                        />
                      </Box>

                      <TextField
                        label="Password"
                        type="password"
                        fullWidth
                        helperText=
                          "Minimum 10 characters."
                        value={
                          password
                        }
                        onChange={
                          (event) =>
                            setPassword(
                              event
                                .target
                                .value
                            )
                        }
                      />

                      <TextField
                        label="Confirm Password"
                        type="password"
                        fullWidth
                        value={
                          confirmPassword
                        }
                        onChange={
                          (event) =>
                            setConfirmPassword(
                              event
                                .target
                                .value
                            )
                        }
                      />

                      {error && (
                        <Alert
                          severity="error"
                        >
                          {error}
                        </Alert>
                      )}

                      <Button
                        variant="contained"
                        size="large"
                        startIcon={
                          <PersonAddAltOutlined />
                        }
                        disabled={
                          busy ||
                          !firstName.trim() ||
                          !lastName.trim() ||
                          password.length < 10 ||
                          confirmPassword !==
                            password
                        }
                        onClick={
                          acceptNew
                        }
                      >
                        {
                          busy
                            ? "Creating account..."
                            : "Create Account & Accept"
                        }
                      </Button>
                    </Stack>
                  )}
                </Box>
              )}
            </>
          ) : null}
        </Box>
      </Box>
    </Box>
  );
}


function InfoRow({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <Box
      sx={{
        display:
          "grid",
        gridTemplateColumns:
          "120px minmax(0, 1fr)",
        gap: 1.5,
        alignItems:
          "start",
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
          fontSize: 12.5,
          fontWeight: 600,
          overflowWrap:
            "anywhere",
        }}
      >
        {value}
      </Typography>
    </Box>
  );
}
