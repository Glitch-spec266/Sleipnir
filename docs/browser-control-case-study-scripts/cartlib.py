"""Cart access that survives row virtualisation: scroll, accumulate, act."""
import json, sys, asyncio
sys.path.insert(0, "/home/prahladv/Projects/sleipnir/src")
from lib import get_page
from playwright.async_api import async_playwright

CART = "https://www.aliexpress.us/p/shoppingcart/index.html"

ROWS = """()=>[...document.querySelectorAll('div.cart-product')].map(r=>{
  const L=(r.innerText||'').split('\\n').map(s=>s.trim()).filter(Boolean);
  const q=r.querySelector('input.comet-v2-input-number-input');
  return {name:(L.find(s=>s.length>25)||L[0]||''), all:L.join(' | ').slice(0,220), qty:q?q.value:'?',
          price:(L.find(s=>/^\\$[0-9]/.test(s))||'')};})"""

async def open_cart(page):
    await page.goto(CART, wait_until="domcontentloaded")
    await page.wait_for_timeout(9000)

async def scan(page):
    """Scroll top->bottom collecting every row that ever mounts."""
    seen = {}
    await page.keyboard.press("Home"); await page.wait_for_timeout(1200)
    for direction in (400, -400):
        for _ in range(60):
            for r in await page.evaluate(ROWS):
                if r["name"]:
                    seen.setdefault(r["name"] + "|" + r["all"][:80], r)
            await page.mouse.wheel(0, direction)
            await page.wait_for_timeout(350)
    return list(seen.values())

IDX = """(pat)=>{const rx=new RegExp(pat,'i');
  return [...document.querySelectorAll('div.cart-product')].findIndex(r=>rx.test(r.innerText));}"""

async def locate(page, pat):
    """Scroll until the row matching pat is mounted; return its live locator."""
    await page.keyboard.press("Home"); await page.wait_for_timeout(1000)
    for _ in range(45):
        i = await page.evaluate(IDX, pat)
        if i >= 0:
            return page.locator("div.cart-product").nth(i)
        await page.mouse.wheel(0, 600)
        await page.wait_for_timeout(450)
    return None

async def delete(page, pat):
    row = await locate(page, pat)
    if row is None: return f"NOT FOUND: {pat}"
    txt = (await row.inner_text()).replace("\n", " | ")[:110]
    await row.hover(); await page.wait_for_timeout(500)
    await row.locator("span.cart-product-name-ope-trashCan").click()
    await page.wait_for_timeout(1500)
    for lbl in ("Remove", "Delete", "Confirm", "Yes", "OK"):
        b = page.locator(f'button:has-text("{lbl}")')
        if await b.count():
            await b.first.click(); break
    await page.wait_for_timeout(3500)
    return f"DELETED: {txt}"

def run(fn):
    async def main():
        async with async_playwright() as pw:
            b, page = await get_page(pw)
            await fn(page)
    asyncio.run(main())
