"""Add one AliExpress item (by index in items.json) to cart, with variant + qty."""
import sys, json, asyncio
from lib import run

ITEMS = {i["n"]: i for i in json.load(open("/tmp/claude-1000/-home-prahladv/7bbbd975-0d9a-44f8-8d64-f9e4fe13d3c9/scratchpad/ali/items.json"))}

READ = """() => {
  const groups = [];
  document.querySelectorAll('div[class*="sku-item--property"]').forEach((g,gi) => {
    const title = ((g.querySelector('div[class*="title"]')||{}).innerText||'').trim();
    const els = [...g.querySelectorAll('div[class*="sku-item--image"], div[class*="sku-item--text"]')];
    groups.push({gi, title, opts: els.map((e,i)=>({i, text:(e.innerText||'').trim() || ((e.querySelector('img')||{}).alt||'').trim(),
      sel: /selected/i.test(e.className), dis: /disabled|soldOut/i.test(e.className)}))});
  });
  const cart = (document.querySelector('a[href*="shopcart"] span, [class*="cart-num"]')||{}).innerText||'';
  return {title: document.title, groups, cart};
}"""

def match(opts, want, avoid):
    cands = []
    for o in opts:
        t = o["text"].lower()
        if any(a.lower() in t for a in avoid): continue
        score = sum(1 for w in want if w.lower() in t)
        if score == len(want): cands.append((score, len(o["text"]), o))
    if not cands: return None
    cands.sort(key=lambda c: c[1])
    return cands[0][2]

async def one(page, n):
    it = ITEMS[n]
    res = {"n": n, "name": it["name"], "id": it["id"], "qty": it["qty"]}
    await page.goto(f"https://www.aliexpress.us/item/{it['id']}.html", wait_until="domcontentloaded")
    await page.wait_for_timeout(5500)
    st = await page.evaluate(READ)
    res["cart_before"] = st["cart"]
    want = list(it.get("variant", [])); avoid = it.get("avoid", [])
    chosen = []
    for g in st["groups"]:
        # tokens relevant to this group
        toks = [w for w in want if any(w.lower() in o["text"].lower() for o in g["opts"])]
        target = match(g["opts"], toks, avoid) if toks else None
        if target is None and len(g["opts"]) == 1:
            target = g["opts"][0]
        if target is None:
            cur = next((o for o in g["opts"] if o["sel"]), None)
            res.setdefault("defaulted", []).append(f'{g["title"]} <- opts {[o["text"] for o in g["opts"]]}')
        if target is None:
            res.setdefault("unresolved", []).append({"group": g["title"], "opts": [o["text"] for o in g["opts"]]})
            continue
        if not target["sel"]:
            el = page.locator('div[class*="sku-item--property"]').nth(g["gi"]).locator(
                'div[class*="sku-item--image"], div[class*="sku-item--text"]').nth(target["i"])
            await el.click()
            await page.wait_for_timeout(1200)
        chosen.append(f'{g["title"].split(":")[0]}={target["text"]}')
    res["chosen"] = chosen
    if res.get("unresolved"):
        res["status"] = "NEEDS_DECISION"; return res
    # verify selection stuck
    st2 = await page.evaluate(READ)
    res["selected_now"] = [ (g["title"]) for g in st2["groups"] ]
    # quantity
    if it["qty"] > 1:
        q = page.locator('input[class*="comet-v2-input"], div[class*="quantity"] input').first
        await q.click(); await q.press("Control+a"); await q.type(str(it["qty"])); await page.wait_for_timeout(800)
        res["qty_field"] = await q.input_value()
    # add to cart, confirmed by the cart XHR
    hits = []
    page.on("response", lambda r: hits.append(r.url) if ("aliexpress" in r.url and "cart" in r.url.split("?")[0].lower()) else None)
    btn = page.locator('button:has-text("Add to cart"), button[class*="addcart"]').first
    await btn.click()
    await page.wait_for_timeout(4500)
    res["cart_xhr"] = [h.split("?")[0] for h in hits][:3]
    res["status"] = "ADDED" if hits else "UNCONFIRMED"
    return res

async def do(page):
    out = open("/tmp/claude-1000/-home-prahladv/7bbbd975-0d9a-44f8-8d64-f9e4fe13d3c9/scratchpad/ali/results.jsonl", "a")
    for a in sys.argv[1:]:
        n = int(a)
        try:
            res = await one(page, n)
        except Exception as e:
            res = {"n": n, "name": ITEMS[n]["name"], "status": "ERROR", "err": f"{type(e).__name__}: {e}"[:300]}
        out.write(json.dumps(res) + "\n"); out.flush()
        print(n, res["status"], res.get("chosen"), res.get("err",""), flush=True)

run(do)
