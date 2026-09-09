import json
from lib import run
JS = """()=>[...document.querySelectorAll('div.cart-product')].map(r=>{
  const L=(r.innerText||'').split('\\n').map(s=>s.trim()).filter(Boolean);
  const q=r.querySelector('input.comet-v2-input-number-input');
  const price=(L.find(s=>/^\\$[0-9]/.test(s))||'');
  return {name:L.find(s=>s.length>25)||L[0], variant:L.find(s=>/\\//.test(s)&&s.length<60)||'', qty:q?q.value:'?', price};})"""
async def f(page):
    await page.goto("https://www.aliexpress.us/p/shoppingcart/index.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)
    for _ in range(16):
        await page.mouse.wheel(0,1400); await page.wait_for_timeout(600)
    rows = await page.evaluate(JS)
    json.dump(rows, open("/tmp/claude-1000/-home-prahladv/7bbbd975-0d9a-44f8-8d64-f9e4fe13d3c9/scratchpad/ali/final_cart.json","w"), indent=1)
    tot=0
    for i,r in enumerate(rows):
        p=r["price"].replace("$","")
        try: tot += float(p)*int(r["qty"])
        except: pass
        print(f'{i:2} x{r["qty"]} {r["price"]:>7}  {r["name"][:58]:58} | {r["variant"][:34]}')
    print("ROWS", len(rows), "SUBTOTAL(list) ~$%.2f" % tot)
run(f)
