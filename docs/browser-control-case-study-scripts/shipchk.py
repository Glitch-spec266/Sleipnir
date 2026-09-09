import sys
from cartlib import run, open_cart, locate
async def f(page):
    await open_cart(page)
    for pat in sys.argv[1:]:
        r = await locate(page, pat)
        if r is None: print(pat, "-> NOT IN CART"); continue
        t = (await r.inner_text()).replace("\n", " | ")
        import re
        ship = re.search(r"Shipping Fee: \$[0-9.,]+", t)
        print(f'{pat[:26]:26} | {ship.group(0) if ship else "free/none"} | {t[:90]}')
run(f)
