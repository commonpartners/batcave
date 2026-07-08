import { test, expect } from "@playwright/test";

// This test intentionally starts unauthenticated, unlike the rest of the
// suite (see playwright.config.ts's chromium project storageState).
test.use({ storageState: { cookies: [], origins: [] } });

test("unauthenticated visitors are redirected to /login", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole("heading", { name: "Common Partners" })).toBeVisible();
});

test("rejects a non-allowlisted email before sending a magic link", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("someone-else@example.com");
  await page.getByRole("button", { name: "Send magic link" }).click();
  await expect(page.getByText(/reviewer allowlist/i)).toBeVisible();
});

test("sends a magic link for an allowlisted email", async ({ page }) => {
  const email = (process.env.NEXT_PUBLIC_ALLOWLISTED_EMAILS ?? "julia@thebothy.club").split(",")[0].trim();
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send magic link" }).click();
  await expect(page.getByText("Check")).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();
});
