/**
 * Impersonation session helpers.
 *
 * Storage keys:
 * - `impersonation_token` — active support Bearer (`imp_*` or JWT typ=impersonation)
 * - `admin_access_token` — admin JWT restored on exit
 * - `impersonated_user_id` — active user context (survives F5)
 * - `impersonation_meta` — UI metadata incl. expires_at
 * - `original_admin_token` — full admin snapshot (user + company) for restore
 * - `access_token` — currently active Bearer used by the API client
 */

import type { CurrentUser } from "@/types/team";
import {
  ACCESS_TOKEN_KEY,
  ADMIN_ACCESS_TOKEN_KEY,
  getAccessToken,
  getAdminAccessToken,
  getImpersonatedUserId,
  getImpersonationToken,
  IMPERSONATED_USER_ID_KEY,
  IMPERSONATION_TOKEN_KEY,
  setAccessToken,
  setAdminAccessToken,
  setImpersonatedUserId,
  setImpersonationToken,
  setPlatformRoleCookie,
} from "@/lib/auth/tokens";

export {
  ACCESS_TOKEN_KEY,
  ADMIN_ACCESS_TOKEN_KEY,
  getAccessToken,
  getAdminAccessToken,
  getImpersonatedUserId,
  getImpersonationToken,
  IMPERSONATED_USER_ID_KEY,
  IMPERSONATION_TOKEN_KEY,
  setAccessToken,
};

export const ORIGINAL_ADMIN_TOKEN_KEY = "original_admin_token";
/** Spec alias: raw admin JWT restored after support mode. */
export const ADMIN_TOKEN_BACKUP_KEY = "admin_token_backup";
export const IMPERSONATION_META_KEY = "impersonation_meta";

export interface AdminSessionSnapshot {
  version: 1;
  access_token: string;
  user: CurrentUser;
  active_company_id: string | null;
  saved_at: string;
}

export interface ImpersonationMeta {
  email: string;
  user_id: string;
  /** Alias of user_id — required for F5 resilience / Stage 3 contract. */
  impersonated_user_id: string;
  full_name: string;
  company_name: string;
  impersonated_by: string;
  expires_at: string;
}

function canUseStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

export function getOriginalAdminSnapshot(): AdminSessionSnapshot | null {
  if (!canUseStorage()) return null;
  const raw = window.localStorage.getItem(ORIGINAL_ADMIN_TOKEN_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as AdminSessionSnapshot;
    if (!parsed?.user?.id || !parsed.user.email) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function getImpersonationMeta(): ImpersonationMeta | null {
  if (!canUseStorage()) return null;
  const raw = window.localStorage.getItem(IMPERSONATION_META_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as ImpersonationMeta;
    if (!parsed) return null;
    // Backfill alias after older sessions.
    if (!parsed.impersonated_user_id && parsed.user_id) {
      parsed.impersonated_user_id = parsed.user_id;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function isImpersonating(): boolean {
  return Boolean(
    getOriginalAdminSnapshot() ||
      getAdminAccessToken() ||
      getImpersonationMeta() ||
      getImpersonatedUserId(),
  );
}

export function isImpersonationExpired(meta?: ImpersonationMeta | null): boolean {
  const current = meta ?? getImpersonationMeta();
  if (!current?.expires_at) return false;
  const expires = Date.parse(current.expires_at);
  if (Number.isNaN(expires)) return false;
  return expires <= Date.now();
}

export function beginImpersonationSession(params: {
  adminUser: CurrentUser;
  activeCompanyId: string | null;
  accessToken: string;
  meta: Omit<ImpersonationMeta, "impersonated_user_id"> & {
    impersonated_user_id?: string;
  };
}): void {
  if (!canUseStorage()) return;

  const previousAccess = getAccessToken() || "";
  const snapshot: AdminSessionSnapshot = {
    version: 1,
    access_token: previousAccess,
    user: params.adminUser,
    active_company_id: params.activeCompanyId,
    saved_at: new Date().toISOString(),
  };

  const meta: ImpersonationMeta = {
    ...params.meta,
    impersonated_user_id: params.meta.impersonated_user_id || params.meta.user_id,
  };

  window.localStorage.setItem(ORIGINAL_ADMIN_TOKEN_KEY, JSON.stringify(snapshot));
  window.localStorage.setItem(IMPERSONATION_META_KEY, JSON.stringify(meta));
  window.localStorage.setItem(ADMIN_TOKEN_BACKUP_KEY, previousAccess || "");

  // Canonical Stage 3 keys (survive F5 independently of snapshot JSON).
  setAdminAccessToken(previousAccess || null);
  setImpersonationToken(params.accessToken);
  setImpersonatedUserId(meta.impersonated_user_id);
  setAccessToken(params.accessToken);
  setPlatformRoleCookie("USER");
}

export function clearImpersonationSession(): AdminSessionSnapshot | null {
  if (!canUseStorage()) return null;
  const snapshot = getOriginalAdminSnapshot();
  const backupFromKey = canUseStorage()
    ? window.localStorage.getItem(ADMIN_TOKEN_BACKUP_KEY)
    : null;
  const adminToken =
    getAdminAccessToken() || snapshot?.access_token || backupFromKey || null;

  window.localStorage.removeItem(ORIGINAL_ADMIN_TOKEN_KEY);
  window.localStorage.removeItem(IMPERSONATION_META_KEY);
  window.localStorage.removeItem(ADMIN_TOKEN_BACKUP_KEY);
  setImpersonationToken(null);
  setImpersonatedUserId(null);
  setAdminAccessToken(null);

  if (adminToken) {
    setAccessToken(adminToken);
  } else {
    setAccessToken(null);
  }

  const role = snapshot?.user?.is_superadmin
    ? "SUPERADMIN"
    : snapshot?.user?.is_support
      ? "SUPPORT"
      : "USER";
  setPlatformRoleCookie(role);

  return snapshot;
}
