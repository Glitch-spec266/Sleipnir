from cartlib import run, open_cart
async def f(page):
    await open_cart(page)
    for _ in range(45): await page.mouse.wheel(0,600); await page.wait_for_timeout(300)
    print(await page.evaluate("""()=>{
      const t=document.body.innerText;
      const i=t.search(/invalid|unavailable|sold out|no longer/i);
      return JSON.stringify({hit:i, ctx:i>0?t.slice(i-200,i+400):'none',
        invalidEls:[...document.querySelectorAll('div[class*=invalid],div[class*=Invalid],div[class*=unavailable]')].map(d=>d.className.split(' ')[0]).slice(0,5),
        cartHdr:(t.match(/Cart \\(\\d+\\)/)||[''])[0]});}"""))
run(f)
