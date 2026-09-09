from lib import run
async def f(page):
    await page.goto("https://www.aliexpress.com/p/trade/index.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(6000)
    print("URL:", page.url)
    print("TITLE:", await page.title())
    txt = await page.evaluate("document.body.innerText.slice(0,1200)")
    print(txt)
run(f)
