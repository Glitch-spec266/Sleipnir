from lib import run
JS = """(pat)=>{const rx=new RegExp(pat,'i');
 const r=[...document.querySelectorAll('div.cart-product')].find(x=>rx.test(x.innerText));
 if(!r) return 'no row';
 const inc=r.querySelector('.comet-v2-input-number-btn-increase');
 return (inc.className.includes('disabled')?'INC DISABLED':'INC OK')+' | qty='+r.querySelector('input.comet-v2-input-number-input').value;}"""
async def f(page):
    await page.goto("https://www.aliexpress.us/p/shoppingcart/index.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)
    for _ in range(16): await page.mouse.wheel(0,1400); await page.wait_for_timeout(500)
    for p in ["SG90", "micro usb/1m", "type-c/1m", "MAX9814"]:
        print(p, "->", await page.evaluate(JS, p))
run(f)
