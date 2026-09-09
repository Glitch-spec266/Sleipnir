from lib import run
async def f(page):
    print(await page.evaluate("""()=>{const e=document.querySelector('[class*="cart-summary"]');return e?e.parentElement.innerText.slice(0,300):'NO SUMMARY';}"""))
run(f)
