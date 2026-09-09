import json
from lib import run
JS = """()=>[...document.querySelectorAll('button')].map(b=>{const r=b.getBoundingClientRect();
 return {t:b.innerText.trim().slice(0,20), cls:b.className.slice(0,40), dis:b.disabled, w:Math.round(r.width), h:Math.round(r.height)};})
 .filter(b=>/cart|buy|sold|out/i.test(b.t+b.cls))"""
async def f(page):
    await page.goto("https://www.aliexpress.us/item/2251832474204589.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(6000)
    print("BEFORE", json.dumps(await page.evaluate(JS)))
    el = page.locator('div[class*="sku-item--property"]').nth(0).locator('div[class*="sku-item--image"], div[class*="sku-item--text"]').nth(1)
    await el.click(); await page.wait_for_timeout(2500)
    print("TITLE", await page.evaluate("""()=>document.querySelector('div[class*="sku-item--title"]').innerText"""))
    print("AFTER ", json.dumps(await page.evaluate(JS)))
run(f)
