from lib import run
import re
async def f(page):
    await page.goto("https://www.aliexpress.us/p/shoppingcart/index.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(7000)
    t = await page.evaluate("document.body.innerText")
    t = re.sub(r'\n{2,}','\n',t)
    i = t.find('Shopping Cart')
    print(t[i if i>0 else 0:][:2500])
run(f)
