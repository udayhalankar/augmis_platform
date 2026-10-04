// apps/web/next.config.ts

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /*
   * AUGMIS static runtimes deliberately use:
   *
   * /runtime/{runtimeId}/
   *
   * The trailing slash is important because uploaded
   * static applications commonly reference relative
   * assets such as:
   *
   *   css/app.css
   *   js/app.js
   *   images/logo.png
   *
   * Without the trailing slash the browser would resolve
   * them outside the runtime directory.
   *
   * AUGMIS therefore owns trailing-slash handling for the
   * runtime gateway. Next.js must not automatically remove it.
   */
  skipTrailingSlashRedirect: true,

  allowedDevOrigins: [
    "127.0.0.1",
    "localhost",

    "localtest.me",
    "runtime.localtest.me",

    // Diagnostic development host.
    "abc.runtime.localtest.me",
  ],
};

export default nextConfig;