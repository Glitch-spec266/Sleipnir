from cartlib import run, open_cart
async def f(page):
    await open_cart(page)
    print(await page.evaluate("""()=>{
      const hdr=document.querySelector('div[class*="cart-header-checkbox"]');
      const boxes=document.querySelectorAll('input.comet-v2-checkbox-input');
      const checked=[...boxes].filter(b=>b.checked).length;
      return JSON.stringify({hdr:hdr?hdr.className:'none', hdrText:hdr?hdr.innerText.trim():'',
        boxes:boxes.length, checked,
        total:(document.body.innerText.match(/Total[^\\n]*\\n?\\$?[0-9.,]*/)||[''])[0].slice(0,60)});}"""))
    print("MaleBlack still there:", await page.evaluate("""()=>/Male Black/.test(document.body.innerText)"""))
run(f)
