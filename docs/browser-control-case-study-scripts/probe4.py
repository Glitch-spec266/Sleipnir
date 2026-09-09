import sys, json
from lib import run
JS = """()=>({t:document.title, btns:[...document.querySelectorAll('button')].map(b=>b.innerText.trim()).filter(Boolean).slice(0,12),
 body:document.body.innerText.slice(0,300),
 groups:[...document.querySelectorAll('div[class*="sku-item--property"]')].map(g=>({
  title:((g.querySelector('div[class*="title"]')||{}).innerText||'').trim(),
  opts:[...g.querySelectorAll('div[class*="sku-item--image"], div[class*="sku-item--text"]')].map(e=>e.innerText.trim()||((e.querySelector('img')||{}).alt||''))}))})"""
async def f(page):
    await page.goto(f"https://www.aliexpress.us/item/{sys.argv[1]}.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(6000)
    print(json.dumps(await page.evaluate(JS), indent=1)[:1800]); print("URL:", page.url)
run(f)
