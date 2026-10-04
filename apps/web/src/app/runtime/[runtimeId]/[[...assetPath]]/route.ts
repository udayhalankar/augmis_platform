// apps/web/src/app/runtime/[runtimeId]/[[...assetPath]]/route.ts

import {
  NextRequest,
  NextResponse,
} from "next/server";


export const runtime = "nodejs";

export const dynamic = "force-dynamic";


type RouteContext = {
  params: Promise<{
    runtimeId: string;
    assetPath?: string[];
  }>;
};


const DEFAULT_RUNTIME_API_BASE_URL =
  "http://127.0.0.1:8001";


const DEFAULT_RUNTIME_GATEWAY_ORIGIN =
  "http://127.0.0.1:3000";


function getRuntimeGatewayOrigin(): string {
  const configured =
    (
      process.env.AUGMIS_RUNTIME_GATEWAY_ORIGIN ??
      process.env.NEXT_PUBLIC_RUNTIME_GATEWAY_ORIGIN ??
      DEFAULT_RUNTIME_GATEWAY_ORIGIN
    ).trim();

  const parsed =
    new URL(configured);

  if (
    parsed.protocol !== "http:" &&
    parsed.protocol !== "https:"
  ) {
    throw new Error(
      "Invalid AUGMIS runtime gateway origin."
    );
  }

  return parsed.origin;
}


function getRuntimeHostSuffix():
  string | null {

  const value =
    (
      process.env
        .NEXT_PUBLIC_RUNTIME_HOST_SUFFIX ??
      ""
    )
      .trim()
      .toLowerCase()
      .replace(
        /^\.+|\.+$/g,
        ""
      );


  return value || null;
}


function getConfiguredGatewayPort():
  string {

  const gateway =
    new URL(
      getRuntimeGatewayOrigin()
    );


  if (gateway.port) {
    return gateway.port;
  }


  return (
    gateway.protocol === "https:"
      ? "443"
      : "80"
  );
}

function getRuntimeScopeLabel(
  runtimeId: string
): string | null {

  /*
   * Backend runtime IDs now use:
   *
   * <32 hex random chars>_
   * t-<8 tenant chars>-a-<32 application chars>
   */

  const match =
    runtimeId.match(
      /^[a-f0-9]{32}_(t-[a-f0-9]{8}-a-[a-f0-9]{32})$/i
    );

  if (!match) {
    return null;
  }

  return match[1].toLowerCase();
}

function isExpectedRuntimeHost(
  request: NextRequest,
  runtimeId: string
): boolean {

  const requestHost =
    (
      request.headers.get(
        "host"
      ) ?? ""
    )
      .trim()
      .toLowerCase();

  if (!requestHost) {
    return false;
  }

  const runtimeSuffix =
    getRuntimeHostSuffix();

  /*
   * When isolated runtime hosting is configured,
   * every static runtime MUST use its exact
   * tenant/application hostname.
   */
  if (runtimeSuffix) {

    const scopeLabel =
      getRuntimeScopeLabel(
        runtimeId
      );

    if (!scopeLabel) {
      return false;
    }

    let parsedRequestHost: URL;

    try {

      parsedRequestHost =
        new URL(
          `http://${requestHost}`
        );

    } catch {

      return false;
    }

    const requestHostname =
      parsedRequestHost.hostname
        .toLowerCase();

    const requestPort =
      parsedRequestHost.port ||
      "80";

    const expectedPort =
      getConfiguredGatewayPort();

    if (
      requestPort !==
      expectedPort
    ) {
      return false;
    }

    const expectedHostname =
      `${scopeLabel}.${runtimeSuffix}`;

    return (
      requestHostname ===
      expectedHostname
    );
  }

  /*
   * Compatibility fallback only when isolated
   * runtime host suffix is not configured.
   */
  const configuredGateway =
    new URL(
      getRuntimeGatewayOrigin()
    );

  return (
    requestHost ===
    configuredGateway.host
      .toLowerCase()
  );
}

function getCurrentRuntimeOrigin(
  request: NextRequest
): string {

  const host =
    (
      request.headers.get(
        "host"
      ) ??
      ""
    ).trim();


  if (!host) {
    throw new Error(
      "Runtime request host is missing."
    );
  }


  /*
   * In local development this is http.
   *
   * In production the configured runtime
   * gateway should be HTTPS.
   */
  const protocol =
    request.nextUrl.protocol;


  return `${protocol}//${host}`;
}

function applyGatewaySecurityHeaders(
  headers: Headers
): void {
  headers.set(
    "X-Content-Type-Options",
    "nosniff"
  );

  headers.set(
    "Referrer-Policy",
    "no-referrer"
  );

  headers.set(
    "X-Frame-Options",
    "DENY"
  );

  headers.set(
    "Cross-Origin-Resource-Policy",
    "same-origin"
  );

  headers.set(
    "Cross-Origin-Opener-Policy",
    "same-origin"
  );

  headers.set(
    "Origin-Agent-Cluster",
    "?1"
  );

  headers.set(
    "X-Permitted-Cross-Domain-Policies",
    "none"
  );

  headers.set(
    "Permissions-Policy",
    [
      "camera=()",
      "microphone=()",
      "geolocation=()",
      "payment=()",
      "usb=()",
      "serial=()",
      "bluetooth=()",
      "clipboard-read=()",
      "clipboard-write=()",
      "accelerometer=()",
      "gyroscope=()",
      "magnetometer=()",
      "midi=()",
      "display-capture=()",
    ].join(", ")
  );

  if (
    new URL(
      getRuntimeGatewayOrigin()
    ).protocol === "https:"
  ) {
    headers.set(
      "Strict-Transport-Security",
      "max-age=31536000"
    );
  }
}


function runtimeHostMismatchResponse(): Response {
  const response =
    NextResponse.json(
      {
        error:
          "AUGMIS runtime requests must use the dedicated runtime origin.",
      },
      {
        status: 421,
      }
    );

  response.headers.set(
    "Cache-Control",
    "no-store"
  );

  applyGatewaySecurityHeaders(
    response.headers
  );

  return response;
}


function getRuntimeApiBaseUrl(): string {
  return (
    process.env.AUGMIS_RUNTIME_API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    DEFAULT_RUNTIME_API_BASE_URL
  ).replace(/\/+$/, "");
}


function validateRuntimeId(
  runtimeId: string
): string {
  const value =
    String(runtimeId || "").trim();

  if (
    !value ||
    value.length > 200 ||
    !/^[A-Za-z0-9_-]+$/.test(value)
  ) {
    throw new Error(
      "Invalid AUGMIS runtime ID."
    );
  }

  return value;
}


function validateAssetPath(
  assetPath: string[]
): string[] {
  return assetPath.map(
    (rawSegment) => {
      const segment =
        String(rawSegment || "");

      if (
        !segment ||
        segment === "." ||
        segment === ".." ||
        segment.includes("/") ||
        segment.includes("\\") ||
        segment.includes("\0") ||
        /^[A-Za-z]:/.test(segment)
      ) {
        throw new Error(
          "Invalid AUGMIS runtime asset path."
        );
      }

      return segment;
    }
  );
}


/*
 * MUST stay identical to the FastAPI helper:
 *
 *     "augmis_static_" + safe[:24]
 */
function getRuntimeCookieName(
  runtimeId: string
): string {
  const safeRuntimeId =
    validateRuntimeId(runtimeId);

  return (
    "augmis_static_" +
    safeRuntimeId.slice(0, 24)
  );
}


function buildBackendRuntimeUrl(
  runtimeId: string,
  assetPath: string[],
  search: string
): URL {
  const safeRuntimeId =
    validateRuntimeId(runtimeId);

  const safeAssetPath =
    validateAssetPath(assetPath);

  const baseUrl =
    getRuntimeApiBaseUrl();

  let path =
    `/api/v1/static-runtime/` +
    `${encodeURIComponent(safeRuntimeId)}/`;

  if (safeAssetPath.length > 0) {
    path +=
      safeAssetPath
        .map((segment) =>
          encodeURIComponent(segment)
        )
        .join("/");
  }

  const url =
    new URL(
      path,
      `${baseUrl}/`
    );

  url.search =
    search || "";

  return url;
}


function isExpectedLaunchRedirect(
  location: string,
  runtimeId: string
): boolean {
  try {
    const backendBase =
      getRuntimeApiBaseUrl();

    const backendOrigin =
      new URL(
        backendBase
      ).origin;

    const target =
      new URL(
        location,
        `${backendBase}/`
      );

    const expectedPath =
      `/api/v1/static-runtime/` +
      `${encodeURIComponent(runtimeId)}/`;

    return (
      target.origin === backendOrigin &&
      target.pathname === expectedPath &&
      !target.search
    );
  } catch {
    return false;
  }
}


function rewriteInternalRuntimeRedirect(
  location: string,
  runtimeId: string,
  gatewayOrigin: string
): string {
  const backendBase =
    getRuntimeApiBaseUrl();

  const backendOrigin =
    new URL(
      backendBase
    ).origin;

  const target =
    new URL(
      location,
      `${backendBase}/`
    );

  const expectedPrefix =
    `/api/v1/static-runtime/` +
    `${encodeURIComponent(runtimeId)}/`;

  if (
    target.origin !== backendOrigin ||
    !target.pathname.startsWith(
      expectedPrefix
    )
  ) {
    throw new Error(
      "Runtime redirect escaped its assigned runtime boundary."
    );
  }

  const relativePath =
    target.pathname.slice(
      expectedPrefix.length
    );

  const gatewayUrl =
    new URL(
      `/runtime/${encodeURIComponent(
        runtimeId
      )}/`,
      gatewayOrigin
    );

  if (relativePath) {
    const segments =
      validateAssetPath(
        relativePath
          .split("/")
          .filter(Boolean)
          .map((segment) =>
            decodeURIComponent(segment)
          )
      );

    gatewayUrl.pathname +=
      segments
        .map((segment) =>
          encodeURIComponent(segment)
        )
        .join("/");
  }

  gatewayUrl.search =
    target.search;

  return (
    gatewayUrl.pathname +
    gatewayUrl.search
  );
}


function shouldStripResponseHeader(
  name: string
): boolean {
  const lower =
    name.toLowerCase();

  return (
    lower === "content-length" ||
    lower === "transfer-encoding" ||
    lower === "connection" ||
    lower === "keep-alive" ||
    lower === "set-cookie" ||
    lower === "location"
  );
}


function blockedMethodResponse():
  Response {
  return NextResponse.json(
    {
      error:
        "Static AUGMIS runtimes are read-only.",
    },
    {
      status: 405,
      headers: {
        Allow: "GET, HEAD",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
        "Cross-Origin-Resource-Policy": "same-origin",
      },
    }
  );
}

function isLocalDevelopmentHostname(
  hostname: string
): boolean {

  const value =
    String(hostname || "")
      .trim()
      .toLowerCase();


  return (
    value === "localhost" ||
    value.endsWith(
      ".localhost"
    ) ||
    value === "127.0.0.1" ||
    value === "::1" ||
    value === "[::1]"
  );
}


function getUpstreamSetCookieHeaders(
  response: Response
): string[] {
  const headers =
    response.headers as Headers & {
      getSetCookie?: () => string[];
    };

  if (
    typeof headers.getSetCookie ===
    "function"
  ) {
    return headers.getSetCookie();
  }

  const single =
    response.headers.get(
      "set-cookie"
    );

  return single
    ? [single]
    : [];
}


function getUpstreamRuntimeCookieValue(
  response: Response,
  expectedCookieName: string
): string | null {
  const setCookies =
    getUpstreamSetCookieHeaders(
      response
    );

  for (
    const setCookie of setCookies
  ) {
    const firstPart =
      setCookie
        .split(";", 1)[0]
        ?.trim();

    if (!firstPart) {
      continue;
    }

    const separatorIndex =
      firstPart.indexOf("=");

    if (separatorIndex <= 0) {
      continue;
    }

    const cookieName =
      firstPart
        .slice(
          0,
          separatorIndex
        )
        .trim();

    const cookieValue =
      firstPart
        .slice(
          separatorIndex + 1
        )
        .trim();

    if (
      cookieName ===
        expectedCookieName &&
      cookieValue
    ) {
      return cookieValue;
    }
  }

  return null;
}

async function proxyRuntimeRequest(
  request: NextRequest,
  context: RouteContext
): Promise<Response> {
  /*
   * STEP 3D-D3:
   * Runtime content must never be served from the AUGMIS
   * platform origin. Only the configured dedicated runtime
   * host may enter this gateway.
   */
 

  let runtimeId: string;
  let assetPath: string[];

  try {
    const params =
      await context.params;

    runtimeId =
      validateRuntimeId(
        params.runtimeId
      );

    assetPath =
      validateAssetPath(
        params.assetPath ?? []
      );
  } catch {
    return NextResponse.json(
      {
        error:
          "Invalid AUGMIS runtime request.",
      },
      {
        status: 400,
        headers: {
          "Cache-Control":
            "no-store",
        },
      }
    );
  }


  /*
 * STEP 3D-D5B:
 *
 * The browser hostname must correspond exactly
 * to the tenant/application scope embedded in
 * this runtime ID.
 */
if (
  !isExpectedRuntimeHost(
    request,
    runtimeId
  )
) {
  return runtimeHostMismatchResponse();
}


  /*
   * Root runtime URL is normalised to a trailing slash.
   * The launch ticket is preserved during this redirect.
   */
  if (
    assetPath.length === 0 &&
    !request.nextUrl.pathname.endsWith("/")
  ) {
    
    const currentRuntimeOrigin =
  getCurrentRuntimeOrigin(
    request
  );


const normalisedUrl =
  new URL(
    `${request.nextUrl.pathname}/`,
    `${currentRuntimeOrigin}/`
  );


normalisedUrl.search =
  request.nextUrl.search;

return NextResponse.redirect(
  normalisedUrl,
  307
);
    }

  let backendUrl: URL;

  try {
    backendUrl =
      buildBackendRuntimeUrl(
        runtimeId,
        assetPath,
        request.nextUrl.search
      );
  } catch {
    return NextResponse.json(
      {
        error:
          "Invalid AUGMIS runtime path.",
      },
      {
        status: 400,
        headers: {
          "Cache-Control":
            "no-store",
        },
      }
    );
  }

  const upstreamHeaders =
    new Headers();

  const accept =
    request.headers.get(
      "accept"
    );

  const acceptLanguage =
    request.headers.get(
      "accept-language"
    );

  const userAgent =
    request.headers.get(
      "user-agent"
    );

  if (accept) {
    upstreamHeaders.set(
      "accept",
      accept
    );
  }

  if (acceptLanguage) {
    upstreamHeaders.set(
      "accept-language",
      acceptLanguage
    );
  }

  if (userAgent) {
    upstreamHeaders.set(
      "user-agent",
      userAgent
    );
  }

  /*
   * Forward ONLY the cookie belonging to this exact runtime.
   */
  const runtimeCookieName =
    getRuntimeCookieName(
      runtimeId
    );

  const runtimeCookie =
    request.cookies.get(
      runtimeCookieName
    );

  if (runtimeCookie?.value) {
    upstreamHeaders.set(
      "cookie",
      `${runtimeCookieName}=${runtimeCookie.value}`
    );
  }

  let upstream: Response;

  try {
    upstream =
      await fetch(
        backendUrl,
        {
          method:
            request.method,
          headers:
            upstreamHeaders,
          redirect:
            "manual",
          cache:
            "no-store",
        }
      );
  } catch (error) {
    console.error(
      "AUGMIS runtime gateway upstream failure:",
      error
    );

    return NextResponse.json(
      {
        error:
          "AUGMIS runtime service is unavailable.",
      },
      {
        status: 502,
        headers: {
          "Cache-Control":
            "no-store",
        },
      }
    );
  }

  /*
   * Launch-ticket exchange.
   *
   * FastAPI validates the ticket first. Only if it returns the
   * expected 303 do we establish the browser-facing cookie.
   */
  const launchTicket =
    request.nextUrl.searchParams.get(
      "ticket"
    );

  if (launchTicket) {
    if (
      upstream.status !== 303
    ) {
      const responseHeaders =
        new Headers();

      upstream.headers.forEach(
        (value, name) => {
          if (
            !shouldStripResponseHeader(
              name
            )
          ) {
            responseHeaders.set(
              name,
              value
            );
          }
        }
      );

      responseHeaders.set(
        "Cache-Control",
        "no-store"
      );
      responseHeaders.set(
        "X-Content-Type-Options",
        "nosniff"
      );
      responseHeaders.set(
        "Referrer-Policy",
        "no-referrer"
      );

      return new Response(
        request.method === "HEAD"
          ? null
          : upstream.body,
        {
          status:
            upstream.status,
          statusText:
            upstream.statusText,
          headers:
            responseHeaders,
        }
      );
    }

    const backendLocation =
      upstream.headers.get(
        "location"
      );

    if (
      !backendLocation ||
      !isExpectedLaunchRedirect(
        backendLocation,
        runtimeId
      )
    ) {
      return NextResponse.json(
        {
          error:
            "AUGMIS blocked an invalid runtime launch redirect.",
        },
        {
          status: 502,
          headers: {
            "Cache-Control":
              "no-store",
          },
        }
      );
    }

    /*
     * Redirect browser to the clean gateway URL.
     */
    const currentRuntimeOrigin =
  getCurrentRuntimeOrigin(
    request
  );


const cleanGatewayUrl =
  new URL(
    `/runtime/${encodeURIComponent(
      runtimeId
    )}/`,
    `${currentRuntimeOrigin}/`
  );

    /*
 * STEP 3D-D5:
 *
 * FastAPI performs a one-time ticket exchange.
 *
 * IMPORTANT:
 *
 * launchTicket is NOT the runtime session secret.
 *
 * FastAPI:
 *
 *   1. validates launchTicket
 *   2. invalidates launchTicket
 *   3. generates a new random session secret
 *   4. stores only its hash
 *   5. returns the new secret in Set-Cookie
 *
 * Therefore the gateway must extract the
 * backend-issued runtime session secret and
 * place THAT value in the browser-facing
 * runtime cookie.
 */

const backendSessionSecret =
  getUpstreamRuntimeCookieValue(
    upstream,
    runtimeCookieName
  );

if (!backendSessionSecret) {
  console.error(
    "[AUGMIS runtime gateway] " +
      "backend session cookie missing",
    {
      runtimeId,
      runtimeCookieName,
      upstreamStatus:
        upstream.status,
      hasSetCookie:
        Boolean(
          upstream.headers.get(
            "set-cookie"
          )
        ),
    }
  );

  return NextResponse.json(
    {
      error:
        "AUGMIS runtime session exchange failed.",
    },
    {
      status: 502,
      headers: {
        "Cache-Control":
          "no-store",
        "X-Content-Type-Options":
          "nosniff",
      },
    }
  );
}


const response =
  NextResponse.redirect(
    cleanGatewayUrl,
    303
  );


response.cookies.set({
  name:
    runtimeCookieName,

  /*
   * CRITICAL:
   * Use FastAPI's newly-issued SESSION
   * secret, never the launch ticket.
   */
  value:
    backendSessionSecret,

  httpOnly:
    true,

  sameSite:
    "lax",

  secure:
    new URL(
      currentRuntimeOrigin
    ).protocol ===
    "https:",

  /*
   * Keep browser cookie scoped to this
   * individual runtime.
   */
  path:
    `/runtime/${runtimeId}/`,
});


response.headers.set(
  "Cache-Control",
  "no-store"
);

applyGatewaySecurityHeaders(
  response.headers
);

console.log(
  "[AUGMIS runtime gateway] " +
    "session exchange accepted",
  {
    runtimeId,
    runtimeCookieName,
    cookiePath:
      `/runtime/${runtimeId}/`,
    sessionSecretPresent:
      Boolean(
        backendSessionSecret
      ),
  }
);

  return response;

      }

  /*
   * Normal static runtime response.
   */
  const responseHeaders =
    new Headers();

  upstream.headers.forEach(
    (value, name) => {
      if (
        !shouldStripResponseHeader(
          name
        )
      ) {
        responseHeaders.set(
          name,
          value
        );
      }
    }
  );

  const location =
    upstream.headers.get(
      "location"
    );

  if (location) {
    try {
      
      const rewrittenLocation =
        rewriteInternalRuntimeRedirect(
          location,
          runtimeId,
          getCurrentRuntimeOrigin(
            request
          )
        );

      responseHeaders.set(
        "Location",
        rewrittenLocation
      );
    } catch {
      return NextResponse.json(
        {
          error:
            "Runtime redirect was blocked by AUGMIS.",
        },
        {
          status: 502,
          headers: {
            "Cache-Control":
              "no-store",
          },
        }
      );
    }
  }

  applyGatewaySecurityHeaders(
    responseHeaders
  );

  if (
    request.method === "HEAD"
  ) {
    return new Response(
      null,
      {
        status:
          upstream.status,
        statusText:
          upstream.statusText,
        headers:
          responseHeaders,
      }
    );
  }

  return new Response(
    upstream.body,
    {
      status:
        upstream.status,
      statusText:
        upstream.statusText,
      headers:
        responseHeaders,
    }
  );
}


export async function GET(
  request: NextRequest,
  context: RouteContext
): Promise<Response> {
  return proxyRuntimeRequest(
    request,
    context
  );
}


export async function HEAD(
  request: NextRequest,
  context: RouteContext
): Promise<Response> {
  return proxyRuntimeRequest(
    request,
    context
  );
}


export async function POST():
  Promise<Response> {
  return blockedMethodResponse();
}


export async function PUT():
  Promise<Response> {
  return blockedMethodResponse();
}


export async function PATCH():
  Promise<Response> {
  return blockedMethodResponse();
}


export async function DELETE():
  Promise<Response> {
  return blockedMethodResponse();
}
