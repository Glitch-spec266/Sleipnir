from cartlib import run, open_cart
async def f(page):
    await open_cart(page)
    print("scrollY0", await page.evaluate("window.scrollY"), "bodyH", await page.evaluate("document.body.scrollHeight"), "winH", await page.evaluate("innerHeight"))
    await page.mouse.move(700, 500)
    await page.mouse.wheel(0, 2000); await page.wait_for_timeout(1500)
    print("scrollY1", await page.evaluate("window.scrollY"), "rows", await page.evaluate("document.querySelectorAll('div.cart-product').length"))
    await page.evaluate("window.scrollTo(0,3000)"); await page.wait_for_timeout(1500)
    print("scrollY2", await page.evaluate("window.scrollY"), "rows", await page.evaluate("document.querySelectorAll('div.cart-product').length"))
    print("scrollers:", await page.evaluate("""()=>JSON.stringify([...document.querySelectorAll('div')].filter(d=>d.scrollHeight>d.clientHeight+200&&d.clientHeight>200).map(d=>[d.className.split(' ')[0],d.clientHeight,d.scrollHeight]).slice(0,6))"""))
    print("groups:", await page.evaluate("document.querySelectorAll('div.cart-product-wrap-group-new').length"))
run(f)
