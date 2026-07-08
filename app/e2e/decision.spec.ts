import { test, expect } from "@playwright/test";

// Requires app/e2e/fixtures.sql loaded (see shortlist.spec.ts).

test("open a company, record a decision, and see it in the decision history", async ({ page }) => {
  await page.goto("/company/11111111");
  await expect(page.getByRole("heading", { name: "Acme Skincare Ltd" })).toBeVisible();

  // "Why this rank" dimension bars from the fixture score_dimensions rows.
  await expect(page.getByText("Brand Customer Equity")).toBeVisible();
  await page.getByText("Brand Customer Equity").click();
  await expect(page.getByText(/repeat-purchase/i)).toBeVisible();

  // Sticky decision bar - Accept opens the reason-code dialog.
  await page.getByRole("button", { name: "Accept" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();

  await page.getByLabel("Love The Heritage Angle").check();
  await page.getByLabel("Brand Stronger Than Score").check();
  await page.getByLabel("Notes (optional)").fill("E2E smoke test decision.");
  await page.getByRole("button", { name: "Record decision" }).click();

  await expect(page.getByRole("dialog")).toBeHidden();

  const history = page.getByText("Decision history").locator("..");
  await expect(history.getByText("Accept")).toBeVisible();
  await expect(history.getByText("Love The Heritage Angle")).toBeVisible();
  await expect(history.getByText("Brand Stronger Than Score")).toBeVisible();
});

test("decision dialog requires at least one reason code", async ({ page }) => {
  await page.goto("/company/22222222");
  await page.getByRole("button", { name: "Reject" }).click();
  await page.getByRole("button", { name: "Record decision" }).click();
  await expect(page.getByText("Pick at least one reason code.")).toBeVisible();
});
