from lib import run
JS = """(pat)=>{const rx=new RegExp(pat,'i');
 const r=[...document.querySelectorAll('div.cart-product')].find(x=>rx.test(x.innerText));
 if(!r) return 'no row';
 const n=r.querySelector('.comet-v2-input-number');
 return n.outerHTML.replace(/></g,'>\\n<').slice(0,900);}"""
async def f(page):
    await page.goto("https://www.aliexpress.us/p/shoppingcart/index.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)
    for _ in range(16): await page.mouse.wheel(0,1400); await page.wait_for_timeout(500)
    print("SG90:\n", await page.evaluate(JS, "SG90"))
run(f)
