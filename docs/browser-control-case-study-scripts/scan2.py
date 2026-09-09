from cartlib import run, open_cart, scan
async def f(page):
    await open_cart(page)
    rows = await scan(page)
    print("ROWS", len(rows))
    for i,r in enumerate(rows):
        if any(k in r["name"] for k in ("40 Pin","Micro USB Cable","Usb A To Micro","GPS","IRLZ","Ceramic","TO-92","Diode","Electrolytic","WeMos","ESP32-C3")):
            print(i, r["price"], "||", r["all"][:190])
run(f)
