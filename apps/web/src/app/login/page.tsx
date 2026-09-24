"use client";

import {
  FormEvent,
  useEffect,
  useState,
} from "react";

import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

import {
  useRouter,
} from "next/navigation";

import axios from "axios";

import {
  useAuth,
} from "@/context/auth-context";


export default function LoginPage() {

  const router =
    useRouter();

  const {
    user,
    loading,
    login,
  } = useAuth();


  const [
    email,
    setEmail,
  ] = useState("");

  const [
    password,
    setPassword,
  ] = useState("");

  const [
    submitting,
    setSubmitting,
  ] = useState(false);

  const [
    errorMessage,
    setErrorMessage,
  ] = useState("");


  useEffect(
    () => {

      if (
        !loading &&
        user
      ) {

        router.replace("/");
      }

    },
    [
      loading,
      user,
      router,
    ]
  );


  const handleSubmit =
    async (
      event:
        FormEvent<HTMLFormElement>
    ) => {

      event.preventDefault();

      setSubmitting(true);

      setErrorMessage("");

      try {

        await login(
          email,
          password
        );

        router.replace("/");

      } catch (error) {

        if (
          axios.isAxiosError(
            error
          )
        ) {

          setErrorMessage(
            error.response?.data
              ?.detail ??
              "Unable to sign in."
          );

        } else {

          setErrorMessage(
            "Unable to sign in."
          );
        }

      } finally {

        setSubmitting(false);
      }
    };


  return (
    <Box
      sx={{
        minHeight: "100vh",
        bgcolor: "#eef2f5",
        display: "grid",
        gridTemplateColumns: {
          xs: "1fr",
          lg: "1.15fr 0.85fr",
        },
      }}
    >

      {/* LEFT BRAND PANEL */}

      <Box
        sx={{
          display: {
            xs: "none",
            lg: "flex",
          },

          flexDirection: "column",
          justifyContent:
            "space-between",

          bgcolor: "#17384f",
          color: "#ffffff",

          px: 7,
          py: 6,
        }}
      >
        <Box>

          <Stack
            direction="row"
            spacing={2}
            sx={{
              alignItems: "center",
            }}
          >
            <Box
              sx={{
                width: 42,
                height: 42,

                display: "grid",
                placeItems: "center",

                bgcolor: "#ffffff",
                color: "#17384f",

                fontSize: 14,
                fontWeight: 700,
              }}
            >
              AU
            </Box>

            <Box>

              <Typography
                sx={{
                  fontSize: 22,
                  fontWeight: 650,
                }}
              >
                AUGMIS
              </Typography>

              <Typography
                sx={{
                  fontSize: 11,
                  opacity: 0.7,
                  letterSpacing: 1,
                }}
              >
                PLATFORM CONTROL PLANE
              </Typography>

            </Box>
          </Stack>


          <Box
            sx={{
              mt: 14,
              maxWidth: 580,
            }}
          >

            <Typography
              sx={{
                fontSize: 13,
                letterSpacing: 1.2,
                opacity: 0.65,
                textTransform:
                  "uppercase",
              }}
            >
              Enterprise Application Platform
            </Typography>

            <Typography
              sx={{
                mt: 2,
                fontSize: 42,
                lineHeight: 1.16,
                fontWeight: 500,
                letterSpacing:
                  "-0.025em",
              }}
            >
              Publish. Subscribe.
              Operate.
            </Typography>

            <Typography
              sx={{
                mt: 3,
                maxWidth: 470,
                fontSize: 15,
                lineHeight: 1.8,
                color:
                  "rgba(255,255,255,0.72)",
              }}
            >
              Centralized application
              publishing, commercial
              entitlements, tenant
              subscriptions and runtime
              operations.
            </Typography>

          </Box>
        </Box>


        <Typography
          sx={{
            fontSize: 11,
            opacity: 0.5,
          }}
        >
          AUGMIS Platform ·
          Control Plane
        </Typography>

      </Box>


      {/* LOGIN PANEL */}

      <Box
        sx={{
          display: "grid",
          placeItems: "center",

          bgcolor: "#ffffff",

          px: {
            xs: 3,
            md: 7,
          },
        }}
      >

        <Box
          sx={{
            width: "100%",
            maxWidth: 390,
          }}
        >

          <Typography
            sx={{
              fontSize: 12,
              color: "primary.main",
              fontWeight: 650,
              letterSpacing: 0.8,
              textTransform:
                "uppercase",
            }}
          >
            Secure Access
          </Typography>

          <Typography
            sx={{
              mt: 1,
              fontSize: 30,
              fontWeight: 600,
              letterSpacing:
                "-0.02em",
            }}
          >
            Sign in
          </Typography>

          <Typography
            sx={{
              mt: 1,
              mb: 4,
              color:
                "text.secondary",
              fontSize: 14,
            }}
          >
            Enter your AUGMIS
            platform credentials.
          </Typography>


          {errorMessage && (

            <Alert
              severity="error"
              sx={{
                mb: 3,
              }}
            >
              {errorMessage}
            </Alert>

          )}


          <Box
            component="form"
            onSubmit={
              handleSubmit
            }
          >

            <Stack spacing={2.5}>

              <TextField
                label="Email address"
                type="email"

                value={email}

                onChange={
                  (event) =>
                    setEmail(
                      event.target.value
                    )
                }

                required
                fullWidth
                autoComplete="email"
              />


              <TextField
                label="Password"
                type="password"

                value={password}

                onChange={
                  (event) =>
                    setPassword(
                      event.target.value
                    )
                }

                required
                fullWidth

                autoComplete=
                  "current-password"
              />


              <Button
                type="submit"
                variant="contained"
                size="large"

                disabled={
                  submitting
                }

                sx={{
                  mt: 1,
                  minHeight: 46,
                }}
              >

                {submitting ? (

                  <CircularProgress
                    size={20}
                    color="inherit"
                  />

                ) : (

                  "Sign in to AUGMIS"

                )}

              </Button>

            </Stack>
          </Box>


          <Box
            sx={{
              mt: 5,
              pt: 2.5,

              borderTop:
                "1px solid",

              borderColor:
                "divider",
            }}
          >

            <Typography
              sx={{
                fontSize: 11,
                color:
                  "text.secondary",
              }}
            >
              Authentication is
              provided by the AUGMIS
              Control Plane.
            </Typography>

          </Box>

        </Box>

      </Box>

    </Box>
  );
}