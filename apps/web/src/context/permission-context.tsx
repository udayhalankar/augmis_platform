"use client";

import { createContext, ReactNode, useCallback, useContext, useEffect,
  useMemo, useRef, useState } from "react";
import { useAuth } from "@/context/auth-context";
import { useTenant } from "@/context/tenant-context";
import { loadMyPlatformPermissions, loadMyTenantPermissions } from "@/lib/rbac";

type PermissionContextValue = {
  platformPermissions: string[];
  tenantPermissions: string[];
  platformLoading: boolean;
  tenantLoading: boolean;
  hasPlatformPermission: (code: string) => boolean;
  hasTenantPermission: (code: string) => boolean;
  hasAnyPlatformPermission: (codes: string[]) => boolean;
  hasAnyTenantPermission: (codes: string[]) => boolean;
  refreshPermissions: () => Promise<void>;
};
type Snapshot = { scopeKey: string; permissions: string[] };
const PermissionContext = createContext<PermissionContextValue | undefined>(undefined);

export function PermissionProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const { selectedTenantId, loading: tenantContextLoading } = useTenant();
  const userId = user?.id ?? "";
  const tenantKey = userId && !tenantContextLoading && selectedTenantId
    ? `${userId}:${selectedTenantId}` : "";

  const [platformSnapshot, setPlatformSnapshot] = useState<Snapshot | null>(null);
  const [tenantSnapshot, setTenantSnapshot] = useState<Snapshot | null>(null);
  const [previousUserId, setPreviousUserId] = useState(userId);
  if (previousUserId !== userId) {
    setPreviousUserId(userId);
    setPlatformSnapshot(null);
    setTenantSnapshot(null);
  }
  const platformRequest = useRef(0);
  const tenantRequest = useRef(0);

  // Previous-account and previous-tenant responses never grant UI capabilities.
  const platformPermissions = useMemo(() =>
    userId && platformSnapshot?.scopeKey === userId
      ? platformSnapshot.permissions : [], [userId, platformSnapshot]);
  const tenantPermissions = useMemo(() =>
    tenantKey && tenantSnapshot?.scopeKey === tenantKey
      ? tenantSnapshot.permissions : [], [tenantKey, tenantSnapshot]);
  const platformLoading = Boolean(userId && platformSnapshot?.scopeKey !== userId);
  const tenantLoading = tenantContextLoading || Boolean(tenantKey && tenantSnapshot?.scopeKey !== tenantKey);

  const refreshPlatformPermissions = useCallback(async () => {
    if (!userId) return;
    const serial = ++platformRequest.current;
    try {
      const response = await loadMyPlatformPermissions();
      if (serial === platformRequest.current) setPlatformSnapshot({
        scopeKey: userId,
        permissions: Array.isArray(response.permissions) ? response.permissions : [],
      });
    } catch {
      if (serial === platformRequest.current) setPlatformSnapshot({ scopeKey: userId, permissions: [] });
    }
  }, [userId]);

  const refreshTenantPermissions = useCallback(async () => {
    if (!tenantKey) return;
    const serial = ++tenantRequest.current;
    try {
      const response = await loadMyTenantPermissions(selectedTenantId);
      if (serial === tenantRequest.current) setTenantSnapshot({
        scopeKey: tenantKey,
        permissions: Array.isArray(response.permissions) ? response.permissions : [],
      });
    } catch {
      if (serial === tenantRequest.current) setTenantSnapshot({ scopeKey: tenantKey, permissions: [] });
    }
  }, [tenantKey, selectedTenantId]);

  useEffect(() => {
    if (!userId) { platformRequest.current += 1; return; }
    let active = true;
    const serial = ++platformRequest.current;
    void loadMyPlatformPermissions().then((response) => {
      if (active && serial === platformRequest.current) setPlatformSnapshot({
        scopeKey: userId,
        permissions: Array.isArray(response.permissions) ? response.permissions : [],
      });
    }).catch(() => {
      if (active && serial === platformRequest.current) setPlatformSnapshot({ scopeKey: userId, permissions: [] });
    });
    return () => { active = false; };
  }, [userId]);

  useEffect(() => {
    if (!tenantKey) { tenantRequest.current += 1; return; }
    let active = true;
    const serial = ++tenantRequest.current;
    void loadMyTenantPermissions(selectedTenantId).then((response) => {
      if (active && serial === tenantRequest.current) setTenantSnapshot({
        scopeKey: tenantKey,
        permissions: Array.isArray(response.permissions) ? response.permissions : [],
      });
    }).catch(() => {
      if (active && serial === tenantRequest.current) setTenantSnapshot({ scopeKey: tenantKey, permissions: [] });
    });
    return () => { active = false; };
  }, [tenantKey, selectedTenantId]);

  const hasPlatformPermission = useCallback((code: string) => platformPermissions.includes(code), [platformPermissions]);
  const hasTenantPermission = useCallback((code: string) => tenantPermissions.includes(code), [tenantPermissions]);
  const hasAnyPlatformPermission = useCallback((codes: string[]) =>
    codes.some((code) => platformPermissions.includes(code)), [platformPermissions]);
  const hasAnyTenantPermission = useCallback((codes: string[]) =>
    codes.some((code) => tenantPermissions.includes(code)), [tenantPermissions]);
  const refreshPermissions = useCallback(async () => {
    await Promise.all([refreshPlatformPermissions(), refreshTenantPermissions()]);
  }, [refreshPlatformPermissions, refreshTenantPermissions]);

  const value = useMemo<PermissionContextValue>(() => ({
    platformPermissions, tenantPermissions, platformLoading, tenantLoading,
    hasPlatformPermission, hasTenantPermission,
    hasAnyPlatformPermission, hasAnyTenantPermission, refreshPermissions,
  }), [platformPermissions, tenantPermissions, platformLoading, tenantLoading,
    hasPlatformPermission, hasTenantPermission,
    hasAnyPlatformPermission, hasAnyTenantPermission, refreshPermissions]);
  return <PermissionContext.Provider value={value}>{children}</PermissionContext.Provider>;
}

export function usePermissions(): PermissionContextValue {
  const context = useContext(PermissionContext);
  if (!context) throw new Error("usePermissions must be used inside PermissionProvider.");
  return context;
}
