import type { Metadata } from "next";

import {
  AppRouterCacheProvider,
} from "@mui/material-nextjs/v15-appRouter";

import Providers from "./providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "AUGMIS Platform",
  description:
    "AUGMIS Application and SaaS Control Plane",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <AppRouterCacheProvider>
          <Providers>
            {children}
          </Providers>
        </AppRouterCacheProvider>
      </body>
    </html>
  );
}