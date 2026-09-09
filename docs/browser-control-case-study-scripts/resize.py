import asyncio, sys
sys.path.insert(0,"/home/prahladv/Projects/sleipnir/src")
from sleipnir.capabilities.browser import CDP_ENDPOINT, ensure_browser
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as pw:
        await ensure_browser()
        b = await pw.chromium.connect_over_cdp(CDP_ENDPOINT)
        ctx = b.contexts[0]; page = [p for p in ctx.pages if not p.url.startswith("chrome-extension")][0]
        s = await ctx.new_cdp_session(page)
        wid = (await s.send("Browser.getWindowForTarget"))["windowId"]
        await s.send("Browser.setWindowBounds", {"windowId": wid,
            "bounds": {"windowState": "normal", "left": 0, "top": 0, "width": 1600, "height": 1200}})
        await page.wait_for_timeout(1500)
        print("innerHeight now:", await page.evaluate("innerHeight"), "innerWidth:", await page.evaluate("innerWidth"))
asyncio.run(main())
