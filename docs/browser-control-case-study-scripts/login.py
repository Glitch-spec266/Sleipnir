from lib import run
async def f(page):
    if "aliexpress" not in page.url:
        await page.goto("https://www.aliexpress.us/", wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
    t = await page.evaluate("document.body.innerText")
    print("URL:", page.url)
    print("signin_present:", "Sign in" in t or "Sign In" in t)
    ck = {c['name'] for c in await page.context.cookies()}
    print("login_cookies:", sorted(n for n in ck if n in ('x_lid','xman_us_t','_m_h5_tk','ali_apache_track','aeu_cid','intl_common_forever','x_user','ali_apache_id')))
run(f)
