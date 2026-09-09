from cartlib import run, open_cart
async def f(page):
    await open_cart(page)
    print("checked:", await page.evaluate("()=>[...document.querySelectorAll('input.comet-v2-checkbox-input')].filter(b=>b.checked).length"))
    print(await page.evaluate("""()=>{const h=document.querySelector('div[class*="cart-header-checkbox"]');
      return h.outerHTML.replace(/></g,'>\\n<').slice(0,700);}"""))
run(f)
