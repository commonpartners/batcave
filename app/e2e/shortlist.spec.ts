import { test, expect } from "@playwright/test";

// Requires app/e2e/fixtures.sql to be loaded into the Supabase project the
// suite is pointed at (see playwright.config.ts / auth.setup.ts).

test("shortlist renders seeded fixture companies ranked by score", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Shortlist" })).toBeVisible();

  const rows = page.locator("table tbody tr");
  await expect(rows).toHaveCount(2); // Acme Skincare + Bristol Botanicals both pass the gate

  // Default sort is score desc: Acme (82) above Bristol Botanicals (65).
  await expect(rows.nth(0)).toContainText("Acme Skincare Ltd");
  await expect(rows.nth(1)).toContainText("Bristol Botanicals Ltd");

  // Value-angle and red-flag chips from the fixture data.
  await expect(rows.nth(0)).toContainText("Reviews Strong Digital Weak");
  await expect(rows.nth(1)).toContainText("Owner Concentration");
});

test("j/k + enter keyboard navigation opens the focused company", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("table tbody tr")).toHaveCount(2);

  await page.keyboard.press("j");
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/company\/22222222/);
  await expect(page.getByRole("heading", { name: "Bristol Botanicals Ltd" })).toBeVisible();
});

test("red-flag filter narrows the list", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Red flags only").check();

  const rows = page.locator("table tbody tr");
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("Bristol Botanicals Ltd");
});
