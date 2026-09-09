import asyncio, sys, json
sys.path.insert(0, "/home/prahladv/Projects/sleipnir/src")
from sleipnir.capabilities.browser import CDP_ENDPOINT, ensure_browser
from playwright.async_api import async_playwright

async def get_page(pw):
    await ensure_browser()
    b = await pw.chromium.connect_over_cdp(CDP_ENDPOINT)
    ctx = b.contexts[0]
    pages = [p for p in ctx.pages if not p.url.startswith("chrome-extension")]
    page = pages[0] if pages else await ctx.new_page()
    return b, page

def run(fn):
    async def main():
        async with async_playwright() as pw:
            b, page = await get_page(pw)
            await fn(page)
    asyncio.run(main())
