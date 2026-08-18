/**
 * Admin Panel auth helpers (client-side).
 */

import { useBotStore } from "@/store/useBotStore";
import { setPlatformRoleCookie, type PlatformRoleCookie } from "@/lib/auth/tokens";

export type PlatformRole = PlatformRoleCookie;

export function getPlatformRole(): PlatformRole {
  const user = useBotStore.getState().currentUser;
  if (!user) return "USER";
  if (user.is_superadmin) return "SUPERADMIN";
  if (user.is_support) return "SUPPORT";
  return "USER";
}

export function isSuperAdminUser(): boolean {
  const user = useBotStore.getState().currentUser;
  if (!user) return false;
  if (user.is_superadmin) return true;
  const rawRole = (user as { role?: string }).role;
  return rawRole === "SUPER_ADMIN" || rawRole === "SUPERADMIN";
}

/** Admin Panel is superadmin-only; SUPPORT no longer qualifies. */
export function canAccessAdminPanel(): boolean {
  return isSuperAdminUser();
}

/** Sync middleware-readable platform role cookie from the current user. */
export function syncPlatformRoleCookie(): void {
  setPlatformRoleCookie(getPlatformRole());
}
