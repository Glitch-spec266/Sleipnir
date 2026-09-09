from lib import run
JS = """()=>{const r=[...document.querySelectorAll('div.cart-product')].find(x=>/SG90/.test(x.innerText));
 return [...r.querySelectorAll('*')].filter(e=>/number|plus|step|increase/i.test(e.className)).map(e=>e.tagName+'.'+e.className.slice(0,55)).slice(0,10);}"""
async def f(page):
    await page.goto("https://www.aliexpress.us/p/shoppingcart/index.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)
    for _ in range(16): await page.mouse.wheel(0,1400); await page.wait_for_timeout(500)
    print(await page.evaluate(JS))
run(f)
