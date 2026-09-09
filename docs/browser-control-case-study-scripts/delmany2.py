from cartlib import run, open_cart, delete
PATS = ["5PCS IRLZ44N", "10PCS IRLZ44N TO-220 IRLZ44 TO220"]
async def f(page):
    for p in PATS:
        await open_cart(page)
        print(await delete(page, p), flush=True)
run(f)
