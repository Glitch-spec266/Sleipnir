import re
from cartlib import run, open_cart, scan
async def f(page):
    await open_cart(page)
    rows = await scan(page)
    ship = []
    tot = 0.0
    for r in rows:
        m = re.search(r"Shipping Fee: \$([0-9.,]+)", r["all"])
        if m:
            v = float(m.group(1).replace(",", "")); tot += v
            ship.append((v, r["price"], r["name"][:52]))
    ship.sort(reverse=True)
    print("ROWS", len(rows), "| lines with shipping:", len(ship), "| shipping sum $%.2f" % tot)
    for v, p, n in ship: print(f"  ${v:6.2f} ship | item {p:>7} | {n}")
run(f)
