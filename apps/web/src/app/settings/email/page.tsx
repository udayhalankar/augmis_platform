"use client";

import {
  Alert,
  Box,
  Button,
  Chip,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";

import EmailOutlined from "@mui/icons-material/EmailOutlined";
import SaveOutlined from "@mui/icons-material/SaveOutlined";
import SendOutlined from "@mui/icons-material/SendOutlined";

import { useEffect, useState } from "react";

import AppShell from "@/components/app-shell";
import ProtectedRoute from "@/components/protected-route";
import {
  loadPlatformEmailSettings,
  savePlatformEmailSettings,
  sendPlatformEmailTest,
  PlatformEmailSettings,
} from "@/lib/platform-settings";


function apiError(
  error: unknown,
  fallback: string
): string {
  const candidate = error as {
    response?: {
      data?: {
        detail?: string;
      };
    };
    message?: string;
  };

  return (
    candidate?.response?.data?.detail ||
    candidate?.message ||
    fallback
  );
}


export default function EmailSettingsPage() {
  const [settings, setSettings] =
    useState<PlatformEmailSettings | null>(null);

  const [credential, setCredential] = useState("");
  const [testRecipient, setTestRecipient] = useState("");
  const [busy, setBusy] = useState(false);
  const [testBusy, setTestBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = async () => {
    setError("");

    try {
      setSettings(
        await loadPlatformEmailSettings()
      );
    } catch (loadError) {
      setError(
        apiError(
          loadError,
          "Email settings could not be loaded."
        )
      );
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const applyProvider = (
    provider: string
  ) => {
    if (!settings) {
      return;
    }

    if (provider === "resend") {
      setSettings({
        ...settings,
        provider,
        host: "smtp.resend.com",
        port: 465,
        username: "resend",
        useSsl: true,
        useStarttls: false,
      });
      return;
    }

    setSettings({
      ...settings,
      provider,
    });
  };

  const securityMode =
    settings?.useSsl
      ? "ssl"
      : settings?.useStarttls
        ? "starttls"
        : "none";

  const updateSecurity = (
    value: string
  ) => {
    if (!settings) {
      return;
    }

    setSettings({
      ...settings,
      useSsl: value === "ssl",
      useStarttls:
        value === "starttls",
    });
  };

  const save = async () => {
    if (!settings) {
      return;
    }

    setBusy(true);
    setError("");
    setMessage("");

    try {
      const result =
        await savePlatformEmailSettings({
          provider: settings.provider,
          enabled: settings.enabled,
          host: settings.host,
          port: settings.port,
          username: settings.username,
          ...(credential
            ? { credential }
            : {}),
          fromEmail: settings.fromEmail,
          fromName: settings.fromName,
          useStarttls:
            settings.useStarttls,
          useSsl: settings.useSsl,
          timeoutSeconds:
            settings.timeoutSeconds,
        });

      setSettings(result);
      setCredential("");
      setMessage(
        "Email delivery settings saved."
      );
    } catch (saveError) {
      setError(
        apiError(
          saveError,
          "Email settings could not be saved."
        )
      );
    } finally {
      setBusy(false);
    }
  };

  const sendTest = async () => {
    const recipient =
      testRecipient.trim();

    if (!recipient) {
      setError(
        "Enter a test recipient email address."
      );
      return;
    }

    setTestBusy(true);
    setError("");
    setMessage("");

    try {
      const result =
        await sendPlatformEmailTest(
          recipient
        );

      setMessage(
        `Test email submitted to ${result.recipient}.`
      );
    } catch (testError) {
      setError(
        apiError(
          testError,
          "Test email could not be sent."
        )
      );
    } finally {
      setTestBusy(false);
    }
  };

  return (
    <ProtectedRoute>
      <AppShell>
        <Box>
          <Stack
            direction={{
              xs: "column",
              md: "row",
            }}
            spacing={2}
            sx={{
              alignItems: {
                xs: "flex-start",
                md: "center",
              },
              justifyContent:
                "space-between",
              mb: 3,
            }}
          >
            <Box>
              <Typography
                sx={{
                  fontSize: 11,
                  color:
                    "text.secondary",
                  letterSpacing: 0.8,
                  textTransform:
                    "uppercase",
                  mb: 0.5,
                }}
              >
                Platform Administration
              </Typography>

              <Typography variant="h4">
                Email Delivery
              </Typography>

              <Typography
                sx={{
                  mt: 0.75,
                  color:
                    "text.secondary",
                }}
              >
                Configure transactional email for invitations and platform notifications.
              </Typography>
            </Box>

            {settings && (
              <Stack
                direction="row"
                spacing={1}
              >
                <Chip
                  size="small"
                  variant="outlined"
                  label={
                    settings.source ===
                    "database"
                      ? "Database Configuration"
                      : "Environment Fallback"
                  }
                  color={
                    settings.source ===
                    "database"
                      ? "success"
                      : "default"
                  }
                />

                <Chip
                  size="small"
                  variant="outlined"
                  label={
                    settings.enabled
                      ? "Enabled"
                      : "Disabled"
                  }
                  color={
                    settings.enabled
                      ? "success"
                      : "default"
                  }
                />
              </Stack>
            )}
          </Stack>

          {error && (
            <Alert
              severity="error"
              sx={{ mb: 2 }}
              onClose={() =>
                setError("")
              }
            >
              {error}
            </Alert>
          )}

          {message && (
            <Alert
              severity="success"
              sx={{ mb: 2 }}
              onClose={() =>
                setMessage("")
              }
            >
              {message}
            </Alert>
          )}

          {!settings ? (
            <Paper
              variant="outlined"
              sx={{ p: 3 }}
            >
              <Typography
                color="text.secondary"
              >
                Loading email settings...
              </Typography>
            </Paper>
          ) : (
            <Stack spacing={2}>
              <Paper
                variant="outlined"
                sx={{ p: 3 }}
              >
                <Stack
                  direction="row"
                  spacing={1}
                  sx={{
                    alignItems:
                      "center",
                    mb: 2.5,
                  }}
                >
                  <EmailOutlined
                    color="primary"
                  />

                  <Box>
                    <Typography
                      variant="h6"
                    >
                      SMTP Configuration
                    </Typography>

                    <Typography
                      sx={{
                        fontSize: 12,
                        color:
                          "text.secondary",
                      }}
                    >
                      SMTP credentials are encrypted at rest and are never returned by the API.
                    </Typography>
                  </Box>
                </Stack>

                <Stack
                  spacing={2}
                  sx={{
                    maxWidth: 820,
                  }}
                >
                  <FormControlLabel
                    control={
                      <Switch
                        checked={
                          settings.enabled
                        }
                        onChange={(
                          event
                        ) =>
                          setSettings({
                            ...settings,
                            enabled:
                              event
                              .target
                              .checked,
                          })
                        }
                      />
                    }
                    label="Enable email delivery"
                  />

                  <FormControl
                    fullWidth
                    size="small"
                  >
                    <InputLabel>
                      Provider
                    </InputLabel>

                    <Select
                      label="Provider"
                      value={
                        settings.provider
                      }
                      onChange={(
                        event
                      ) =>
                        applyProvider(
                          String(
                            event
                            .target
                            .value
                          )
                        )
                      }
                    >
                      <MenuItem value="resend">
                        Resend
                      </MenuItem>
                      <MenuItem value="custom">
                        Custom SMTP
                      </MenuItem>
                    </Select>
                  </FormControl>

                  <Stack
                    direction={{
                      xs: "column",
                      md: "row",
                    }}
                    spacing={2}
                  >
                    <TextField
                      label="SMTP Host"
                      fullWidth
                      size="small"
                      value={
                        settings.host
                      }
                      disabled={
                        settings.provider ===
                        "resend"
                      }
                      onChange={(
                        event
                      ) =>
                        setSettings({
                          ...settings,
                          host:
                            event
                            .target
                            .value,
                        })
                      }
                    />

                    <TextField
                      label="Port"
                      size="small"
                      type="number"
                      sx={{
                        width: {
                          xs: "100%",
                          md: 180,
                        },
                      }}
                      value={
                        settings.port
                      }
                      disabled={
                        settings.provider ===
                        "resend"
                      }
                      onChange={(
                        event
                      ) =>
                        setSettings({
                          ...settings,
                          port: Number(
                            event
                            .target
                            .value
                          ),
                        })
                      }
                    />
                  </Stack>

                  <TextField
                    label="SMTP Username"
                    fullWidth
                    size="small"
                    value={
                      settings.username
                    }
                    disabled={
                      settings.provider ===
                      "resend"
                    }
                    onChange={(
                      event
                    ) =>
                      setSettings({
                        ...settings,
                        username:
                          event
                          .target
                          .value,
                      })
                    }
                  />

                  <TextField
                    label={
                      settings
                      .credentialConfigured
                        ? "SMTP Credential — configured"
                        : "SMTP Credential"
                    }
                    fullWidth
                    size="small"
                    type="password"
                    value={credential}
                    helperText={
                      settings
                      .credentialConfigured
                        ? "Leave blank to keep the currently configured credential."
                        : "Enter the SMTP password or provider API key."
                    }
                    onChange={(
                      event
                    ) =>
                      setCredential(
                        event
                        .target
                        .value
                      )
                    }
                  />

                  <Stack
                    direction={{
                      xs: "column",
                      md: "row",
                    }}
                    spacing={2}
                  >
                    <TextField
                      label="Sender Name"
                      fullWidth
                      size="small"
                      value={
                        settings.fromName
                      }
                      onChange={(
                        event
                      ) =>
                        setSettings({
                          ...settings,
                          fromName:
                            event
                            .target
                            .value,
                        })
                      }
                    />

                    <TextField
                      label="Sender Email"
                      fullWidth
                      size="small"
                      value={
                        settings.fromEmail
                      }
                      onChange={(
                        event
                      ) =>
                        setSettings({
                          ...settings,
                          fromEmail:
                            event
                            .target
                            .value,
                        })
                      }
                    />
                  </Stack>

                  <Stack
                    direction={{
                      xs: "column",
                      md: "row",
                    }}
                    spacing={2}
                  >
                    <FormControl
                      fullWidth
                      size="small"
                    >
                      <InputLabel>
                        Transport Security
                      </InputLabel>

                      <Select
                        label="Transport Security"
                        value={securityMode}
                        disabled={
                          settings.provider ===
                          "resend"
                        }
                        onChange={(
                          event
                        ) =>
                          updateSecurity(
                            String(
                              event
                              .target
                              .value
                            )
                          )
                        }
                      >
                        <MenuItem value="ssl">
                          SSL/TLS
                        </MenuItem>
                        <MenuItem value="starttls">
                          STARTTLS
                        </MenuItem>
                        <MenuItem value="none">
                          None
                        </MenuItem>
                      </Select>
                    </FormControl>

                    <TextField
                      label="Timeout (seconds)"
                      size="small"
                      type="number"
                      sx={{
                        width: {
                          xs: "100%",
                          md: 220,
                        },
                      }}
                      value={
                        settings
                        .timeoutSeconds
                      }
                      onChange={(
                        event
                      ) =>
                        setSettings({
                          ...settings,
                          timeoutSeconds:
                            Number(
                              event
                              .target
                              .value
                            ),
                        })
                      }
                    />
                  </Stack>

                  <Stack
                    direction="row"
                    spacing={1}
                    sx={{
                      alignItems:
                        "center",
                    }}
                  >
                    <Button
                      variant="contained"
                      startIcon={
                        <SaveOutlined />
                      }
                      disabled={busy}
                      onClick={save}
                    >
                      {busy
                        ? "Saving..."
                        : "Save Settings"}
                    </Button>

                    {settings
                      .credentialConfigured && (
                      <Chip
                        size="small"
                        variant="outlined"
                        color="success"
                        label="Credential configured"
                      />
                    )}
                  </Stack>
                </Stack>
              </Paper>

              <Paper
                variant="outlined"
                sx={{ p: 3 }}
              >
                <Typography
                  variant="h6"
                  sx={{ mb: 0.5 }}
                >
                  Test Delivery
                </Typography>

                <Typography
                  sx={{
                    mb: 2,
                    fontSize: 12,
                    color:
                      "text.secondary",
                  }}
                >
                  Send a transactional test using the currently effective configuration.
                </Typography>

                <Stack
                  direction={{
                    xs: "column",
                    md: "row",
                  }}
                  spacing={1}
                  sx={{
                    maxWidth: 820,
                  }}
                >
                  <TextField
                    label="Recipient Email"
                    size="small"
                    fullWidth
                    value={testRecipient}
                    onChange={(
                      event
                    ) =>
                      setTestRecipient(
                        event
                        .target
                        .value
                      )
                    }
                  />

                  <Button
                    variant="outlined"
                    startIcon={
                      <SendOutlined />
                    }
                    disabled={testBusy}
                    onClick={sendTest}
                    sx={{
                      minWidth: 170,
                    }}
                  >
                    {testBusy
                      ? "Sending..."
                      : "Send Test Email"}
                  </Button>
                </Stack>
              </Paper>
            </Stack>
          )}
        </Box>
      </AppShell>
    </ProtectedRoute>
  );
}
