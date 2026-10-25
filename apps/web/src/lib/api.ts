import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";
import {
  applySession, clearAccessToken, getAccessToken, tokenNeedsRenewal,
  SessionTokens,
} from "@/lib/auth-storage";

// In production, normal API requests must use the ALB's same-origin /api/v1/*
// routing. NEXT_PUBLIC_* values are exposed to browsers: never publish a
// private service URL here. Keep the existing development fallback unchanged.
export const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ??
  (process.env.NODE_ENV === "production" ? "" : "http://127.0.0.1:8000");

function assertPublicApiBase(): void {
  if (process.env.NODE_ENV !== "production" || typeof window === "undefined") return;
  let url: URL;
  try { url = new URL(apiBaseUrl || "/", window.location.origin); }
  catch { throw new Error("R01_PUBLIC_API_ORIGIN_INVALID"); }
  if (url.origin !== window.location.origin || url.pathname !== "/" || url.search || url.hash ||
      url.username || url.password) {
    throw new Error("R01_PUBLIC_API_ORIGIN_INVALID");
  }
}

const authTransport = axios.create({ baseURL: "", withCredentials: true, headers: { "X-Augmis-CSRF": "1" } });
export const api = axios.create({ baseURL: apiBaseUrl, withCredentials: true, headers: { "X-Augmis-CSRF": "1" } });
let pendingRenewal: Promise<string> | null = null;

export async function renewAccess(): Promise<string> {
  if (pendingRenewal) return pendingRenewal;
  pendingRenewal = (async () => {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const response = await authTransport.post<SessionTokens>("/api/session/refresh", {});
        applySession(response.data);
        return response.data.access_token;
      } catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 409 && attempt < 2) {
          await new Promise(resolve => setTimeout(resolve, 450 + attempt * 450));
          continue;
        }
        throw error;
      }
    }
    throw new Error("SESSION_RENEWAL_UNAVAILABLE");
  })();
  try { return await pendingRenewal; }
  finally { pendingRenewal = null; }
}

function authPublicPath(url: string | undefined): boolean {
  return !!url && /\/api\/v1\/auth\/(login|register|refresh|logout)$/.test(url.split("?")[0]);
}

function rejectSession(): void {
  clearAccessToken();
  if (typeof window !== "undefined") window.dispatchEvent(new Event("augmis-auth-expired"));
}

api.interceptors.request.use(async (config) => {
  assertPublicApiBase();
  if (!authPublicPath(config.url)) {
    let token = getAccessToken();
    if (tokenNeedsRenewal()) {
      try { token = await renewAccess(); }
      catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 401) rejectSession();
        throw error;
      }
    }
    if (token) config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  response => response,
  async (error: AxiosError) => {
    const request = error.config as (InternalAxiosRequestConfig & { _augmisRetried?: boolean }) | undefined;
    if (error.response?.status === 401 && request && !authPublicPath(request.url)) {
      if (!request._augmisRetried) {
        request._augmisRetried = true;
        try {
          const token = await renewAccess();
          request.headers.Authorization = `Bearer ${token}`;
          return api(request);
        } catch (refreshError) {
          if (axios.isAxiosError(refreshError) && refreshError.response?.status === 401) rejectSession();
          return Promise.reject(refreshError);
        }
      }
      // After a successful session refresh, a resource-level 401 can be
      // authorization-specific; it must not invalidate a valid login.
    }
    return Promise.reject(error);
  },
);

export async function endServerSession(): Promise<void> {
  await authTransport.post("/api/session/logout", {});
}

export default api;

export async function startServerSession(email: string, password: string): Promise<SessionTokens> {
  return (await authTransport.post<SessionTokens>("/api/session/login", {email, password})).data;
}
