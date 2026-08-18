"use client";

import { useEffect } from "react";

import { applyUserPlatformRole } from "@/lib/auth/session";
import {
  clearAuthTokens,
  getAccessToken,
  isJwtExpired,
  setAccessToken,
} from "@/lib/auth/tokens";
import { useBotStore } from "@/store/useBotStore";

/**
 * Remirror access-token cookie after F5 and keep platform-role cookie in sync.
 * Middleware can only read cookies — not localStorage.
 *
 * If localStorage has no token, clear stale auth cookies so middleware does not
 * treat a leftover cookie as a live session.
 */
export function AuthSessionBootstrap() {
  const currentUser = useBotStore((state) => state.currentUser);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      clearAuthTokens();
      return;
    }
    // Remirror cookie Max-Age; skip remirroring clearly expired JWTs
    // (silent refresh on the next API call will renew when possible).
    if (!token.startsWith("imp_") && isJwtExpired(token, 0)) {
      return;
    }
    setAccessToken(token);
  }, []);

  useEffect(() => {
    if (currentUser) {
      applyUserPlatformRole(currentUser);
    }
  }, [currentUser]);

  return null;
}
