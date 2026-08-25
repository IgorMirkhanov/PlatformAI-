/**
 * Wallet / BYOK / playground E2E — mocked API, no live backend.
 */
import { expect, test } from "@playwright/test";

import {
  E2E_ORG_ID,
  ownerMePayload,
  seedDashboardSession,
} from "./helpers/session";

function blockedWalletBody() {
  return {
    organization_id: E2E_ORG_ID,
    balance_tokens: 0,
    credit_balance: 0,
    status: "blocked",
    low_balance_threshold: 1000,
    blocked_at: new Date().toISOString(),
    transactions: [],
  };
}

test.describe("wallet isolation UI", () => {
  test.use({ baseURL: "http://127.0.0.1:3000" });
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/**", async (route) => {
      const url = route.request().url();
      if (url.includes("/team/me") || url.includes("/auth/me")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(ownerMePayload()),
        });
        return;
      }
      if (url.includes("/api/v1/wallet/usage-by-bot")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ organization_id: E2E_ORG_ID, days: 7, items: [] }),
        });
        return;
      }
      if (url.includes("/api/v1/wallet")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(blockedWalletBody()),
        });
        return;
      }
      if (url.includes("/playground/chat")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            text: "AI agent is temporarily unavailable. Transferring to an operator.",
            model_name: null,
            input_tokens: 0,
            output_tokens: 0,
            total_tokens: 0,
            estimated_cost_tokens: 0,
            dry_run: true,
            wallet_blocked: true,
            rag_context: [],
          }),
        });
        return;
      }
      if (url.includes("/billing/status") || url.includes("/organizations/usage")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            balance: 0,
            is_low_balance: false,
            wallet_balance_kzt: 0,
            low_balance_threshold_kzt: 2500,
          }),
        });
        return;
      }
      if (url.includes("/dashboard/stats")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ agents: [], total_agents: 0 }),
        });
        return;
      }
      if (url.includes("/billing/notifications") || url.includes("/diagnostic")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ notifications: [], logs: [], total: 0, unread_critical: 0 }),
        });
        return;
      }
      if (url.includes("/team/organizations")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            organizations: [{ id: E2E_ORG_ID, name: "E2E Org", is_active: true }],
            active_company_id: E2E_ORG_ID,
          }),
        });
        return;
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });
    await seedDashboardSession(page);
  });

  test("blocked wallet shows top-up CTA and status", async ({ page }) => {
    await page.goto("/dashboard/wallet", { waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(/\/dashboard\/wallet/);
    await expect(page.getByTestId("wallet-page-blocked-banner")).toBeVisible();
    await expect(page.getByTestId("wallet-status")).toHaveText("blocked");
    await expect(page.getByTestId("wallet-balance")).toHaveText("0");
    await expect(page.getByTestId("wallet-page-blocked-banner").getByText("Пополнить")).toBeVisible();
  });

  test("dashboard shows blocked wallet banner", async ({ page }) => {
    await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByTestId("wallet-blocked-banner")).toBeVisible();
    await expect(page.getByText("Кошелёк заблокирован")).toBeVisible();
  });

  test("wallet page polls GET /api/v1/wallet", async ({ page }) => {
    let walletGets = 0;
    await page.route((url) => {
      const href = url.toString();
      return href.includes("/api/v1/wallet") && !href.includes("usage-by-bot");
    }, async (route) => {
      walletGets += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(blockedWalletBody()),
      });
    });
    await page.goto("/dashboard/wallet", { waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(/\/dashboard\/wallet/);
    await expect(page.getByTestId("wallet-page-blocked-banner")).toBeVisible();
    const afterFirst = walletGets;
    expect(afterFirst).toBeGreaterThanOrEqual(1);
    await page.waitForTimeout(10_500);
    expect(walletGets).toBeGreaterThan(afterFirst);
  });

  test("playground surfaces wallet blocked error", async ({ page }) => {
    await page.goto("/dashboard/playground", { waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(/\/dashboard\/playground/);
    await page.getByTestId("playground-input").fill("hello");
    await page.getByRole("button", { name: "Отправить" }).click();
    await expect(page.getByTestId("playground-error")).toBeVisible();
  });
});
