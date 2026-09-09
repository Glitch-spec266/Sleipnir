import sys, json
from lib import run
JS = """() => [...document.querySelectorAll('div[class*="sku-item--property"]')].map((g,gi)=>({gi,
  title:((g.querySelector('div[class*="title"]')||{}).innerText||'').trim(),
  boxes:[...g.querySelectorAll('div[class*="sku-item--box"]')].map(e=>e.innerText.trim()),
  imgs:[...g.querySelectorAll('div[class*="sku-item--image"]')].map(e=>(e.querySelector('img')||{}).alt||''),
  raw:[...g.children].map(c=>c.className.slice(0,50))
}))"""
async def f(page):
    await page.goto(f"https://www.aliexpress.us/item/{sys.argv[1]}.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(5500)
    print(json.dumps(await page.evaluate(JS), indent=1)[:2500])
run(f)
