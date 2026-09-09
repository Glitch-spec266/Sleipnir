import sys
from lib import run
pid = sys.argv[1]
JS = """() => {
  const out = [];
  document.querySelectorAll('div[class*="sku-item--property"], div[class*="skuProp"]').forEach(g => {
    const title = (g.querySelector('div[class*="title"]')||{}).innerText || '';
    const opts = [...g.querySelectorAll('div[class*="sku-item--box"], div[class*="sku-item--image"], [data-sku-col], span[class*="sku"]')]
      .map(e => (e.innerText||'').trim() || (e.querySelector('img')||{}).alt || '');
    out.push({title: title.trim(), opts: [...new Set(opts.filter(Boolean))]});
  });
  return {t: document.title, groups: out, hasCart: !!document.querySelector('button[class*="addcart"],[class*="add-to-cart"]')};
}"""
async def f(page):
    await page.goto(f"https://www.aliexpress.us/item/{pid}.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(6000)
    import json; print(json.dumps(await page.evaluate(JS), indent=1)[:3000])
    print("URL:", page.url)
run(f)
