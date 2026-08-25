import { expect, test } from "@playwright/test";

import { E2E_ORG_ID, ownerMePayload, seedDashboardSession } from "./helpers/session";

test.describe("BYOK vault validation", () => {
  test.use({ baseURL: "http://127.0.0.1:3000" });
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/**", async (route) => {
      const url = route.request().url();
      const method = route.request().method();
      if (url.includes("/team/me") || url.includes("/auth/me")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(ownerMePayload()),
        });
        return;
      }
      if (url.includes("/api/v1/credentials") && method === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ items: [] }),
        });
        return;
      }
      if (url.includes("/api/v1/credentials") && method === "POST") {
        await route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({
            detail: "OpenAI rejected the key (HTTP 401).",
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

  test("invalid OpenAI key shows inline error and is not listed", async ({ page }) => {
    await page.goto("/dashboard/byok-vault", { waitUntil: "domcontentloaded" });
    await expect(page).toHaveURL(/\/dashboard\/byok-vault/);
    await page.getByTestId("byok-secret").fill("sk-invalid");
    await page.getByRole("button", { name: "Сохранить" }).click();
    await expect(page.getByTestId("byok-error")).toContainText("OpenAI rejected the key");
    await expect(page.getByTestId("byok-item")).toHaveCount(0);
  });
});
