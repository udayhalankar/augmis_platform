// C1-D4 same-origin transport ONLY for refresh-cookie exchanges.
// Authentication, authorization and session policy remain authoritative in FastAPI.
import { NextRequest, NextResponse } from "next/server";

const allowedActions = new Set(["login", "refresh", "logout"]);

export async function POST(request: NextRequest, context: { params: Promise<{ action: string }> }) {
  const { action } = await context.params;
  if (!allowedActions.has(action)) return NextResponse.json({ detail: "Not found" }, { status: 404 });
  const origin = new URL(request.url).origin;
  if (request.headers.get("origin") !== origin || request.headers.get("x-augmis-csrf") !== "1") {
    return NextResponse.json({ detail: "SESSION_ORIGIN_DENIED" }, { status: 403 });
  }
  const controlPlane = process.env.AUGMIS_SESSION_API_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8001";
  const body = action === "login" ? await request.text() : "{}";
  // Only forward the AUGMIS refresh cookie, never unrelated console cookies.
  const cookieHeader = (request.headers.get("cookie") ?? "").split(";")
    .map(value => value.trim())
    .filter(value => value.startsWith("__Host-augmis_refresh=") || value.startsWith("augmis_dev_refresh="))
    .join("; ");
  if (body.length > 8192) return NextResponse.json({ detail: "Request too large" }, { status: 413 });
  try {
    const upstream = await fetch(`${controlPlane.replace(/\/$/, "")}/api/v1/auth/${action}`, {
      method: "POST", cache: "no-store", redirect: "manual",
      headers: {
        "Content-Type": "application/json",
        "X-Augmis-CSRF": "1", Origin: origin,
        Cookie: action === "login" ? "" : cookieHeader,
      },
      body,
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
