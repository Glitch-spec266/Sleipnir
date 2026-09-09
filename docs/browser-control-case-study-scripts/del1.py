from lib import run
FIND = """(pat)=>{const rx=new RegExp(pat,'i');
 return [...document.querySelectorAll('div.cart-product')].findIndex(r=>rx.test(r.innerText));}"""
async def f(page):
    await page.goto("https://www.aliexpress.us/p/shoppingcart/index.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(8000)
    for _ in range(16): await page.mouse.wheel(0,1400); await page.wait_for_timeout(500)
    i = await page.evaluate(FIND, r"1PC-180 Degree")
    print("row", i)
    if i>=0:
        row = page.locator("div.cart-product").nth(i)
        await row.scroll_into_view_if_needed(); await row.hover(); await page.wait_for_timeout(500)
        await row.locator("span.cart-product-name-ope-trashCan").click(); await page.wait_for_timeout(1500)
        for lbl in ("Remove","Delete","Confirm","Yes","OK"):
            b=page.locator(f'button:has-text("{lbl}")')
            if await b.count(): await b.first.click(); print("confirmed via",lbl); break
        await page.wait_for_timeout(3000)
    print("remaining rows:", await page.evaluate("document.querySelectorAll('div.cart-product').length"))
run(f)
