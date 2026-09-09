from lib import run
JS = """()=>[...document.querySelectorAll('div.cart-product')].map((r,i)=>{
  const ins=[...r.querySelectorAll('input')].map(e=>[e.className.split(' ')[0],e.value,e.type]);
  const spans=[...r.querySelectorAll('[class*="quantity"],[class*="Quantity"]')].map(e=>e.className.split(' ')[0]+':'+e.innerText.trim().slice(0,10));
  return {i, ins, spans:spans.slice(0,3), name:(r.innerText||'').split('\\n')[1].slice(0,45)};})"""
async def f(page):
    await page.goto("https://www.aliexpress.us/p/shoppingcart/index.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)
    for _ in range(14):
        await page.mouse.wheel(0,1400); await page.wait_for_timeout(600)
    import json
    for r in await page.evaluate(JS): print(json.dumps(r))
run(f)
