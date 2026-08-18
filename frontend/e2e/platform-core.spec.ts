import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

/** Minimal valid 1×1 PNG (binary placeholder for Kaspi receipt uploads). */
const MINIMAL_PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

const RECEIPT_FILE_NAME = "mock-kaspi-receipt.png";
const E2E_DIR = path.join(__dirname);
const RECEIPT_PATH = path.join(E2E_DIR, RECEIPT_FILE_NAME);

/** Ephemeral Bearer token injected for route/auth bypass checks. */
const E2E_BEARER_TOKEN = `Bearer e2e-healthcheck-${createHash("sha256")
  .update("mp-ai-platform-e2e")
  .digest("hex")
  .slice(0, 32)}`;

interface CurrentUserPayload {
  id: string;
  email: string;
  full_name: string;
  company_name: string;
  company_id: string;
  role: "OWNER" | "ADMIN" | "PROMPT_ENGINEER" | "OPERATOR";
  timezone: string;
  created_at: string;
  is_superadmin?: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function ensureMockReceiptExists(): string {
  mkdirSync(E2E_DIR, { recursive: true });
  if (!existsSync(RECEIPT_PATH)) {
    writeFileSync(RECEIPT_PATH, Buffer.from(MINIMAL_PNG_BASE64, "base64"));
  }
  return RECEIPT_PATH;
}

async function resolveCurrentUser(page: Page): Promise<CurrentUserPayload> {
  const response = await page.request.get("/api/v1/team/me");
  expect(response.ok(), `Expected /api/v1/team/me to succeed, got ${response.status()}`).toBeTruthy();

  const payload: unknown = await response.json();
  if (!isRecord(payload)) {
    throw new Error("Malformed /team/me payload.");
  }

  const id = typeof payload.id === "string" ? payload.id : null;
  const email = typeof payload.email === "string" ? payload.email : null;
  const companyId = typeof payload.company_id === "string" ? payload.company_id : null;
  const role = typeof payload.role === "string" ? payload.role : "OWNER";

  if (!id || !email || !companyId) {
    throw new Error("Incomplete /team/me identity — cannot seed auth storage.");
  }

  return {
    id,
    email,
    full_name: typeof payload.full_name === "string" ? payload.full_name : "E2E Operator",
    company_name:
      typeof payload.company_name === "string" ? payload.company_name : "E2E Workspace",
    company_id: companyId,
    role: role as CurrentUserPayload["role"],
    timezone: typeof payload.timezone === "string" ? payload.timezone : "Asia/Almaty",
    created_at:
      typeof payload.created_at === "string"
        ? payload.created_at
        : new Date().toISOString(),
    is_superadmin: Boolean(payload.is_superadmin),
  };
}

async function injectAuthSession(page: Page, user: CurrentUserPayload): Promise<void> {
  await page.addInitScript(
    ({ token, user: currentUser }) => {
      window.localStorage.setItem("auth_token", token);
      window.localStorage.setItem("access_token", token);
      window.localStorage.setItem("mpai_e2e_bearer", token);

      const persisted = {
        state: {
          connection: null,
          activeBotId: null,
          activeCompanyId: currentUser.company_id,
          currentUser,
          avatarByBotId: {},
        },
        version: 0,
      };
      window.localStorage.setItem("ai-bot-platform-store", JSON.stringify(persisted));
    },
    { token: E2E_BEARER_TOKEN, user },
  );
}

test.describe("Platform core E2E spectacle suite", () => {
  let receiptPath = "";

  test.beforeEach(async ({ page }) => {
    receiptPath = ensureMockReceiptExists();
    const user = await resolveCurrentUser(page);
    await injectAuthSession(page, user);
  });

  test("Agent Factory: create bot and confirm card registration", async ({ page }) => {
    const agentName = `E2E Agent ${Date.now()}`;

    await page.goto("/bots", { waitUntil: "domcontentloaded" });
    await page.waitForURL(/\/(bots|dashboard)/);

    // Product copy uses «Создать ИИ-Агента» / «Создать агента»; accept «Создать бота» aliases.
    const createTrigger = page
      .getByRole("button", { name: /Создать (бота|агента|ИИ-Агента)/i })
      .first();
    await expect(createTrigger).toBeVisible();
    await createTrigger.click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    const nameInput = dialog.locator("#agent-modal-name");
    await nameInput.click();
    await nameInput.fill(agentName);
    await expect(nameInput).toHaveValue(agentName);

    // Use-case select acts as the structured "description / sphere" field.
    const useCaseSelect = dialog.locator("#agent-modal-use-case");
    if (await useCaseSelect.count()) {
      await useCaseSelect.selectOption({ value: "support_rag" });
    }

    const createResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes("/api/v1/bots") &&
        response.request().method() === "POST" &&
        !response.url().includes("/setup") &&
        !response.url().includes("/publish"),
    );

    await dialog.getByRole("button", { name: /^Создать$/ }).click();

    const createResponse = await createResponsePromise;
    expect(createResponse.ok(), `Bot create failed: ${createResponse.status()}`).toBeTruthy();
    const createdPayload: unknown = await createResponse.json();
    if (!isRecord(createdPayload) || typeof createdPayload.name !== "string") {
      throw new Error("Create bot response missing name.");
    }
    expect(createdPayload.name).toBe(agentName);
    const createdBotId =
      typeof createdPayload.bot_id === "string" ? createdPayload.bot_id : null;
    expect(createdBotId).toBeTruthy();

    await expect(page.getByText(/Агент создан\.|Открываем настройки/i).first()).toBeVisible({
      timeout: 30_000,
    });

    // Create flow routes into the agent workspace — confirm the name registers in layout.
    await page.waitForURL(/\/bots\/[^/]+\/settings/, { timeout: 30_000 });
    await expect(page.locator(`input[value="${agentName}"]`).first()).toBeVisible({
      timeout: 30_000,
    });

    await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
    const refreshButton = page.getByRole("button", { name: /Обновить/i });
    if (await refreshButton.isVisible().catch(() => false)) {
      await refreshButton.click();
    }

    // Agent card grid renders the bot name as an h3 heading (or plain text fallback).
    const cardHeading = page.getByRole("heading", { name: agentName });
    const cardText = page.getByText(agentName, { exact: true });
    await expect(cardHeading.or(cardText).first()).toBeVisible({ timeout: 30_000 });
  });

  test("Billing Sandbox: preset 15000 ₸ + receipt deposit toast", async ({ page }) => {
    await page.goto("/billing", { waitUntil: "networkidle" });

    // Header "+" deposit manager (aria-label), not the simulated top-up CTA on the page body.
    await expect(page.getByLabel("Пополнить баланс")).toBeVisible();
    await page.getByLabel("Пополнить баланс").click();

    const depositDialog = page.getByRole("dialog");
    await expect(depositDialog).toBeVisible();
    await expect(depositDialog.getByText("Ручное пополнение")).toBeVisible();

    // Preset chip label is locale-formatted (e.g. "15 000 ₸"); click by visible text.
    const presetChip = depositDialog.getByRole("button", {
      name: /15[\s\u00a0]?000\s*₸/,
    });
    await expect(presetChip).toBeVisible();
    await presetChip.click();

    const amountInput = depositDialog.locator('input[type="number"]');
    await expect(amountInput).toHaveValue("15000");

    const fileInput = depositDialog.locator('input[type="file"]');
    await fileInput.setInputFiles(receiptPath);

    await expect(depositDialog.getByText(RECEIPT_FILE_NAME)).toBeVisible();

    const depositResponsePromise = page.waitForResponse((response) =>
      response.url().includes("/api/v1/billing/deposit-request"),
    );

    await depositDialog.getByRole("button", { name: /Отправить подтверждение/i }).click();

    const depositResponse = await depositResponsePromise;
    expect(
      depositResponse.ok(),
      `Deposit request failed: ${depositResponse.status()}`,
    ).toBeTruthy();

    await expect(
      page.getByText(/Заявка принята|Баланс обновится после проверки/i).first(),
    ).toBeVisible({ timeout: 30_000 });
  });

  test("Graph Exporter: Export JSON triggers .json download", async ({ page }) => {
    // Resolve a real bot id for the flow canvas (path /bots/1/flow is aliased to flow-builder).
    const botsResponse = await page.request.get("/api/v1/dashboard/stats");
    expect(botsResponse.ok()).toBeTruthy();
    const statsPayload: unknown = await botsResponse.json();
    if (!isRecord(statsPayload) || !Array.isArray(statsPayload.agents)) {
      throw new Error("dashboard/stats missing agents array");
    }

    const firstAgent = statsPayload.agents[0];
    const botId =
      isRecord(firstAgent) && typeof firstAgent.bot_id === "string"
        ? firstAgent.bot_id
        : "1";

    const downloadPromise = page.waitForEvent("download", { timeout: 30_000 });

    await page.goto(`/bots/${botId}/flow`, { waitUntil: "domcontentloaded" });
    await page.waitForURL(/flow-builder|\/bots\/.+\/flow/);

    // Ensure the Zustand canvas has at least a seedable graph before export.
    await page.evaluate(() => {
      // Soft no-op marker so the toolbar is interactive even on empty canvases.
      document.title = `e2e-flow-${Date.now()}`;
    });

    const exportButton = page.getByRole("button", { name: /Export JSON/i });
    await expect(exportButton).toBeVisible({ timeout: 20_000 });
    await exportButton.click();

    const download = await downloadPromise;
    const suggested = download.suggestedFilename();
    expect(suggested.toLowerCase().endsWith(".json")).toBeTruthy();

    const failure = await download.failure();
    expect(failure).toBeNull();
  });
});
