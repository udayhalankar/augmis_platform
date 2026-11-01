// apps/web/src/context/tenant-context.tsx
"use client";

import { createContext, ReactNode, useCallback, useContext, useEffect,
  useMemo, useRef, useState } from "react";
import { useAuth } from "@/context/auth-context";
import { loadMyTenants, MyTenantMembership } from "@/lib/tenant-context-api";

const TENANT_STORAGE_KEY = "augmis.platform.selectedTenantId";
type TenantContextType = {
  tenants: MyTenantMembership[];
  selectedTenant: MyTenantMembership | null;
  selectedTenantId: string;
  loading: boolean;
  error: string;
  selectTenant: (tenantId: string) => void;
  refreshTenants: () => Promise<void>;
};
type MembershipSnapshot = { ownerId: string; entries: MyTenantMembership[]; error: string };
type TenantSelection = { ownerId: string; id: string };
const TenantContext = createContext<TenantContextType | undefined>(undefined);

export function TenantProvider({ children }: { children: ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const userId = user?.id ?? "";
  const [snapshot, setSnapshot] = useState<MembershipSnapshot | null>(null);
  const [selection, setSelection] = useState<TenantSelection>({ ownerId: "", id: "" });
  const [previousUserId, setPreviousUserId] = useState(userId);
  if (previousUserId !== userId) {
    setPreviousUserId(userId);
    setSnapshot(null);
    setSelection({ ownerId: "", id: "" });
  }
  const requestSerial = useRef(0);
  const selectionRef = useRef<TenantSelection>({ ownerId: "", id: "" });

  const tenants = useMemo(() => userId && snapshot?.ownerId === userId
    ? snapshot.entries : [], [userId, snapshot]);
  const selectedTenantId = selection.ownerId === userId && tenants.some(
    (membership) => membership.tenant.id === selection.id && membership.status === "active"
  ) ? selection.id : "";
  const loading = Boolean(authLoading || (userId && snapshot?.ownerId !== userId));
  const error = userId && snapshot?.ownerId === userId ? snapshot.error : "";
  const selectedTenant = useMemo(() =>
    tenants.find((entry) => entry.tenant.id === selectedTenantId) ?? null,
    [tenants, selectedTenantId]);

  const selectTenant = useCallback((tenantId: string) => {
    const cleanId = String(tenantId || "").trim();
    if (!userId) return;
    if (!cleanId) {
      selectionRef.current = { ownerId: userId, id: "" };
      setSelection(selectionRef.current);
      if (typeof window !== "undefined") window.localStorage.removeItem(TENANT_STORAGE_KEY);
      return;
    }
    if (!tenants.some((entry) => entry.status === "active" && entry.tenant.id === cleanId)) {
      console.warn("[AUGMIS tenant context] Rejected unauthorized tenant selection");
      return;
    }
    selectionRef.current = { ownerId: userId, id: cleanId };
    setSelection(selectionRef.current);
    if (typeof window !== "undefined") window.localStorage.setItem(TENANT_STORAGE_KEY, cleanId);
  }, [tenants, userId]);

  // Commit only responses belonging to the latest request and the active user.
  // Both initial loading and manual refresh share these post-I/O handlers.
  const commitTenants = useCallback((serial: number, memberships: MyTenantMembership[]) => {
    if (serial !== requestSerial.current) return;
    const active = memberships.filter((member) => member.status === "active");
    const stored = typeof window !== "undefined"
      ? window.localStorage.getItem(TENANT_STORAGE_KEY) || "" : "";
    const candidate = active.some((member) => member.tenant.id === stored)
      ? stored : active[0]?.tenant.id ?? "";
    setSnapshot({ ownerId: userId, entries: active, error: "" });
    const current = selectionRef.current;
    const preferred = current.ownerId === userId && active.some(
      (member) => member.tenant.id === current.id) ? current.id : candidate;
    selectionRef.current = { ownerId: userId, id: preferred };
    setSelection(selectionRef.current);
    if (typeof window !== "undefined") {
      if (preferred) window.localStorage.setItem(TENANT_STORAGE_KEY, preferred);
      else window.localStorage.removeItem(TENANT_STORAGE_KEY);
    }
  }, [userId]);

  const rejectTenants = useCallback((serial: number) => {
    if (serial !== requestSerial.current) return;
    setSnapshot({ ownerId: userId, entries: [], error: "Your tenant memberships could not be loaded." });
    selectionRef.current = { ownerId: userId, id: "" };
    setSelection(selectionRef.current);
  }, [userId]);

  const refreshTenants = useCallback(async () => {
    if (!userId || authLoading) return;
    const serial = ++requestSerial.current;
    try {
      const memberships = await loadMyTenants();
      commitTenants(serial, memberships);
    } catch {
      rejectTenants(serial);
    }
  }, [userId, authLoading, commitTenants, rejectTenants]);

  useEffect(() => {
    if (!userId || authLoading) {
      requestSerial.current += 1;
      return;
    }
    const serial = ++requestSerial.current;
    // Call the external API directly. State is updated only in the async
    // resolution handlers, not synchronously in the effect.
    void loadMyTenants().then(
      (memberships) => commitTenants(serial, memberships),
      () => rejectTenants(serial),
    );
    return () => { requestSerial.current += 1; };
  }, [userId, authLoading, commitTenants, rejectTenants]);

  const value = useMemo<TenantContextType>(() => ({ tenants, selectedTenant,
    selectedTenantId, loading, error, selectTenant, refreshTenants }),
    [tenants, selectedTenant, selectedTenantId, loading, error, selectTenant, refreshTenants]);
  return <TenantContext.Provider value={value}>{children}</TenantContext.Provider>;
}

export function useTenant() {
  const context = useContext(TenantContext);
  if (!context) throw new Error("useTenant must be used inside TenantProvider");
  return context;
}
