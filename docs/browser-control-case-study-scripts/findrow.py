import sys
from cartlib import run, open_cart, locate
async def f(page):
    await open_cart(page)
    for pat in sys.argv[1:]:
        r = await locate(page, pat)
        print(pat, "->", (await r.inner_text()).replace("\n"," | ")[:120] if r else "NOT IN CART")
run(f)
