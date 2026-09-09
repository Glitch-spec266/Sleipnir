from cartlib import run, open_cart, delete
PATS = ["Female Black", "WeMos D1 Mini", "960pcs-with box", "24Values-840pcs", "350pcs-box"]
async def f(page):
    for p in PATS:
        await open_cart(page)
        print(await delete(page, p), flush=True)
run(f)
