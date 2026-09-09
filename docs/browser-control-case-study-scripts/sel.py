from cartlib import run, open_cart, locate
async def f(page):
    await open_cart(page)
    hdr = page.locator('div[class*="cart-header-checkbox"] label, div[class*="cart-header-checkbox"] input').first
    n = await page.evaluate("()=>[...document.querySelectorAll('input.comet-v2-checkbox-input')].filter(b=>b.checked).length")
    print("checked before:", n)
    if n:  # deselect all first
        await hdr.click(); await page.wait_for_timeout(3000)
        print("after deselect:", await page.evaluate("()=>[...document.querySelectorAll('input.comet-v2-checkbox-input')].filter(b=>b.checked).length"))
    row = await locate(page, "Electrolytic Capacitor Mixed DIP")
    if row is None: print("ELECTROLYTIC NOT FOUND"); return
    await row.locator('label.comet-v2-checkbox, span.comet-v2-checkbox, input.comet-v2-checkbox-input').first.click()
    await page.wait_for_timeout(3000)
    print("after ticking electrolytic:", await page.evaluate("()=>[...document.querySelectorAll('input.comet-v2-checkbox-input')].filter(b=>b.checked).length"))
    await page.keyboard.press("Home"); await page.wait_for_timeout(1500)
    await page.locator('div[class*="cart-header-checkbox"]').first.click()
    await page.wait_for_timeout(5000)
    print("TOTAL BLOCK:", await page.evaluate("""()=>{const t=document.body.innerText;
      const i=t.indexOf('Checkout'); return t.slice(Math.max(0,i-260), i+40).replace(/\\n+/g,' | ');}"""))
run(f)
