import { expect, test, type Page, type Route } from "@playwright/test";

import { AUTH_STORAGE_STATE_PATH, seedDashboardSession } from "./helpers/session";

/** Deterministic bot id — all hub APIs are route-mocked; no live DB required. */
const E2E_BOT_ID = "11111111-2222-4333-8444-555555555555";
const E2E_COMPANY_ID = "e2e-company-id";

const TIMEOUT_ERROR_BODY = {
  success: false,
  error: "Connection timed out. Please check your token.",
} as const;

const HUB_CHANNEL_TYPES = [
  "telegram",
  "telegram_business",
  "instagram",
  "wazzup",
  "waba",
  "whatsapp_qr",
] as const;

const HUB_USER = {
  id: "e2e-user-id",
  email: "e2e-hub@example.com",
  full_name: "E2E Hub Operator",
  company_name: "E2E Workspace",
  company_id: E2E_COMPANY_ID,
  role: "OWNER" as const,
  timezone: "Asia/Almaty",
  is_superadmin: true,
  is_active: true,
  is_verified: true,
};

function disconnectedChannels(botId: string) {
  return {
    success: true,
    bot_id: botId,
    channels: HUB_CHANNEL_TYPES.map((channel_type) => ({
      channel_type,
      status: "disconnected",
      connected: false,
      reference_id: null,
      meta_data: {},
      updated_at: null,
      webhook_url: null,
    })),
  };
}

function mockAgentProfile(botId: string) {
  return {
    id: botId,
    user_id: HUB_USER.id,
    name: "E2E Hub Agent",
    platform_type: "TELEGRAM",
    is_active: true,
    default_chat_state: true,
    timezone: "Asia/Almaty",
    schedule_config: {},
    prompt_instructions: "E2E prompt",
    llm_model_name: "gpt-4o-mini",
    llm_temperature: 0.2,
    message_split: false,
    message_buffer_delay: 0,
    custom_code_snippet: "",
    show_username_visibility: true,
    show_messenger_visibility: true,
    show_datetime_visibility: true,
    avatar_url: null,
  };
}

async function fulfillJson(route: Route, status: number, body: unknown): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

/**
 * Stub shell + hub APIs so validation UI can be exercised without a live backend.
 * Returns a mutable flag set when a Telegram connect POST is attempted.
 */
async function installHubMocks(page: Page): Promise<{ telegramConnectAttempted: { value: boolean } }> {
  const telegramConnectAttempted = { value: false };

  await page.route("**/api/v1/**", async (route) => {
    if (route.request().method() === "GET") {
      await fulfillJson(route, 200, {});
      return;
    }
    await route.continue();
  });

  await page.route("**/api/v1/team/me", async (route) => {
    if (route.request().method() === "GET") {
      await fulfillJson(route, 200, {
        ...HUB_USER,
        created_at: new Date().toISOString(),
      });
      return;
    }
    await route.continue();
  });

  await page.route("**/api/v1/auth/me", async (route) => {
    await fulfillJson(route, 200, { ...HUB_USER, created_at: new Date().toISOString() });
  });

  await page.route("**/api/v1/team/organizations**", async (route) => {
    await fulfillJson(route, 200, {
      organizations: [{ id: E2E_COMPANY_ID, name: "E2E Workspace", is_active: true }],
      active_company_id: E2E_COMPANY_ID,
    });
  });

  await page.route("**/api/v1/billing/status**", async (route) => {
    await fulfillJson(route, 200, {
      balance: 0,
      currency: "KZT",
      plan: null,
      subscription: null,
    });
  });

  await page.route("**/api/v1/billing/notifications**", async (route) => {
    await fulfillJson(route, 200, { notifications: [], total: 0, unread_critical: 0 });
  });

  await page.route("**/api/v1/dashboard/stats**", async (route) => {
    await fulfillJson(route, 200, { agents: [], total_agents: 0 });
  });

  await page.route("**/api/v1/wallet**", async (route) => {
    await fulfillJson(route, 200, {
      organization_id: E2E_COMPANY_ID,
      balance_tokens: 10_000,
      status: "active",
      transactions: [],
    });
  });

  await page.route(`**/api/v1/bots/${E2E_BOT_ID}/profile`, async (route) => {
    await fulfillJson(route, 200, mockAgentProfile(E2E_BOT_ID));
  });

  await page.route(`**/api/v1/bots/${E2E_BOT_ID}/channels`, async (route) => {
    if (route.request().method() === "GET") {
      await fulfillJson(route, 200, disconnectedChannels(E2E_BOT_ID));
      return;
    }
    await route.continue();
  });

  await page.route(`**/api/v1/bots/${E2E_BOT_ID}/channel-integrations`, async (route) => {
    await fulfillJson(route, 200, { bot_id: E2E_BOT_ID, channels: [] });
  });

  await page.route(`**/api/v1/bots/${E2E_BOT_ID}/channels/telegram/connect`, async (route) => {
    telegramConnectAttempted.value = true;
    await fulfillJson(route, 200, {
      success: true,
      bot_id: E2E_BOT_ID,
      channel_type: "telegram",
      status: "connected",
      connected: true,
      reference_id: "@mock",
      webhook_url: null,
      message: "should not be called",
    });
  });

  return { telegramConnectAttempted };
}

async function openHubPanel(page: Page, slug: string): Promise<void> {
  await page.goto(`/dashboard/channels-agent/${E2E_BOT_ID}/${slug}`, {
    waitUntil: "domcontentloaded",
  });
  await expect(page).not.toHaveURL(/\/login/);
  await expect(
    page.getByRole("heading", { name: /E2E Hub Agent|Telegram|WABA/i }).first(),
  ).toBeVisible({
    timeout: 30_000,
  });
}

async function openChannelsGrid(page: Page): Promise<void> {
  await page.goto(`/dashboard/channels?botId=${E2E_BOT_ID}`, { waitUntil: "domcontentloaded" });
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByRole("heading", { name: "Каналы связи" })).toBeVisible({
    timeout: 30_000,
  });
}

function channelCard(page: Page, label: string) {
  return page.locator("article").filter({ has: page.getByRole("heading", { name: label }) });
}

async function trackConnectAndPatch(page: Page, channelType: string) {
  const hits = { connect: 0, patch: 0 };
  await page.route(
    `**/api/v1/bots/${E2E_BOT_ID}/channels/${channelType}/connect`,
    async (route) => {
      hits.connect += 1;
      await fulfillJson(route, 400, { detail: "should not be called" });
    },
  );
  await page.route(`**/api/v1/bots/${E2E_BOT_ID}/channels/${channelType}`, async (route) => {
    if (route.request().method() === "PATCH") {
      hits.patch += 1;
      await fulfillJson(route, 400, {
        detail: "Channel must be connected before toggling enabled state.",
      });
      return;
    }
    await route.continue();
  });
  return hits;
}

function crimsonBanner(page: Page, message: string | RegExp) {
  return page.getByRole("alert").filter({ hasText: message });
}

async function expectCrimsonBanner(page: Page, message: string | RegExp): Promise<void> {
  const banner = crimsonBanner(page, message);
  await expect(banner).toBeVisible();
  await expect(banner).toContainText(message);

  const styles = await banner.evaluate((el) => {
    const computed = window.getComputedStyle(el);
    return {
      className: el.className,
      borderBottomColor: computed.borderBottomColor,
      backgroundColor: computed.backgroundColor,
      color: computed.color,
    };
  });

  expect(styles.className).toMatch(/#DC143C/);
  expect(styles.borderBottomColor).toMatch(/220,\s*20,\s*60/);
}

function inspectHubScrollLayout(): {
  active: Array<{ tag: string; className: string }>;
  nestedPairs: number;
  hubFitsViewport: boolean;
} {
  const isInViewportLayout = (el: HTMLElement): boolean => {
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
      return false;
    }
    for (let parent: HTMLElement | null = el; parent; parent = parent.parentElement) {
      const parentStyle = window.getComputedStyle(parent);
      if (parentStyle.display === "none" || parentStyle.visibility === "hidden") {
        return false;
      }
    }
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) return false;
    if (rect.right <= 0 || rect.left >= window.innerWidth) return false;
    if (rect.bottom <= 0 || rect.top >= window.innerHeight) return false;
    return true;
  };

  const nodes = Array.from(document.querySelectorAll("body *")) as HTMLElement[];
  const scrollers: HTMLElement[] = [];
  const active: Array<{ tag: string; className: string }> = [];

  for (const el of nodes) {
    if (!isInViewportLayout(el)) continue;
    const style = window.getComputedStyle(el);
    const overflowY = style.overflowY;
    if (overflowY !== "auto" && overflowY !== "scroll") continue;
    if (style.overflowX === "auto" || style.overflowX === "scroll") {
      if (el.scrollWidth > el.clientWidth + 2 && el.scrollHeight <= el.clientHeight + 2) {
        continue;
      }
    }
    if (el.scrollHeight > el.clientHeight + 2) {
      scrollers.push(el);
      active.push({ tag: el.tagName.toLowerCase(), className: el.className.toString() });
    }
  }

  let nestedPairs = 0;
  for (const outer of scrollers) {
    for (const inner of scrollers) {
      if (outer !== inner && outer.contains(inner)) nestedPairs += 1;
    }
  }

  const hub = document.querySelector(".bg-zinc-950.text-zinc-100") as HTMLElement | null;
  const hubFitsViewport = hub
    ? hub.getBoundingClientRect().height <= window.innerHeight + 2
    : false;

  return { active, nestedPairs, hubFitsViewport };
}

test.describe("Omnichannel Hub validation & layout", () => {
  test.use({ storageState: AUTH_STORAGE_STATE_PATH });

  test.beforeEach(async ({ page }) => {
    await seedDashboardSession(page, {
      botId: E2E_BOT_ID,
      user: HUB_USER,
    });
  });

  test("Empty Telegram token: blocks request, no pending, crimson banner", async ({ page }) => {
    const { telegramConnectAttempted } = await installHubMocks(page);

    await openHubPanel(page, "telegram");

    const tokenInput = page.getByPlaceholder("123456789:AAH…");
    await expect(tokenInput).toBeVisible();
    await tokenInput.fill("");

    const connectButton = page.getByRole("button", { name: /^Подключить$/ });
    await expect(connectButton).toBeVisible();
    await expect(connectButton).toBeEnabled();

    await connectButton.click();

    await expect.poll(() => telegramConnectAttempted.value).toBe(false);

    await expect(connectButton).toHaveAttribute("aria-busy", "false");
    await expect(connectButton).toContainText("Подключить");
    await expect(connectButton).not.toContainText("Сохранение");
    await expect(page.locator("svg.animate-spin")).toHaveCount(0);

    await expectCrimsonBanner(page, /Укажите токен бота|Неверный формат токена/i);
  });

  test("WABA connect: surfaces structured 504 timeout in crimson banner", async ({ page }) => {
    await installHubMocks(page);

    let connectHits = 0;
    await page.route(`**/api/v1/bots/${E2E_BOT_ID}/channels/waba/connect`, async (route) => {
      connectHits += 1;
      await fulfillJson(route, 504, TIMEOUT_ERROR_BODY);
    });

    await openHubPanel(page, "waba");

    await page.getByRole("textbox", { name: "Phone Number ID" }).fill("123456789012345");
    await page.getByRole("textbox", { name: "Business Account ID" }).fill("987654321098765");
    await page.getByLabel("Access Token").fill("mock-invalid-waba-token-xxxxxxxx");

    const connectButton = page.getByRole("button", { name: /^Подключить$/ });
    await connectButton.click();

    await expect.poll(() => connectHits).toBe(1);

    await expect(connectButton).toContainText("Подключить", { timeout: 15_000 });
    await expect(connectButton).toBeEnabled();
    await expect(connectButton).toHaveAttribute("aria-busy", "false");

    await expectCrimsonBanner(page, TIMEOUT_ERROR_BODY.error);

    await expect(page.getByRole("heading", { name: "WABA" })).toBeVisible();
    await expect(page.getByText("Официальный WhatsApp Business API")).toBeVisible();
  });

  test("Tablet width: only one master vertical scroll container (no double nesting)", async ({
    page,
  }) => {
    await installHubMocks(page);

    await page.setViewportSize({ width: 768, height: 700 });
    await openHubPanel(page, "telegram");

    await page.evaluate(() => {
      const section = document.querySelector("section.min-h-0");
      if (!section) return;
      const spacer = document.createElement("div");
      spacer.setAttribute("data-e2e-scroll-spacer", "true");
      spacer.style.height = "1600px";
      spacer.style.width = "100%";
      spacer.style.flexShrink = "0";
      section.appendChild(spacer);
    });

    await expect
      .poll(async () => (await page.evaluate(inspectHubScrollLayout)).active.length)
      .toBeGreaterThan(0);

    const layout = await page.evaluate(inspectHubScrollLayout);
    expect(
      layout.active,
      `Expected a single master vertical scroller, found ${JSON.stringify(layout.active)}`,
    ).toHaveLength(1);
    expect(layout.nestedPairs, "Nested active overflow-y scrollers indicate double-nesting").toBe(
      0,
    );
    expect(layout.hubFitsViewport).toBe(true);
  });

  test("Empty Wazzup credentials: blocks connect POST", async ({ page }) => {
    await installHubMocks(page);

    let connectHits = 0;
    await page.route(`**/api/v1/bots/${E2E_BOT_ID}/channels/wazzup/connect`, async (route) => {
      connectHits += 1;
      await fulfillJson(route, 200, {
        success: true,
        bot_id: E2E_BOT_ID,
        channel_type: "wazzup",
        status: "connected",
        connected: true,
        reference_id: null,
        webhook_url: null,
        message: "should not be called",
      });
    });

    await openHubPanel(page, "wazzup");
    await page.getByRole("button", { name: /^Подключить$/ }).click();

    await expect.poll(() => connectHits).toBe(0);
    await expectCrimsonBanner(page, /API-ключ|Channel ID/i);
  });

  for (const channel of [
    { label: "Wazzup", type: "wazzup", field: "Channel ID" },
    { label: "Instagram", type: "instagram", field: "Instance ID" },
    { label: "WhatsApp", type: "whatsapp_qr", field: "Instance ID" },
  ] as const) {
    test(`Channels grid: ${channel.label} Connect opens keys modal without PATCH`, async ({
      page,
    }) => {
      await installHubMocks(page);
      const hits = await trackConnectAndPatch(page, channel.type);

      await openChannelsGrid(page);

      const card = channelCard(page, channel.label);
      await card.getByRole("button", { name: "Подключить" }).click();

      const modal = page.locator(".moonai-modal");
      await expect(modal.getByRole("heading", { name: channel.label })).toBeVisible();
      await expect(modal.getByRole("textbox", { name: channel.field })).toBeVisible();

      await modal.getByRole("button", { name: "Сохранить и подключить" }).click();

      await expect.poll(() => hits.connect).toBe(0);
      await expect.poll(() => hits.patch).toBe(0);
      await expect(modal.getByRole("alert")).toBeVisible();
    });
  }

  test("Channels grid: toggle on disconnected channel opens modal, no PATCH", async ({ page }) => {
    await installHubMocks(page);
    const hits = await trackConnectAndPatch(page, "wazzup");

    await openChannelsGrid(page);

    const card = channelCard(page, "Wazzup");
    await card.getByRole("switch").click();

    const modal = page.locator(".moonai-modal");
    await expect(modal.getByRole("heading", { name: "Wazzup" })).toBeVisible();
    await expect.poll(() => hits.patch).toBe(0);
    await expect.poll(() => hits.connect).toBe(0);
  });
});
