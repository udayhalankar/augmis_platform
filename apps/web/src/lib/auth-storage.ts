// C1-D4: short-lived access tokens exist only in JS memory.
// The rotating refresh secret is an HttpOnly cookie; never read or store it in JS.
let accessToken: string | null = null;
let accessExpiry = 0;
let idleDeadline = 0;
let absoluteDeadline = 0;
let idleMinutes = 30;

export type SessionTokens = {
  access_token: string;
  accessExpiresInSeconds: number;
  idleMinutes: number;
  lastActivityAt: string;
  idleDeadline: string;
  absoluteDeadline: string;
};

export function getAccessToken(): string | null { return accessToken; }
export function tokenNeedsRenewal(): boolean { return !accessToken || Date.now() + 45000 >= accessExpiry; }
export function getSessionDeadline(): number { return Math.min(idleDeadline, absoluteDeadline); }
export function getSessionIdleMinutes(): number { return idleMinutes; }
export function setAccessToken(token: string): void { accessToken = token; }
export function applySession(data: SessionTokens): void {
  accessToken = data.access_token;
  accessExpiry = Date.now() + data.accessExpiresInSeconds * 1000;
  idleMinutes = data.idleMinutes;
  idleDeadline = Date.parse(data.idleDeadline);
  absoluteDeadline = Date.parse(data.absoluteDeadline);
}
export function applyActivity(data: { idleMinutes: number; lastActivityAt: string; idleDeadline: string }): void {
  idleMinutes = data.idleMinutes;
  idleDeadline = Date.parse(data.idleDeadline);
}
export function clearAccessToken(): void {
  accessToken = null;
  accessExpiry = 0;
  idleDeadline = 0;
  absoluteDeadline = 0;
  if (typeof window !== "undefined") {
    // Remove previous implementation's persistent token on upgrade.
    window.sessionStorage.removeItem("augmis_access_token");
  }
}
