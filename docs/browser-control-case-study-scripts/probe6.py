from lib import run
JS = """()=>{const r=[...document.querySelectorAll('div.cart-product')][28];
 return [...r.querySelectorAll('*')].filter(e=>/delete|remove|trash/i.test(e.className+e.getAttribute('aria-label'))).map(e=>e.tagName+'.'+e.className.slice(0,45)).slice(0,6);}"""
async def f(page):
    await page.goto("https://www.aliexpress.us/p/shoppingcart/index.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)
    for _ in range(14):
        await page.mouse.wheel(0,1400); await page.wait_for_timeout(600)
    print(await page.evaluate(JS))
run(f)
