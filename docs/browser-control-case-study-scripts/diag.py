from lib import run
async def f(page):
    await page.goto("https://www.aliexpress.us/p/shoppingcart/index.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(9000)
    print("URL:", page.url)
    print("cart-product:", await page.evaluate("document.querySelectorAll('div.cart-product').length"))
    print("any cart cls:", await page.evaluate("""()=>JSON.stringify([...new Set([...document.querySelectorAll('div[class*=cart]')].map(d=>d.className.split(' ')[0]))].slice(0,12))"""))
    t = await page.evaluate("document.body.innerText")
    print("TEXT:", t.replace("\n"," | ")[:600])
run(f)
