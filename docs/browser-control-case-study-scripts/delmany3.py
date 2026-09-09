from cartlib import run, open_cart, delete
PATS = ["TZT Precision DS3231", "1PCS RFID module RC522 mini Kits",
        "Matrix Switch Keyboard Keypad Array Module ABS",
        "type-c/1m", "micro usb/1m", "1Pcs/1m",
        "CP2102 ESP32 Development Board 30Pin/38Pin"]
async def f(page):
    for p in PATS:
        await open_cart(page)
        print(await delete(page, p), flush=True)
run(f)
