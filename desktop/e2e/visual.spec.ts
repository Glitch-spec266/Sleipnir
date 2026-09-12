import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("voice workspace is operable in every color scheme", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });

  await page.goto("/");
  await expect(page.getByText("Local core connected")).toBeVisible();
  await page.getByRole("button", { name: "Voice" }).click();
  await expect(page.getByRole("heading", { name: "Sleipnir is listening." })).toBeVisible();

  for (const scheme of ["orbit", "index", "glasshouse"] as const) {
    await page.getByLabel("Color scheme").selectOption(scheme);
    await expect(page.locator(".app")).toHaveAttribute("data-scheme", scheme);
  }

  await page.getByRole("button", { name: "Stop listening" }).click();
  await expect(page.getByRole("heading", { name: "Voice is off." })).toBeVisible();
  expect(errors).toEqual([]);
});

test("voice settings scroll behind a dock that remains an exit", async ({ page }) => {
  await page.setViewportSize({ width: 960, height: 680 });
  await page.goto("/");
  await expect(page.getByText("Local core connected")).toBeVisible();
  await page.getByRole("button", { name: "Voice" }).click();

  const bounds = await page.locator(".app-footer").evaluate((footer) => {
    const rect = footer.getBoundingClientRect();
    return { top: rect.top, bottom: rect.bottom, viewport: window.innerHeight };
  });
  expect(bounds.top).toBeGreaterThanOrEqual(0);
  expect(bounds.bottom).toBeLessThanOrEqual(bounds.viewport);
  await expect(page.getByRole("button", { name: "Home" })).toBeVisible();

  const workspace = page.locator(".workspace");
  await workspace.hover();
  await page.mouse.wheel(0, 500);
  await expect.poll(() => workspace.evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
  await expect(page.getByRole("button", { name: "Home" })).toBeVisible();

  await page.getByRole("button", { name: "Home" }).click();
  await expect(page.getByLabel("New instruction")).toBeVisible();
});

test("advanced mode exposes the operational workspaces", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Advanced mode" }).click();

  for (const label of ["Console", "Chronicle", "Routing", "Trust", "Settings"]) {
    await expect(page.getByRole("button", { name: label })).toBeVisible();
  }
});

test("voice orb stays compact and opens the workbench", async ({ page }) => {
  await page.setViewportSize({ width: 208, height: 208 });
  await page.goto("/?surface=orb");

  await expect(page.getByRole("button", { name: "Open Sleipnir" })).toBeVisible();
  await expect(page.getByText("Hey, Sleipnir")).toBeVisible();
  expect(await page.evaluate(() => ({
    width: document.documentElement.scrollWidth,
    height: document.documentElement.scrollHeight,
  }))).toEqual({ width: 208, height: 208 });
});

test("simple and advanced workspaces have no detectable accessibility violations", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Local core connected")).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.getByRole("button", { name: "Advanced mode" }).click();
  await page.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Advanced is yours to tune." })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
