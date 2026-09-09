from cartlib import run, open_cart, locate
TOT = """()=>{const t=document.body.innerText; const i=t.indexOf('Checkout');
  return t.slice(Math.max(0,i-220), i+20).replace(/\\n+/g,' | ');}"""
CNT = "()=>[...document.querySelectorAll('input.comet-v2-checkbox-input')].filter(b=>b.checked).length"
async def f(page):
    await open_cart(page)
    hdr = page.locator('div[class*="cart-header-checkbox-wrap"] label.comet-v2-checkbox').first
    if await page.evaluate(CNT):
        await hdr.click(); await page.wait_for_timeout(4000)
    print("deselected ->", await page.evaluate(CNT))
    row = await locate(page, "Electrolytic Capacitor Mixed DIP")
    await row.locator('label.comet-v2-checkbox').first.click(); await page.wait_for_timeout(4000)
    print("electrolytic ticked ->", await page.evaluate(CNT))
    await page.keyboard.press("Home"); await page.wait_for_timeout(2000)
    await page.locator('div[class*="cart-header-checkbox-wrap"] label.comet-v2-checkbox').first.click()
    await page.wait_for_timeout(7000)
    print("all ->", await page.evaluate(CNT))
    print("ORDERED:", await page.evaluate(TOT))
run(f)
