"""Read price + shipping + rating/orders straight off a listing page."""
import sys, json, re
from lib import run
JS = """()=>{
 const t=document.body.innerText;
 const ship=(t.match(/(Free [Ss]hipping|Shipping:?\\s*\\$[0-9.,]+|\\$[0-9.,]+\\s*[Ss]hipping)/)||[''])[0];
 const price=(t.match(/\\$[0-9][0-9.,]*/)||[''])[0];
 const sold=(t.match(/[0-9,+]+\\s*sold/i)||[''])[0];
 const rate=(t.match(/\\n([45]\\.[0-9])\\n/)||['',''])[1];
 const grp=[...document.querySelectorAll('div[class*="sku-item--property"]')].map(g=>({
   title:((g.querySelector('div[class*="title"]')||{}).innerText||'').trim().split(':')[0],
   opts:[...g.querySelectorAll('div[class*="sku-item--image"], div[class*="sku-item--text"]')]
        .map(e=>e.innerText.trim()||((e.querySelector('img')||{}).alt||''))}));
 return {price, ship, sold, rate, grp};}"""
async def f(page):
    out=[]
    for pid in sys.argv[1:]:
        await page.goto(f"https://www.aliexpress.us/item/{pid}.html", wait_until="domcontentloaded")
        await page.wait_for_timeout(6000)
        r = await page.evaluate(JS); r["id"]=pid
        print(json.dumps(r)[:600], flush=True)
run(f)
