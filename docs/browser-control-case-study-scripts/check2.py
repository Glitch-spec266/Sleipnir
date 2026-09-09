from lib import run
async def f(page):
    await page.goto("https://www.aliexpress.com/", wait_until="domcontentloaded")
    await page.wait_for_timeout(7000)
    print("URL:", page.url)
    t = await page.evaluate("document.body.innerText.slice(0,400)")
    print(t.replace("\n"," | ")[:400])
    ck = await page.context.cookies()
    names = sorted({c['name'] for c in ck})
    print("cookies:", len(ck), [n for n in names if n.lower() in ('aer_ucc','xman_us_f','x_lid','cna','intl_locale','aep_usuc_f','_bl_uid','xman_t','ali_apache_id','x_user')][:10])
run(f)
