import { expect, test } from "@playwright/test";

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
