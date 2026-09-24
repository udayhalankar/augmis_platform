"use client";

import {
  ReactNode,
  useEffect,
} from "react";

import {
  Box,
  CircularProgress,
  Typography,
} from "@mui/material";

import {
  useRouter,
} from "next/navigation";

import {
  useAuth,
} from "@/context/auth-context";


export default function ProtectedRoute({
  children,
}: {
  children: ReactNode;
}) {

  const router =
    useRouter();

  const {
    user,
    loading,
  } = useAuth();


  useEffect(
    () => {

      if (
        !loading &&
        !user
      ) {

        router.replace(
          "/login"
        );
      }

    },
    [
      loading,
      user,
      router,
    ]
  );


  if (loading) {

    return (
      <Box
        sx={{
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          bgcolor:
            "background.default",
        }}
      >
        <Box
          sx={{
            textAlign: "center",
          }}
        >
          <CircularProgress
            size={28}
          />

          <Typography
            sx={{
              mt: 2,
              fontSize: 13,
              color:
                "text.secondary",
            }}
          >
            Loading AUGMIS Platform
          </Typography>
        </Box>
      </Box>
    );
  }


  if (!user) {

    return null;
  }


  return (
    <>
      {children}
    </>
  );
}