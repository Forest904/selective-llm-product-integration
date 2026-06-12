import { expect, test } from "@playwright/test";
import { source as axeSource } from "axe-core";

test("desktop visitor can navigate the educational demo", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Mosaic turns messy product catalogs/i })).toBeVisible();
  await expect(page.getByLabel(/Animated Mosaic data flow illustration/i)).toBeVisible();
  await page.getByRole("link", { name: /Pipeline/ }).click();
  await expect(page.getByRole("heading", { name: /Watch source records/i })).toBeVisible();
  await expect(page.locator('[data-stage-scene]:not([hidden])').getByLabel("Animated stage flow scene")).toBeVisible();
  await page.getByRole("button", { name: "Step forward" }).click();
  await expect(page.getByRole("heading", { name: "Schema Alignment" })).toBeVisible();
});

test("pipeline controls preserve the complete interactive story", async ({ page }) => {
  await page.goto("/pipeline/");

  await page.getByLabel("Stage selector").selectOption("4");
  await expect(page.getByRole("heading", { name: "Record Linkage" })).toBeVisible();
  await expect(page.getByText(/classical model accepts/i)).toBeVisible();

  await page.getByRole("button", { name: "LLM" }).click();
  await expect(page.getByText(/LLM abstains on A6000/i)).toBeVisible();
  await expect(page.locator('[data-stage-scene]:not([hidden])').getByText("assisted path", { exact: true })).toBeVisible();

  await page.getByLabel("Toggle uncertainty overlay").uncheck();
  await page.getByLabel("Toggle provenance overlay").uncheck();
  const activePanel = page.locator('[data-stage-panel]:not([hidden])');
  await expect(activePanel.getByText("Uncertainty", { exact: true })).toBeHidden();
  await expect(activePanel.getByText("Provenance", { exact: true })).toBeHidden();

  await page.getByRole("button", { name: "Reset pipeline demo" }).click();
  await expect(page.getByRole("heading", { name: "Heterogeneous Sources" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Baseline" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("Toggle uncertainty overlay")).toBeChecked();
  await expect(page.getByLabel("Toggle provenance overlay")).toBeChecked();
});

test("pipeline playback advances and can be paused", async ({ page }) => {
  await page.goto("/pipeline/");
  await page.getByRole("button", { name: "Play pipeline animation" }).click();
  await expect(page.getByRole("button", { name: "Pause pipeline animation" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Schema Alignment" })).toBeVisible({ timeout: 4_000 });
  await page.getByRole("button", { name: "Pause pipeline animation" }).click();
  await expect(page.getByRole("button", { name: "Play pipeline animation" })).toBeVisible();
});

test("concept explorer switches modules and reveals a lesson", async ({ page }) => {
  await page.goto("/concepts/");
  await page.getByRole("tab", { name: "Record Linkage" }).click();
  await expect(page.getByRole("heading", { name: "Record Linkage" })).toBeVisible();
  await page.getByRole("button", { name: "Unsure" }).click();
  await expect(page.getByText(/Borderline pairs should expose uncertainty/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Unsure" })).toHaveAttribute("aria-pressed", "true");
});

test("mobile layout keeps pipeline controls usable by keyboard", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/pipeline/");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: /Step backward/ })).toBeVisible();
  await expect(page.getByLabel("Stage selector")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("pipeline page has no serious accessibility violations", async ({ page }) => {
  await page.goto("/pipeline/");
  await page.addScriptTag({ content: axeSource });
  const violations = await page.evaluate(async () => {
    const axe = (window as typeof window & { axe: { run: () => Promise<{ violations: Array<{ impact: string | null; id: string }> }> } }).axe;
    const result = await axe.run();
    return result.violations.filter((item) => item.impact === "critical" || item.impact === "serious");
  });
  expect(violations).toEqual([]);
});

test("static assets and polished pages load without favicon errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });

  await page.goto("/results/");
  await expect(page.getByRole("heading", { name: /Fixture-labeled comparison/i })).toBeVisible();
  const favicon = await page.request.get("/favicon.ico");
  expect(favicon.status()).toBe(200);
  expect(errors.filter((error) => error.includes("favicon"))).toEqual([]);
});
