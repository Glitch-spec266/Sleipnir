import json, re
from lib import run
JS = """()=>[...document.querySelectorAll('div.cart-product')].map(r=>{
   const q=r.querySelector('input[class*="comet"], input[type="text"], input[type="number"]');
   const t=(r.innerText||'').split('\\n').map(s=>s.trim()).filter(Boolean);
   return {q:q?q.value:'?', t:t.slice(0,4).join(' | ').slice(0,140)};})"""
async def f(page):
    await page.goto("https://www.aliexpress.us/p/shoppingcart/index.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)
    for _ in range(14):
        await page.mouse.wheel(0, 1400); await page.wait_for_timeout(700)
    await page.evaluate("window.scrollTo(0,0)"); await page.wait_for_timeout(1500)
    rows = await page.evaluate(JS)
    print("ROWS", len(rows))
    for i,r in enumerate(rows): print(f"{i:2} q={r['q']:>3} {r['t']}")
run(f)
