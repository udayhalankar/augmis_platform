// apps/web/src/lib/platform-settings.ts
import api from "@/lib/api";

export type PlatformEmailSettings = {
  provider: string;
  enabled: boolean;
  host: string;
  port: number;
  username: string;
  credentialConfigured: boolean;
  fromEmail: string;
  fromName: string;
  useStarttls: boolean;
  useSsl: boolean;
  timeoutSeconds: number;
  source: string;
  updatedAt: string | null;
};

export type UpdatePlatformEmailSettings = {
  provider: string;
  enabled: boolean;
  host: string;
  port: number;
  username: string;
  credential?: string;
  clearCredential?: boolean;
  fromEmail: string;
  fromName: string;
  useStarttls: boolean;
  useSsl: boolean;
  timeoutSeconds: number;
};

export type PlatformEmailTestResult = {
  status: string;
  recipient: string;
  provider: string;
  source: string;
};

export async function loadPlatformEmailSettings():
Promise<PlatformEmailSettings> {
  const response = await api.get<PlatformEmailSettings>(
    "/api/v1/platform/settings/email"
  );
  return response.data;
}

export async function savePlatformEmailSettings(
  payload: UpdatePlatformEmailSettings
): Promise<PlatformEmailSettings> {
  const response = await api.put<PlatformEmailSettings>(
    "/api/v1/platform/settings/email",
    payload
  );
  return response.data;
}

export async function sendPlatformEmailTest(
  recipient: string
): Promise<PlatformEmailTestResult> {
  const response = await api.post<PlatformEmailTestResult>(
    "/api/v1/platform/settings/email/test",
    { recipient }
  );
  return response.data;
}
