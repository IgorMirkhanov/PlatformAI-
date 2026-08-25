import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import type { Page } from "@playwright/test";

export const E2E_BOT_ID = "11111111-1111-1111-1111-111111111111";
export const E2E_ORG_ID = "22222222-2222-2222-2222-222222222222";
export const E2E_USER_ID = "33333333-3333-3333-3333-333333333333";

/** Relative to the frontend package root (playwright.config.ts cwd). */
export const AUTH_STORAGE_STATE_PATH = "playwright/.auth/user.json";

export function buildE2EAccessJwt(claims: Record<string, unknown> = {}): string {
  const encode = (value: object) => Buffer.from(JSON.stringify(value)).toString("base64url");
  const now = Math.floor(Date.now() / 1000);
  const payload = {
    exp: now + 60 * 60,
    iat: now,
    role: "OWNER",
    sub: E2E_USER_ID,
    company_id: E2E_ORG_ID,
    is_superadmin: false,
    ...claims,
  };
  return `${encode({ alg: "none", typ: "JWT" })}.${encode(payload)}.e2e`;
}

export const CURRENT_USER = {
  id: E2E_USER_ID,
  email: "owner@example.com",
  full_name: "E2E Owner",
  role: "OWNER",
  company_id: E2E_ORG_ID,
  company_name: "E2E Org",
  is_superadmin: false,
  is_active: true,
  is_verified: true,
  timezone: "Asia/Almaty",
};

export interface SeedSessionOptions {
  botId?: string;
  user?: Partial<typeof CURRENT_USER> & { id?: string; email?: string };
  origin?: string;
}

function persistStorePayload(botId: string, user: typeof CURRENT_USER, botName: string) {
  return {
    state: {
      connection: { botId, botName },
      activeBotId: botId,
      activeCompanyId: user.company_id,
      currentUser: user,
      avatarByBotId: {},
      agentProfiles: {
        [botId]: { id: botId, name: botName, company_id: user.company_id },
      },
    },
    version: 0,
  };
}

function cookieRecord(name: string, value: string, domain: string, expires: number) {
  return {
    name,
    value,
    domain,
    path: "/",
    expires,
    httpOnly: false,
    secure: false,
    sameSite: "Lax" as const,
  };
}

/** Playwright `storageState` JSON: JWT cookie with `exp` + persist store. */
export function buildE2EAuthStorageState(
  origin = "http://127.0.0.1:3000",
  options?: SeedSessionOptions,
) {
  const token = buildE2EAccessJwt({
    sub: options?.user?.id ?? E2E_USER_ID,
    company_id: options?.user?.company_id ?? E2E_ORG_ID,
    is_superadmin: options?.user?.is_superadmin ?? false,
  });
  const user = { ...CURRENT_USER, ...options?.user };
  const botId = options?.botId ?? E2E_BOT_ID;
  const expires = Math.floor(Date.now() / 1000) + 60 * 60;
  const host = new URL(origin).hostname;
  const domains = Array.from(new Set([host, "127.0.0.1", "localhost"]));
  const cookies = domains.flatMap((domain) => [
    cookieRecord("mpai_access_token", token, domain, expires),
    cookieRecord("mpai_platform_role", user.is_superadmin ? "SUPERADMIN" : "USER", domain, expires),
  ]);

  return {
    cookies,
    origins: [
      {
        origin,
        localStorage: [
          { name: "mpai_access_token", value: token },
          { name: "auth_token", value: token },
          { name: "access_token", value: token },
          {
            name: "ai-bot-platform-store",
            value: JSON.stringify(persistStorePayload(botId, user, "E2E Bot")),
          },
        ],
      },
    ],
  };
}

export function writeE2EAuthStorageState(
  filePath = AUTH_STORAGE_STATE_PATH,
  origin = "http://127.0.0.1:3000",
): string {
  const absolute = path.isAbsolute(filePath) ? filePath : path.join(process.cwd(), filePath);
  mkdirSync(path.dirname(absolute), { recursive: true });
  writeFileSync(absolute, `${JSON.stringify(buildE2EAuthStorageState(origin), null, 2)}\n`);
  return absolute;
}

/**
 * Middleware requires a JWT cookie with `exp`. Persist store key is
 * `ai-bot-platform-store` (not `mpai-bot-store`).
 */
export async function seedDashboardSession(
  page: Page,
  options?: SeedSessionOptions,
): Promise<void> {
  const origin = options?.origin ?? "http://127.0.0.1:3000";
  const botId = options?.botId ?? E2E_BOT_ID;
  const user = { ...CURRENT_USER, ...options?.user };
  const token = buildE2EAccessJwt({
    sub: user.id,
    company_id: user.company_id,
    is_superadmin: user.is_superadmin,
  });
  const role = user.is_superadmin ? "SUPERADMIN" : "USER";

  await page.context().addCookies([
    { name: "mpai_access_token", value: token, url: origin },
    { name: "mpai_access_token", value: token, url: "http://localhost:3000" },
    { name: "mpai_platform_role", value: role, url: origin },
    { name: "mpai_platform_role", value: role, url: "http://localhost:3000" },
  ]);
  await page.addInitScript(
    ({ token: accessToken, user: sessionUser, botId: sessionBotId, store }) => {
      localStorage.setItem("mpai_access_token", accessToken);
      localStorage.setItem("auth_token", accessToken);
      localStorage.setItem("access_token", accessToken);
      localStorage.setItem("ai-bot-platform-store", store);
      document.cookie = `mpai_access_token=${encodeURIComponent(accessToken)}; Path=/; SameSite=Lax`;
      document.cookie = `mpai_platform_role=${encodeURIComponent(sessionUser.is_superadmin ? "SUPERADMIN" : "USER")}; Path=/; SameSite=Lax`;
    },
    {
      token,
      user,
      botId,
      store: JSON.stringify(persistStorePayload(botId, user, "E2E Hub Agent")),
    },
  );
}

export function ownerMePayload() {
  return {
    ...CURRENT_USER,
    created_at: new Date().toISOString(),
  };
}
