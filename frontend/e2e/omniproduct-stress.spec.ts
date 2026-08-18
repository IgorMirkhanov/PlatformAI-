/**
 * Omni-product stress E2E: superadmin impersonation, WhatsApp QR socket stability,
 * and CRM Action canvas save/schema validation.
 *
 * APIs and WebSockets are route-mocked so the suite stays deterministic without a live DB.
 */

import { expect, test, type Page, type Route } from "@playwright/test";

const E2E_BOT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const ADMIN_TOKEN = "e2e-admin-access-token";
const IMP_TOKEN = "imp_e2e.impersonation.signature";
const CUSTOMER_EMAIL = "customer@example.com";

const ADMIN_USER = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "superadmin@mp.ai.test",
  full_name: "Platform Superadmin",
  company_name: "MP.AI Support",
  company_id: "11111111-1111-4111-8111-111111111111",
  role: "OWNER" as const,
  timezone: "Asia/Almaty",
  created_at: new Date().toISOString(),
  is_superadmin: true,
};

const CUSTOMER_USER = {
  id: "22222222-2222-4222-8222-222222222222",
  email: CUSTOMER_EMAIL,
  full_name: "Acme Owner",
  company_name: "Acme Logistics",
  company_id: "22222222-2222-4222-8222-222222222222",
  role: "OWNER" as const,
  timezone: "Asia/Almaty",
  created_at: new Date().toISOString(),
  is_superadmin: false,
};

async function fulfillJson(route: Route, status: number, body: unknown): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function injectSession(
  page: Page,
  user: typeof ADMIN_USER,
  token: string,
  botId: string | null = E2E_BOT_ID,
): Promise<void> {
  await page.addInitScript(
    ({ accessToken, currentUser, activeBotId }) => {
      window.localStorage.setItem("auth_token", accessToken);
      window.localStorage.setItem("access_token", accessToken);
      window.localStorage.setItem("mpai_e2e_bearer", `Bearer ${accessToken}`);

      const persisted = {
        state: {
          connection: activeBotId
            ? {
                botId: activeBotId,
                botName: "E2E Stress Agent",
                companyId: currentUser.company_id,
              }
            : null,
          activeBotId,
          activeCompanyId: currentUser.company_id,
          currentUser,
          avatarByBotId: {},
          agentProfiles: activeBotId
            ? {
                [activeBotId]: {
                  id: activeBotId,
                  name: "E2E Stress Agent",
                  user_id: currentUser.id,
                },
              }
            : {},
        },
        version: 0,
      };
      window.localStorage.setItem("ai-bot-platform-store", JSON.stringify(persisted));
    },
    { accessToken: token, currentUser: user, activeBotId: botId },
  );
}

async function installShellMocks(page: Page, meUser: typeof ADMIN_USER | typeof CUSTOMER_USER): Promise<void> {
  await page.route(/\/api\/v1\/team\/me(?:\?|$)/, async (route) => {
    if (route.request().method() === "GET") {
      await fulfillJson(route, 200, meUser);
      return;
    }
    await fulfillJson(route, 200, meUser);
  });

  await page.route(/\/api\/v1\/team\/organizations/, async (route) => {
    await fulfillJson(route, 200, {
      organizations: [
        {
          company_id: meUser.company_id,
          company_name: meUser.company_name,
          role: meUser.role,
          timezone: meUser.timezone,
        },
      ],
      active_company_id: meUser.company_id,
    });
  });

  await page.route(/\/api\/v1\/billing\//, async (route) => {
    await fulfillJson(route, 200, {
      balance: 1000,
      currency: "KZT",
      plan: null,
      subscription: null,
      notifications: [],
      total: 0,
    });
  });

  await page.route(/\/api\/v1\/dashboard\//, async (route) => {
    await fulfillJson(route, 200, { agents: [], total_agents: 0, logs: [], total: 0 });
  });
}

function mockAgentProfile(botId: string) {
  return {
    id: botId,
    user_id: ADMIN_USER.id,
    name: "E2E Stress Agent",
    platform_type: "TELEGRAM",
    is_active: true,
    default_chat_state: true,
    timezone: "Asia/Almaty",
    schedule_config: {},
    prompt_instructions: "",
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

// ---------------------------------------------------------------------------
// Superadmin Impersonation
// ---------------------------------------------------------------------------

test.describe("Superadmin impersonation flow", () => {
  test("login as superadmin → enter customer → amber banner → restore admin", async ({
    page,
  }) => {
    let activeMe: typeof ADMIN_USER | typeof CUSTOMER_USER = { ...ADMIN_USER };
    let impersonateCalled = false;
    let endCalled = false;

    await page.addInitScript(
      ({ accessToken, currentUser }) => {
        window.localStorage.setItem("auth_token", accessToken);
        window.localStorage.setItem("access_token", accessToken);
        window.localStorage.setItem(
          "ai-bot-platform-store",
          JSON.stringify({
            state: {
              connection: null,
              activeBotId: null,
              activeCompanyId: currentUser.company_id,
              currentUser,
              avatarByBotId: {},
              agentProfiles: {},
            },
            version: 0,
          }),
        );
      },
      { accessToken: ADMIN_TOKEN, currentUser: ADMIN_USER },
    );

    await page.route(/\/api\/v1\/team\/me(?:\?|$)/, async (route) => {
      await fulfillJson(route, 200, activeMe);
    });
    await page.route(/\/api\/v1\/team\/organizations/, async (route) => {
      await fulfillJson(route, 200, {
        organizations: [
          {
            company_id: activeMe.company_id,
            company_name: activeMe.company_name,
            role: activeMe.role,
            timezone: activeMe.timezone,
          },
        ],
        active_company_id: activeMe.company_id,
      });
    });
    await page.route(/\/api\/v1\/billing\//, async (route) => {
      await fulfillJson(route, 200, {
        balance: 0,
        currency: "KZT",
        notifications: [],
        total: 0,
      });
    });
    await page.route(/\/api\/v1\/dashboard\//, async (route) => {
      await fulfillJson(route, 200, { agents: [], total_agents: 0, logs: [], total: 0 });
    });

    await page.route(/\/api\/v1\/admin\/clients/, async (route) => {
      await fulfillJson(route, 200, {
        clients: [
          {
            id: CUSTOMER_USER.id,
            email: CUSTOMER_USER.email,
            full_name: CUSTOMER_USER.full_name,
            company_name: CUSTOMER_USER.company_name,
            company_id: CUSTOMER_USER.company_id,
            role: CUSTOMER_USER.role,
            is_superadmin: false,
            created_at: CUSTOMER_USER.created_at,
          },
        ],
        total: 1,
        query: "",
      });
    });

    await page.route(/\/api\/v1\/admin\/impersonate$/, async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      impersonateCalled = true;
      const payload = route.request().postDataJSON() as { email?: string };
      expect(payload.email?.toLowerCase()).toBe(CUSTOMER_EMAIL);
      activeMe = { ...CUSTOMER_USER };
      await fulfillJson(route, 200, {
        access_token: IMP_TOKEN,
        token_type: "Bearer",
        organization_id: CUSTOMER_USER.company_id,
        organization_name: CUSTOMER_USER.company_name,
        impersonated_user_id: CUSTOMER_USER.id,
        impersonated_user_email: CUSTOMER_USER.email,
        impersonated_user_name: CUSTOMER_USER.full_name,
        impersonated_user_role: CUSTOMER_USER.role,
        impersonated_by: ADMIN_USER.id,
        expires_at: new Date(Date.now() + 3_600_000).toISOString(),
        headers: { Authorization: `Bearer ${IMP_TOKEN}` },
        message: `Вошли под аккаунтом ${CUSTOMER_EMAIL}.`,
      });
    });

    await page.route(/\/api\/v1\/admin\/impersonate\/end/, async (route) => {
      endCalled = true;
      activeMe = { ...ADMIN_USER };
      await fulfillJson(route, 200, {
        success: true,
        message: "Impersonation ended and audit logged.",
      });
    });

    await page.goto("/dashboard/admin", { waitUntil: "domcontentloaded" });

    // Prefer the admin heading; fall back if the gate briefly shows while user hydrates.
    const adminHeading = page.getByRole("heading", { name: /Войти под пользователем/i });
    await expect(adminHeading).toBeVisible({ timeout: 30_000 });

    const search = page.getByPlaceholder(/Поиск по email/i);
    await search.fill(CUSTOMER_EMAIL);
    await expect(page.getByRole("cell", { name: CUSTOMER_EMAIL })).toBeVisible({
      timeout: 15_000,
    });

    await page.getByRole("button", { name: /Войти в аккаунт/i }).click();

    await page.waitForURL(/\/dashboard\/?$/, { timeout: 20_000 });
    expect(impersonateCalled).toBeTruthy();

    const banner = page.getByRole("status").filter({ hasText: /Вы работаете под аккаунтом/i });
    await expect(banner).toBeVisible({ timeout: 15_000 });
    await expect(banner).toContainText(CUSTOMER_EMAIL);

    const bannerClass = await banner.evaluate((el) => el.className);
    expect(bannerClass).toMatch(/#DC143C|amber-500/);

    const accessAfterImpersonate = await page.evaluate(() =>
      window.localStorage.getItem("access_token"),
    );
    expect(accessAfterImpersonate).toBe(IMP_TOKEN);

    const originalSnapshot = await page.evaluate(() =>
      window.localStorage.getItem("original_admin_token"),
    );
    expect(originalSnapshot).toBeTruthy();
    expect(originalSnapshot).toContain(ADMIN_USER.email);

    await page.getByRole("button", { name: /Вернуться в админку/i }).click();
    await page.waitForURL(/\/dashboard\/admin/, { timeout: 20_000 });
    expect(endCalled).toBeTruthy();

    const restoredToken = await page.evaluate(() => window.localStorage.getItem("access_token"));
    expect(restoredToken).toBe(ADMIN_TOKEN);

    const clearedMeta = await page.evaluate(() =>
      window.localStorage.getItem("impersonation_meta"),
    );
    expect(clearedMeta).toBeNull();

    await expect(adminHeading).toBeVisible({ timeout: 30_000 });
  });
});

// ---------------------------------------------------------------------------
// WhatsApp QR WebSocket stability
// ---------------------------------------------------------------------------

test.describe("WhatsApp QR socket stability", () => {
  test("single persistent socket while modal open; clean reopen cycle", async ({ page }) => {
    await injectSession(page, ADMIN_USER, ADMIN_TOKEN);
    await installShellMocks(page, ADMIN_USER);

    await page.route(new RegExp(`/api/v1/bots/${E2E_BOT_ID}/profile`), async (route) => {
      await fulfillJson(route, 200, mockAgentProfile(E2E_BOT_ID));
    });

    await page.route(new RegExp(`/api/v1/bots/${E2E_BOT_ID}/channels$`), async (route) => {
      await fulfillJson(route, 200, {
        success: true,
        bot_id: E2E_BOT_ID,
        channels: [
          {
            channel_type: "whatsapp_qr",
            status: "disconnected",
            connected: false,
            reference_id: null,
            meta_data: {},
            updated_at: null,
            webhook_url: null,
          },
        ],
      });
    });

    let openCount = 0;
    let closeCount = 0;

    await page.routeWebSocket(/whatsapp\/ws-qr/, (ws) => {
      openCount += 1;
      ws.onClose(() => {
        closeCount += 1;
      });
      ws.onMessage((message) => {
        const raw = typeof message === "string" ? message : String(message);
        try {
          const parsed = JSON.parse(raw) as { type?: string };
          if (parsed.type === "ping") {
            ws.send(JSON.stringify({ type: "pong", ts: Date.now() }));
          }
        } catch {
          // ignore
        }
      });

      ws.send(
        JSON.stringify({
          event: "qr_code_ready",
          qr_base64:
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
          message: "Отсканируйте QR-код",
        }),
      );
    });

    await page.goto(`/dashboard/channels-agent/${E2E_BOT_ID}/whatsapp-qr`, {
      waitUntil: "domcontentloaded",
    });

    await expect(page.getByRole("heading", { name: /WhatsApp QR/i }).first()).toBeVisible({
      timeout: 30_000,
    });

    await page.getByRole("button", { name: /Подключить через QR/i }).click();

    const modalTitle = page.getByRole("heading", { name: /Подключение WhatsApp по QR/i });
    await expect(modalTitle).toBeVisible();

    const modalShell = page.locator("div.fixed.inset-0").filter({ has: modalTitle });
    await expect(modalShell).toBeVisible();
    await expect(modalShell).toHaveClass(/items-center/);
    await expect(modalShell).toHaveClass(/justify-center/);

    await expect(page.getByAltText("WhatsApp QR")).toBeVisible({ timeout: 10_000 });
    expect(openCount).toBe(1);

    await page.waitForTimeout(800);
    expect(openCount).toBe(1);
    expect(closeCount).toBe(0);

    // Header X is actionable; full-screen backdrop is obscured by the dialog panel.
    await page.getByRole("button", { name: "Закрыть модальное окно" }).click();
    await expect(modalTitle).toHaveCount(0);
    await expect.poll(() => closeCount, { timeout: 5_000 }).toBe(1);

    await page.getByRole("button", { name: /Подключить через QR/i }).click();
    await expect(modalTitle).toBeVisible();
    await expect.poll(() => openCount, { timeout: 5_000 }).toBe(2);
    await expect(page.getByAltText("WhatsApp QR")).toBeVisible();

    await page.waitForTimeout(600);
    expect(openCount).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// CRM Action canvas — schema validation on Save Flow
// ---------------------------------------------------------------------------

test.describe("CRM interactive node canvas", () => {
  test("add crm_action node, configure amoCRM POST body, Save Flow schema", async ({
    page,
  }) => {
    await injectSession(page, ADMIN_USER, ADMIN_TOKEN);
    await installShellMocks(page, ADMIN_USER);

    let savedPayload: {
      title?: string;
      nodes?: Array<{ type?: string; data?: Record<string, unknown> }>;
      edges?: unknown[];
      graph_data?: {
        nodes?: Array<{ type?: string; data?: Record<string, unknown> }>;
      };
      is_published?: boolean;
    } | null = null;

    await page.route(new RegExp(`/api/v1/bots/${E2E_BOT_ID}/flow`), async (route) => {
      const method = route.request().method();
      if (method === "GET") {
        await fulfillJson(route, 200, {
          bot_id: E2E_BOT_ID,
          flow_id: null,
          title: "E2E Stress Flow",
          graph_data: {
            nodes: [
              {
                id: "trigger_seed",
                type: "trigger",
                position: { x: 80, y: 120 },
                data: { trigger_type: "message_received", webhook_event: "" },
              },
            ],
            edges: [],
          },
          is_published: false,
          is_default_template: true,
          updated_at: null,
        });
        return;
      }
      if (method === "POST" || method === "PUT" || method === "PATCH") {
        savedPayload = route.request().postDataJSON() as typeof savedPayload;
        await fulfillJson(route, 200, {
          bot_id: E2E_BOT_ID,
          flow_id: "flow-e2e-1",
          title: savedPayload?.title ?? "E2E Stress Flow",
          graph_data: {
            nodes: savedPayload?.nodes ?? [],
            edges: savedPayload?.edges ?? [],
          },
          is_published: Boolean(savedPayload?.is_published),
          message: "Flow saved.",
          updated_at: new Date().toISOString(),
        });
        return;
      }
      await route.continue();
    });

    await page.route(new RegExp(`/api/v1/bots/${E2E_BOT_ID}/profile`), async (route) => {
      await fulfillJson(route, 200, mockAgentProfile(E2E_BOT_ID));
    });

    await page.setViewportSize({ width: 1440, height: 900 });

    const flowLoaded = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/v1/bots/${E2E_BOT_ID}/flow`) &&
        response.request().method() === "GET" &&
        response.ok(),
      { timeout: 30_000 },
    );

    await page.goto(`/dashboard/flow-builder/${E2E_BOT_ID}`, {
      waitUntil: "domcontentloaded",
    });
    await flowLoaded;

    await expect(page.getByText("Node Palette")).toBeVisible({ timeout: 30_000 });
    // Wait until the seeded Trigger is on the canvas and load has finished setGraph.
    await expect(
      page.locator(".react-flow__node").filter({ hasText: /Trigger/i }).first(),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/1 node/i)).toBeVisible();

    const palette = page.locator("aside").filter({ hasText: "Node Palette" });
    const paletteCrm = palette.getByRole("button", { name: /CRM Action/i });
    await paletteCrm.scrollIntoViewIfNeeded();
    await expect(paletteCrm).toBeVisible();
    await paletteCrm.click();

    // Canvas should grow from the seeded Trigger to Trigger + CRM Action.
    await expect
      .poll(async () => page.locator(".react-flow__node").count(), {
        timeout: 10_000,
      })
      .toBeGreaterThanOrEqual(2);

    const crmNode = page
      .locator(".react-flow__node")
      .filter({ hasText: /CRM Action|External API/i })
      .last();
    await expect(crmNode).toBeVisible({ timeout: 10_000 });
    await crmNode.scrollIntoViewIfNeeded();
    await crmNode.click({ force: true });

    const integrationSelect = crmNode.getByLabel("Integration type");
    await expect(integrationSelect).toBeVisible({ timeout: 10_000 });
    await integrationSelect.selectOption("amocrm");
    await crmNode.getByLabel("HTTP method").selectOption("POST");

    await crmNode
      .getByPlaceholder(/amocrm\.ru|example\.amocrm/i)
      .fill("https://example.amocrm.ru/api/v4/leads");

    await crmNode.getByLabel("JSON body template").fill(
      '{\n  "phone": "{{phone}}",\n  "lead_name": "Lead from WhatsApp",\n  "source": "{{channel}}"\n}',
    );

    await crmNode.getByPlaceholder("crm_result").fill("crm_result");

    await page.getByRole("button", { name: /^Save Flow$/i }).click();

    await expect.poll(() => savedPayload !== null, { timeout: 15_000 }).toBeTruthy();

    const nodes = savedPayload?.nodes ?? savedPayload?.graph_data?.nodes ?? [];
    const crmSaved = nodes.find((node) => node.type === "crm_action");
    expect(crmSaved, "Saved graph must include crm_action node").toBeTruthy();

    const data = crmSaved?.data ?? {};
    expect(data.integration_type === "amocrm" || data.action_type === "amocrm").toBeTruthy();
    expect(data.method).toBe("POST");
    expect(String(data.url)).toContain("amocrm.ru/api/v4/leads");
    expect(String(data.body_template)).toContain("{{phone}}");
    expect(String(data.body_template)).toContain("Lead from WhatsApp");
    expect(String(data.body_template)).toContain("{{channel}}");
    expect(data.response_variable).toBe("crm_result");
    expect(typeof data.headers === "object" && data.headers !== null).toBeTruthy();
  });
});
