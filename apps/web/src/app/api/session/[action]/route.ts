// C1-D4 same-origin transport: authentication stays authoritative in FastAPI.
// R01: production trust comes from configured public origin, never request.url
// or client-supplied X-Forwarded-* headers.
import { NextRequest, NextResponse } from "next/server";

const allowedActions = new Set(["login", "refresh", "logout"]);

function getProductionTransport(): { publicOrigin: string; apiOrigin: string; publicHost: string } | null {
  const env = (process.env.AUGMIS_APP_ENV ?? "").trim().toLowerCase();
  if (env && !["dev", "development", "prod", "production"].includes(env)) {
    throw new Error("R01_APP_ENV_UNRECOGNIZED");
  }
  if (process.env.NODE_ENV !== "production" && !["prod", "production"].includes(env)) return null;

  const configuredOrigin = (process.env.AUGMIS_PUBLIC_ORIGIN ?? "").trim();
  const configuredApi = (process.env.AUGMIS_SESSION_API_URL ?? "").trim();
  try {
    const publicUrl = new URL(configuredOrigin);
    const apiUrl = new URL(configuredApi);
    const hostname = publicUrl.hostname.toLowerCase();
    if (publicUrl.protocol !== "https:" || publicUrl.origin !== configuredOrigin ||
        publicUrl.pathname !== "/" || publicUrl.search || publicUrl.hash ||
        publicUrl.username || publicUrl.password || publicUrl.port ||
        hostname === "localhost" || hostname.endsWith(".localhost") ||
        hostname === "localtest.me" || hostname.endsWith(".localtest.me") ||
        hostname.endsWith(".test") || hostname.endsWith(".invalid") ||
        !hostname.includes(".") || /^\d+\.\d+\.\d+\.\d+$/.test(hostname) ||
        !["http:", "https:"].includes(apiUrl.protocol) || apiUrl.pathname !== "/" ||
        apiUrl.search || apiUrl.hash || apiUrl.username || apiUrl.password ||
        apiUrl.hostname === hostname ||
        ["localhost", "127.0.0.1", "::1"].includes(apiUrl.hostname)) {
      throw new Error("Invalid R01 production session transport configuration");
    }
    return { publicOrigin: configuredOrigin, apiOrigin: apiUrl.origin, publicHost: publicUrl.host };
  } catch {
    throw new Error("R01_SESSION_TRANSPORT_CONFIG_INVALID");
  }
}

// R04: read no more than the allowed login payload, even without Content-Length.
async function boundedLoginBody(request: NextRequest): Promise<string | null> {
  const limit = 8192;
  const header = request.headers.get("content-length");
  if (header !== null && (!/^\d+$/.test(header) || Number(header) > limit)) return null;
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > limit) return null;
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const data = new Uint8Array(total);
  let at = 0;
  for (const chunk of chunks) { data.set(chunk, at); at += chunk.byteLength; }
  return new TextDecoder("utf-8", { fatal: true }).decode(data);
}

export async function POST(request: NextRequest, context: { params: Promise<{ action: string }> }) {
  const { action } = await context.params;
  if (!allowedActions.has(action)) return NextResponse.json({ detail: "Not found" }, { status: 404 });

  let transport: ReturnType<typeof getProductionTransport>;
  try { transport = getProductionTransport(); }
  catch {
    return NextResponse.json({ detail: "SESSION_INGRESS_CONFIG_INVALID" }, { status: 503,
      headers: { "Cache-Control": "no-store" } });
  }
  const origin = transport?.publicOrigin ?? new URL(request.url).origin;
  if ((transport && request.headers.get("host")?.toLowerCase() !== transport.publicHost.toLowerCase()) ||
      request.headers.get("origin") !== origin || request.headers.get("x-augmis-csrf") !== "1") {
    return NextResponse.json({ detail: "SESSION_ORIGIN_DENIED" }, { status: 403,
      headers: { "Cache-Control": "no-store" } });
  }

  // Production has no fallback to a browser-facing or development API target.
  const controlPlane = transport?.apiOrigin ?? process.env.AUGMIS_SESSION_API_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8001";
  let body = "{}";
  if (action === "login") {
    try {
      const parsed = await boundedLoginBody(request);
      if (parsed === null) return NextResponse.json({ detail: "Request too large" }, { status: 413,
        headers: { "Cache-Control": "no-store" } });
      body = parsed;
    } catch {
      return NextResponse.json({ detail: "Invalid login body" }, { status: 400,
        headers: { "Cache-Control": "no-store" } });
    }
  }
  const cookieHeader = (request.headers.get("cookie") ?? "").split(";")
    .map(value => value.trim())
    .filter(value => transport ? value.startsWith("__Host-augmis_refresh=") : value.startsWith("augmis_dev_refresh="))
    .join("; ");
  if (body.length > 8192) return NextResponse.json({ detail: "Request too large" }, { status: 413 });
  try {
    const upstream = await fetch(`${controlPlane.replace(/\/$/, "")}/api/v1/auth/${action}`, {
      method: "POST", cache: "no-store", redirect: "manual",
      signal: AbortSignal.timeout(12000),
      headers: {
        "Content-Type": "application/json", "X-Augmis-CSRF": "1", Origin: origin,
        Cookie: action === "login" ? "" : cookieHeader,
      }, body,
    });
    const result = new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json",
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" },
    });
    const cookie = upstream.headers.get("set-cookie");
    if (cookie) result.headers.set("Set-Cookie", cookie);
    return result;
  } catch {
    return NextResponse.json({ detail: "Authentication service unavailable" }, { status: 503,
      headers: { "Cache-Control": "no-store" } });
  }
}
