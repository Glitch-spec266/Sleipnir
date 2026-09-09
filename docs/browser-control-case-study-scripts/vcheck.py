from lib import run
JS = """(pat)=>{const rx=new RegExp(pat,'i');
 const r=[...document.querySelectorAll('div.cart-product')].find(x=>rx.test(x.innerText));
 if(!r) return 'NOT FOUND';
 const L=(r.innerText||'').split('\\n').map(s=>s.trim()).filter(Boolean);
 return L.slice(0,6).join(' | ').slice(0,170);}"""
async def f(page):
    await page.goto("https://www.aliexpress.us/p/shoppingcart/index.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)
    for _ in range(16): await page.mouse.wheel(0,1400); await page.wait_for_timeout(500)
    for p in ["SG90","TP4056","LM2596S Step","MAX9814","LED Light White","Breadboard MB102","ESP32-CAM","0.96 inch oled","Relay Module Board"]:
        print(p, "=>", await page.evaluate(JS,p))
run(f)
