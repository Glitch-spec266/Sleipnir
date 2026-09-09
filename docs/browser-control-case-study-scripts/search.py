import sys, json, urllib.parse
from lib import run
JS = """()=>[...document.querySelectorAll('a[href*="/item/"]')].map(a=>{
  const c=a.closest('div[class*="search-item-card"]')||a.parentElement.parentElement;
  const txt=(c.innerText||'').replace(/\\n+/g,' | ');
  const m=a.href.match(/item\\/(\\d+)/);
  return m?{id:m[1], t:txt.slice(0,190)}:null;}).filter(Boolean)"""
async def f(page):
    q = " ".join(sys.argv[1:])
    await page.goto("https://www.aliexpress.us/w/wholesale-"+urllib.parse.quote(q.replace(" ","-"))+".html", wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)
    seen={}
    for r in await page.evaluate(JS):
        if r["id"] not in seen and len(r["t"])>40: seen[r["id"]]=r["t"]
    for i,(k,v) in enumerate(list(seen.items())[:12]): print(i, k, v)
run(f)
