import sys
from lib import run
JS = """() => {
  const g = document.querySelectorAll('div[class*="sku-item--property"]')[1];
  const walk = (e,d) => d>3?'':[...e.children].map(c=>' '.repeat(d*2)+c.tagName+'.'+c.className.slice(0,45)+' | '+(c.children.length?'':c.innerText.trim().slice(0,20))+'\\n'+walk(c,d+1)).join('');
  return walk(g,0);
}"""
async def f(page):
    await page.goto(f"https://www.aliexpress.us/item/{sys.argv[1]}.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(5500)
    print(await page.evaluate(JS))
run(f)
