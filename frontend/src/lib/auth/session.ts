/**
 * Auth session helpers — login / register / password reset + token persistence.
 */

import axios from "axios";

import { buildApiUrl } from "@/lib/api/baseUrl";
import type { TokenPairResponse } from "@/lib/api/client";
import {
  clearAuthTokens,
  decodeJwtPayload,
  getAccessToken,
  getRefreshToken,
  setPlatformRoleCookie,
  setTokenPair,
  type PlatformRoleCookie,
} from "@/lib/auth/tokens";
import type { CurrentUser } from "@/types/team";

function roleFromUser(user: Pick<CurrentUser, "is_superadmin" | "is_support">): PlatformRoleCookie {
  if (user.is_superadmin) return "SUPERADMIN";
  if (user.is_support) return "SUPPORT";
  return "USER";
}

function roleFromAccessToken(accessToken: string): PlatformRoleCookie {
  const payload = decodeJwtPayload(accessToken);
  if (payload?.is_superuser === true || payload?.is_superadmin === true) {
    return "SUPERADMIN";
  }
  if (payload?.is_support === true) {
    return "SUPPORT";
  }
  return "USER";
}

async function parseAxiosError(error: unknown): Promise<never> {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    const message =
      (typeof detail === "string" && detail) ||
      (typeof error.response?.data?.message === "string" && error.response.data.message) ||
      error.message ||
      "Request failed";
    throw new Error(message);
  }
  throw error instanceof Error ? error : new Error("Request failed");
}

export async function loginWithPassword(email: string, password: string): Promise<TokenPairResponse> {
  try {
    const { data } = await axios.post<TokenPairResponse>(
      buildApiUrl("/api/v1/auth/login/json"),
      { email, password },
      { headers: { "Content-Type": "application/json" } },
    );
    setTokenPair({
      accessToken: data.access_token,
      refreshToken: data.refresh_token,
      expiresIn: data.expires_in ?? 60 * 60,
      platformRole: roleFromAccessToken(data.access_token),
    });
    return data;
  } catch (error) {
    return parseAxiosError(error);
  }
}

export async function registerAccount(payload: {
  email: string;
  password: string;
  full_name?: string;
  company_name?: string;
}): Promise<void> {
  try {
    await axios.post(buildApiUrl("/api/v1/auth/register"), payload, {
      headers: { "Content-Type": "application/json" },
    });
    // Register may not return tokens — follow with login.
    await loginWithPassword(payload.email, payload.password);
  } catch (error) {
    return parseAxiosError(error);
  }
}

export async function requestPasswordReset(email: string): Promise<void> {
  try {
    await axios.post(
      buildApiUrl("/api/v1/auth/forgot-password"),
      { email },
      { headers: { "Content-Type": "application/json" } },
    );
  } catch (error) {
    return parseAxiosError(error);
  }
}

export async function resetPassword(token: string, newPassword: string): Promise<void> {
  try {
    await axios.post(
      buildApiUrl("/api/v1/auth/reset-password"),
      { token, new_password: newPassword },
      { headers: { "Content-Type": "application/json" } },
    );
  } catch (error) {
    return parseAxiosError(error);
  }
}

export function applyUserPlatformRole(user: CurrentUser): void {
  setPlatformRoleCookie(roleFromUser(user));
}

/**
 * Local sign-out + best-effort server revoke of the refresh token.
 */
export function signOutLocal(): void {
  const refresh = getRefreshToken();
  const access = getAccessToken();
  clearAuthTokens();

  if (!refresh && !access) return;

  void axios
    .post(
      buildApiUrl("/api/v1/auth/logout"),
      refresh ? { refresh_token: refresh } : {},
      {
        headers: {
          "Content-Type": "application/json",
          ...(access ? { Authorization: `Bearer ${access}` } : {}),
        },
      },
    )
    .catch(() => {
      // Client session is already cleared; ignore network/401 on logout.
    });
}
