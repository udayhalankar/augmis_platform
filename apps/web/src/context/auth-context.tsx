"use client";

import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import axios from "axios";
import api, { endServerSession, renewAccess, startServerSession } from "@/lib/api";
import { applyActivity, applySession, clearAccessToken, getAccessToken,
  getSessionDeadline } from "@/lib/auth-storage";

export type AuthUser = { id: string; email: string; first_name: string; last_name: string; status: string };
type AuthContextType = {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
};
const AuthContext = createContext<AuthContextType | undefined>(undefined);
const MESSAGE = "augmis-session-state";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const channel = useRef<BroadcastChannel | null>(null);
  const lastServerTouch = useRef(0);
  const activityInFlight = useRef(false);
  const lastInteraction = useRef(0);
  const sessionGeneration = useRef(0);

  const expireLocal = useCallback((broadcast = true) => {
    sessionGeneration.current++;
    clearAccessToken();
    setUser(null);
    setLoading(false);
    if (broadcast) channel.current?.postMessage({ type: "logout" });
  }, []);

  const logout = useCallback(async () => {
    // A user-initiated logout is revocation, not merely clearing the screen.
    try { await endServerSession(); }
    finally { expireLocal(); }
  }, [expireLocal]);

  const refreshUser = useCallback(async () => {
    const generation = sessionGeneration.current;
    try {
      await renewAccess();
      const me = await api.get<AuthUser>("/api/v1/auth/me");
      if (generation === sessionGeneration.current) setUser(me.data);
    } catch (error) {
      if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) {
        expireLocal();
      } else {
        // Fail closed on initial bootstrap; do not misreport outages as session expiry.
        setUser(null);
      }
    } finally { setLoading(false); }
  }, [expireLocal]);

  const login = useCallback(async (email: string, password: string) => {
    const session = await startServerSession(email, password);
    applySession(session);
    const me = await api.get<AuthUser>("/api/v1/auth/me");
    sessionGeneration.current++;
    setUser(me.data);
    setLoading(false);
    channel.current?.postMessage({ type: "login" });
  }, []);

  useEffect(() => {
    // Explicit logout/login events, not token contents, move across tabs.
    if (typeof BroadcastChannel !== "undefined") {
      channel.current = new BroadcastChannel(MESSAGE);
      channel.current.onmessage = event => {
        if (event.data?.type === "logout") expireLocal(false);
        if (event.data?.type === "login") void refreshUser();
        if (event.data?.type === "activity" && event.data.idleMinutes && event.data.lastActivityAt && event.data.idleDeadline) {
          applyActivity({ idleMinutes: event.data.idleMinutes, lastActivityAt: event.data.lastActivityAt, idleDeadline: event.data.idleDeadline });
        }
      };
    }
    void refreshUser();
    const onExpired = () => expireLocal();
    window.addEventListener("augmis-auth-expired", onExpired);
    return () => {
      window.removeEventListener("augmis-auth-expired", onExpired);
      channel.current?.close(); channel.current = null;
    };
  }, [expireLocal, refreshUser]);

  useEffect(() => {
    if (!user) return;
    // Browser timers improve UX only. Server enforces the actual deadline.
    const enforceDeadline = () => {
      const deadline = getSessionDeadline();
      if (deadline && Date.now() >= deadline) expireLocal();
    };
    const sendActivity = async () => {
      if (activityInFlight.current) return;
      if (Date.now() - lastServerTouch.current < 45000) return;
      const deadline = getSessionDeadline();
      if (!deadline || Date.now() >= deadline) { enforceDeadline(); return; }
      activityInFlight.current = true;
      try {
        const result = await api.post<{ idleMinutes: number; lastActivityAt: string; idleDeadline: string }>("/api/v1/auth/activity", {});
        applyActivity(result.data);
        channel.current?.postMessage({ type: "activity", ...result.data });
        lastServerTouch.current = Date.now();
      } catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 401) expireLocal();
      } finally { activityInFlight.current = false; }
    };
    const onInteraction = (event: Event) => {
      if (!event.isTrusted) return;
      lastInteraction.current = Date.now();
      void sendActivity();
    };
    const onForeground = () => {
      enforceDeadline();
      if (document.visibilityState === "visible" && getAccessToken() && getSessionDeadline() > Date.now()) {
        void api.get<{idleMinutes: number; lastActivityAt: string; idleDeadline: string}>("/api/v1/auth/session")
          .then(result => applyActivity(result.data)).catch(() => undefined);
      }
    };
    const eventNames = ["pointerdown", "pointermove", "keydown", "touchstart"] as const;
    eventNames.forEach(name => window.addEventListener(name, onInteraction, { passive: true }));
    window.addEventListener("focus", onForeground);
    document.addEventListener("visibilitychange", onForeground);
    const timer = window.setInterval(enforceDeadline, 1000);
    return () => {
      eventNames.forEach(name => window.removeEventListener(name, onInteraction));
      window.removeEventListener("focus", onForeground);
      document.removeEventListener("visibilitychange", onForeground);
      window.clearInterval(timer);
    };
  }, [user, expireLocal]);

  return <AuthContext.Provider value={{ user, loading, login, logout, refreshUser }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
