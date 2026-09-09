from cartlib import run, open_cart
async def f(page):
    await open_cart(page)
    before = await page.evaluate("()=>[...document.querySelectorAll('input.comet-v2-checkbox-input')].filter(b=>b.checked).length")
    await page.locator('div[class*="cart-header-checkbox-wrap"] label.comet-v2-checkbox').first.click()
    await page.wait_for_timeout(6000)
    print("checked:", before, "->", await page.evaluate("()=>[...document.querySelectorAll('input.comet-v2-checkbox-input')].filter(b=>b.checked).length"))
    print(await page.evaluate("""()=>{const t=document.body.innerText; const i=t.indexOf('Checkout');
      return t.slice(Math.max(0,i-200), i+20).replace(/\\n+/g,' | ');}"""))
run(f)
