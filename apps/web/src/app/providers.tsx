"use client";

import {
  ReactNode,
} from "react";

import {
  CssBaseline,
  ThemeProvider,
} from "@mui/material";

import {
  AuthProvider,
} from "@/context/auth-context";

import {
  TenantProvider,
} from "@/context/tenant-context";

import theme from "@/theme";


export default function Providers({
  children,
}: {
  children: ReactNode;
}) {

  return (
    <ThemeProvider
      theme={theme}
    >
      <CssBaseline />

      <AuthProvider>

        <TenantProvider>
          {children}
        </TenantProvider>

      </AuthProvider>

    </ThemeProvider>
  );
}