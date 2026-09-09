const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(process.env.PW_MODULE);

const root = __dirname;
const browserPath = process.env.PW_BROWSER;
const base = process.env.PROTOTYPE_URL || "http://127.0.0.1:4173";
const directions = [
  "01-relay", "02-atelier", "03-vector", "04-orbit", "05-current",
  "06-index", "07-mission", "08-glasshouse", "09-chronicle", "10-helm"
];
const pages = ["command", "graph", "console", "review", "routing", "trust"];

(async () => {
  fs.mkdirSync(path.join(root, "screenshots"), { recursive: true });
  fs.mkdirSync(path.join(root, "screenshots", "pages"), { recursive: true });
  const browser = await chromium.launch({ executablePath: browserPath, headless: true });
  const report = { viewport: "1440x900", directions: [], errors: [] };

  for (const direction of directions) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
    const errors = [];
    page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(`console: ${message.text()}`);
    });
    await page.goto(`${base}/directions/${direction}.html`, { waitUntil: "networkidle" });
    await page.screenshot({ path: path.join(root, "screenshots", `${direction}.png`) });

    for (const pageId of pages) {
      await page.locator(`[data-page="${pageId}"]`).first().click();
      await page.waitForTimeout(40);
      const activeCount = await page.locator(`[data-page="${pageId}"].active`).count();
      if (!activeCount) errors.push(`navigation: ${pageId} did not become active`);
      await page.screenshot({ path: path.join(root, "screenshots", "pages", `${direction}-${pageId}.png`) });
    }

    await page.locator('[data-page="graph"]').first().click();
    await page.locator('[data-task="t020"]').click();
    const selected = await page.locator("#selected-task-title").textContent();
    if (!selected.includes("Sign on physical device")) errors.push("interaction: graph selection failed");
    report.directions.push({ direction, pagesChecked: pages.length, selectedTask: selected, errors });
    report.errors.push(...errors.map((error) => `${direction}: ${error}`));
    await page.close();
  }

  const gallery = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  gallery.on("pageerror", (error) => report.errors.push(`gallery pageerror: ${error.message}`));
  await gallery.goto(`${base}/`, { waitUntil: "networkidle" });
  await gallery.screenshot({ path: path.join(root, "screenshots", "gallery.png"), fullPage: true });
  report.galleryCards = await gallery.locator(".concept-card").count();
  await gallery.close();
  await browser.close();
  fs.writeFileSync(path.join(root, "screenshots", "report.json"), JSON.stringify(report, null, 2));

  console.log(`checked ${report.directions.length} directions / ${report.directions.length * pages.length} page states`);
  console.log(`gallery cards: ${report.galleryCards}`);
  console.log(`errors: ${report.errors.length}`);
  if (report.errors.length) {
    console.error(report.errors.join("\n"));
    process.exitCode = 1;
  }
})();
