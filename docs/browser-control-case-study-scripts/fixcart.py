"""Cart-side repairs: set quantities, delete wrong lines."""
import json, re
from lib import run

FIND = """(pat)=>{const rx=new RegExp(pat,'i');
 return [...document.querySelectorAll('div.cart-product')].findIndex(r=>rx.test(r.innerText));}"""

async def load(page):
    await page.goto("https://www.aliexpress.us/p/shoppingcart/index.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)
    for _ in range(14):
        await page.mouse.wheel(0,1400); await page.wait_for_timeout(600)

async def setqty(page, pat, n):
    i = await page.evaluate(FIND, pat)
    if i < 0: return f"NOT FOUND {pat}"
    inp = page.locator("div.cart-product").nth(i).locator("input.comet-v2-input-number-input")
    await inp.scroll_into_view_if_needed(); await inp.click()
    await inp.press("Control+a"); await inp.type(str(n)); await inp.press("Enter")
    await page.wait_for_timeout(3000)
    return f"qty[{i}] {pat} -> {await inp.input_value()}"

async def delete(page, pat):
    i = await page.evaluate(FIND, pat)
    if i < 0: return f"NOT FOUND {pat}"
    row = page.locator("div.cart-product").nth(i)
    await row.scroll_into_view_if_needed(); await row.hover(); await page.wait_for_timeout(500)
    await row.locator("span.cart-product-name-ope-trashCan").click()
    await page.wait_for_timeout(1500)
    for label in ("Remove", "Delete", "Confirm", "OK", "Yes"):
        b = page.locator(f'button:has-text("{label}")')
        if await b.count():
            await b.first.click(); break
    await page.wait_for_timeout(3000)
    return f"deleted[{i}] {pat}"

async def f(page):
    await load(page)
    print(await delete(page, r"HC-SR501[\s\S]{0,400}5PCS"))
    await load(page)
    print(await setqty(page, r"Micro USB Cable[\s\S]{0,300}\bmicro usb\b", 2))
run(f)
