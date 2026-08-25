/**
 * Auth token storage — localStorage + cookie mirrors for Next.js middleware.
 */

export const ACCESS_TOKEN_KEY = "access_token";
export const REFRESH_TOKEN_KEY = "refresh_token";
export const ADMIN_ACCESS_TOKEN_KEY = "admin_access_token";
export const IMPERSONATION_TOKEN_KEY = "impersonation_token";
export const IMPERSONATED_USER_ID_KEY = "impersonated_user_id";

/** Cookie names readable by middleware (Edge). */
export const ACCESS_TOKEN_COOKIE = "mpai_access_token";
export const PLATFORM_ROLE_COOKIE = "mpai_platform_role";

export type PlatformRoleCookie = "SUPERADMIN" | "SUPPORT" | "USER";

function canUseStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function setCookie(name: string, value: string, maxAgeSeconds: number): void {
  if (typeof document === "undefined") return;
  const secure = typeof window !== "undefined" && window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${name}=${encodeURIComponent(value)}; Path=/; Max-Age=${maxAgeSeconds}; SameSite=Lax${secure}`;
}

function clearCookie(name: string): void {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=; Path=/; Max-Age=0; SameSite=Lax`;
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  if (canUseStorage()) {
    const fromStorage = window.localStorage.getItem(ACCESS_TOKEN_KEY);
    if (fromStorage) return fromStorage;
  }
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${ACCESS_TOKEN_COOKIE}=([^;]*)`),
  );
  return match ? decodeURIComponent(match[1]) : null;
}

export function getRefreshToken(): string | null {
  if (!canUseStorage()) return null;
  return window.localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function getAdminAccessToken(): string | null {
  if (!canUseStorage()) return null;
  return window.localStorage.getItem(ADMIN_ACCESS_TOKEN_KEY);
}

export function getImpersonationToken(): string | null {
  if (!canUseStorage()) return null;
  return (
    window.localStorage.getItem(IMPERSONATION_TOKEN_KEY) ||
    (getAccessToken()?.startsWith("imp_") ? getAccessToken() : null)
  );
}

export function getImpersonatedUserId(): string | null {
  if (!canUseStorage()) return null;
  return window.localStorage.getItem(IMPERSONATED_USER_ID_KEY);
}

/**
 * Persist access token and mirror into a cookie for middleware route guards.
 * Default Max-Age aligns with shortened access JWT TTL (60 minutes).
 */
export function setAccessToken(token: string | null, expiresInSeconds = 60 * 60): void {
  if (!canUseStorage()) return;
  if (!token) {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY);
    clearCookie(ACCESS_TOKEN_COOKIE);
    return;
  }
  window.localStorage.setItem(ACCESS_TOKEN_KEY, token);
  setCookie(ACCESS_TOKEN_COOKIE, token, Math.max(60, expiresInSeconds));
}

export function setRefreshToken(token: string | null): void {
  if (!canUseStorage()) return;
  if (!token) {
    window.localStorage.removeItem(REFRESH_TOKEN_KEY);
    return;
  }
  window.localStorage.setItem(REFRESH_TOKEN_KEY, token);
}

export function setAdminAccessToken(token: string | null): void {
  if (!canUseStorage()) return;
  if (!token) {
    window.localStorage.removeItem(ADMIN_ACCESS_TOKEN_KEY);
    return;
  }
  window.localStorage.setItem(ADMIN_ACCESS_TOKEN_KEY, token);
}

export function setImpersonationToken(token: string | null): void {
  if (!canUseStorage()) return;
  if (!token) {
    window.localStorage.removeItem(IMPERSONATION_TOKEN_KEY);
    return;
  }
  window.localStorage.setItem(IMPERSONATION_TOKEN_KEY, token);
}

export function setImpersonatedUserId(userId: string | null): void {
  if (!canUseStorage()) return;
  if (!userId) {
    window.localStorage.removeItem(IMPERSONATED_USER_ID_KEY);
    return;
  }
  window.localStorage.setItem(IMPERSONATED_USER_ID_KEY, userId);
}

export function setPlatformRoleCookie(role: PlatformRoleCookie | null): void {
  if (role) {
    setCookie(PLATFORM_ROLE_COOKIE, role, 60 * 60 * 24 * 7);
  } else {
    clearCookie(PLATFORM_ROLE_COOKIE);
  }
}

export function setTokenPair(params: {
  accessToken: string;
  refreshToken?: string | null;
  expiresIn?: number;
  platformRole?: PlatformRoleCookie | null;
}): void {
  setAccessToken(params.accessToken, params.expiresIn ?? 60 * 60);
  if (params.refreshToken !== undefined) {
    setRefreshToken(params.refreshToken);
  }
  if (params.platformRole !== undefined) {
    setPlatformRoleCookie(params.platformRole);
  }
}

/** Wipe all auth + impersonation tokens (failed refresh / sign-out). */
export function clearAuthTokens(): void {
  if (!canUseStorage()) return;
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  window.localStorage.removeItem(REFRESH_TOKEN_KEY);
  window.localStorage.removeItem(ADMIN_ACCESS_TOKEN_KEY);
  window.localStorage.removeItem(IMPERSONATION_TOKEN_KEY);
  window.localStorage.removeItem(IMPERSONATED_USER_ID_KEY);
  // Impersonation snapshot keys (defined in lib/impersonation.ts).
  window.localStorage.removeItem("original_admin_token");
  window.localStorage.removeItem("impersonation_meta");
  clearCookie(ACCESS_TOKEN_COOKIE);
  clearCookie(PLATFORM_ROLE_COOKIE);
}

/**
 * Decode JWT payload without verifying signature (client UX / cookie role only).
 */
export function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split(".");
    if (parts.length < 2) return null;
    let b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const pad = (4 - (b64.length % 4)) % 4;
    b64 += "=".repeat(pad);
    const json = atob(b64);
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function isJwtExpired(token: string, skewSeconds = 30): boolean {
  const payload = decodeJwtPayload(token);
  if (!payload || typeof payload.exp !== "number") {
    // Opaque impersonation tokens (imp_*) — expiry tracked separately in meta.
    return false;
  }
  return payload.exp * 1000 <= Date.now() + skewSeconds * 1000;
}

export function redirectToLoginExpired(): void {
  if (typeof window === "undefined") return;
  const path = window.location.pathname + window.location.search;
  const from =
    path && path !== "/login" && !path.startsWith("/login?")
      ? `?expired=true&from=${encodeURIComponent(path)}`
      : "?expired=true";
  window.location.assign(`/login${from}`);
}
