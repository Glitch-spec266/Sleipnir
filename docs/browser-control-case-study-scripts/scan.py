from cartlib import run, open_cart, scan
async def f(page):
    await open_cart(page)
    rows = await scan(page)
    print("ROWS", len(rows))
    tot = 0
    for i, r in enumerate(rows):
        try: tot += float(r["price"].replace("$","")) * int(r["qty"])
        except: pass
        print(f'{i:2} x{r["qty"]} {r["price"]:>7} {r["name"][:56]:56} | {r["all"][:0]}')
    print("SUBTOTAL(list) ~$%.2f" % tot)
run(f)
