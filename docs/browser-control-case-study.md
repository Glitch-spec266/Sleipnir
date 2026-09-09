# Case study: driving AliExpress with Sleipnir's browser capability

**Date:** 2026-09-06
**Task:** add a 40-line electronics parts order to a live AliExpress cart, each line
on a specific SKU variant, without a human touching the browser.
**Result:** 41 lines added, 3 pre-existing lines untouched, 44 lines in cart,
list subtotal ~$86.51.

This is a record of what `sleipnir.capabilities.browser` can actually do against a
hostile, JavaScript-heavy, bot-averse commercial site — not a demo page.

## Why this task is a real test

AliExpress is a worst case for browser automation:

- Product pages are client-rendered; nothing useful exists in the initial HTML.
- SKU option elements use hashed CSS class suffixes (`sku-item--text--hYfAukP`)
  that differ between listings and change over time.
- Variant availability is dynamic — selecting a variant can *remove* the
  Add-to-cart button entirely if that SKU is out of stock.
- Quantity is capped per line at promotional prices, and the cap is expressed
  only as a `disabled` class on a `<div>`, not as a message.
- Cart rows are virtualised; only the first four exist in the DOM until scrolled.
- The whole flow requires an authenticated session that must survive across
  dozens of separate process invocations.

## The capability being exercised

`src/sleipnir/capabilities/browser.py` provides:

- A **headed Chrome for Testing**, launched **detached** (`start_new_session=True`)
  with a **persistent profile** at `~/.sleipnir/browser-profile`.
- A fixed CDP endpoint on port **9333**, so any later process attaches to the
  *same* browser rather than getting a fresh one.
- `ensure_browser()` — idempotent start; `stop_browser()` — real kill via
  `~/.sleipnir/browser.pid`, because closing a CDP connection does not close
  the browser.

Every script in `browser-control-case-study-scripts/` is ~30 lines and starts
with the same four lines:

```python
sys.path.insert(0, "/home/prahladv/Projects/sleipnir/src")
from sleipnir.capabilities.browser import CDP_ENDPOINT, ensure_browser
await ensure_browser()
browser = await pw.chromium.connect_over_cdp(CDP_ENDPOINT)
```

The persistent profile is what makes the task possible at all: the operator
signed in **once**, by hand, and ~30 subsequent Python processes over ~40 minutes
all inherited that session.

## Method

Four small scripts, each doing one job:

| Script | Job |
|---|---|
| `probe4.py` | Dump a listing's SKU groups and options as JSON |
| `add.py` | Match variant tokens, click, verify, set quantity, add to cart |
| `search.py` | Run a search and return `(id, title, price, rating, orders)` rows |
| `final.py` / `vcheck.py` | Scroll the virtualised cart and audit every line |

`add.py` is the interesting one. Its loop per item:

1. Navigate to `/item/<id>.html`, settle 5.5 s.
2. Read every SKU group: title, option texts, `selected` / `disabled` state.
3. For each group, take only the requested tokens that actually appear in *that*
   group's options, and require **all** of them to match a single option
   (with an `avoid` list to reject near-misses like `MAX4466` or `MG90S`).
4. Click the matching option.
5. **Re-read the DOM** and confirm the group's title now names the chosen option.
   This is the check that matters: a click that lands but does not select is the
   failure mode that silently ships the wrong part.
6. Set quantity, click Add to cart, and confirm via the cart XHR firing.

### Three rules learned the hard way

**Never accept a default on a multi-option group.** The first pass silently
accepted AliExpress's default on a second, unrequested group and ordered a
**5-pack** of PIR sensors instead of one. `add.py` now refuses: any group with
more than one option and no matching token returns `NEEDS_DECISION` with the
full option list, and a human picks. Nine items came back this way and all nine
were genuinely ambiguous — pack sizes (`1PCS/5PCS/10PCS`), colour, plug type.

**Read and click through the same selector.** The initial selector matched a
*container* holding all options, so `opts[i]` and the click target `nth(i)`
disagreed. Item 6 was ordered as `10pcs 3mm Receiver` when the log said
`10pcs 5mm Emitter` — the log was reporting the option it *read*, not the one it
*clicked*. Both now resolve through
`div[class*="sku-item--image"], div[class*="sku-item--text"]`.

**Verify at the destination, not the source.** Per-item "ADDED" is not proof.
The full cart audit found three defects that every per-item log had reported as
success: the wrong IR LED, a duplicate PIR line, and two quantities that
silently reverted to 1.

### Things only a real browser finds

- **An unbuyable variant.** On listing `2251832474204589`, selecting `MAX9814`
  removed both Buy-now and Add-to-cart from the DOM — the variant exists in the
  picker but cannot be purchased. Only visible by selecting it and re-reading the
  button set. Resolved by sourcing a replacement listing via `search.py`.
- **A hard quantity cap.** Four lines refused to go above 1. The evidence was a
  single class on a `<div>`:
  `comet-v2-input-number-btn-increase comet-v2-input-number-btn-disabled`.
  Typing `2` into the field appeared to work and reverted on reload. Resolved by
  switching to a 5-pack variant for the servo and a second seller for the cable.

## Outcome

| Metric | Value |
|---|---|
| Add-to-cart attempts | 55 |
| Confirmed added | 44 |
| Returned `NEEDS_DECISION` (correctly) | 9 |
| Errors (both transient/structural, both resolved) | 2 |
| Final cart lines | 44 (3 pre-existing + 41 new) |
| Wrong-variant lines shipped to the cart | 0 after audit |
| Human interventions | 1 sign-in, 2 either/or decisions |

Manual clicks avoided: roughly 200 (navigate, select 1–3 swatches, add, verify,
per item).

## Reproducing

```bash
cd docs/browser-control-case-study-scripts
~/Projects/sleipnir/.venv/bin/python probe4.py <item_id>   # inspect variants
~/Projects/sleipnir/.venv/bin/python add.py 1 2 3          # add by items.json index
~/Projects/sleipnir/.venv/bin/python final.py              # audit the cart
```

`items.json` is the order; `results.jsonl` is the per-attempt log;
`final_cart.json` is the verified end state.

## Honest limitations

- Timing is fixed sleeps, not network-idle waits. One item timed out on a slow
  load and needed a retry.
- The hashed-class selectors will break when AliExpress redeploys its frontend.
  `probe4.py` exists to re-derive them in one command when that happens.
- Nothing here bypasses a CAPTCHA or a login. It drives a session a human
  established, which is the design intent of the capability.
- Checkout is deliberately not automated. The cart is left for a human to review
  and pay.

## Addendum — second session, 2026-09-06

A later session reported two "hard blocks": *the cart only exposes ~20 of 40
lines* and *product-page adds silently fail*. Neither was real. Both were one bug.

**The browser window was 296 px tall.** `innerHeight` was 296, so the cart's
lazy-loader never mounted more than 10 rows, and any row past the tenth was
genuinely unreachable — exactly the symptom reported. The fix is three CDP calls:

```python
s = await ctx.new_cdp_session(page)
wid = (await s.send("Browser.getWindowForTarget"))["windowId"]
await s.send("Browser.setWindowBounds", {"windowId": wid,
    "bounds": {"windowState": "normal", "width": 1600, "height": 1200}})
```

`innerHeight` went 296 → 885 and all 40 rows became reachable. Sleipnir's
launcher takes no window-size flags, so window geometry is a CDP concern; this
belongs in any future scripted flow as a precondition, not a debugging step.

Two lessons generalise:

- **"Not in the DOM" is not "not in the cart."** Two lines reported as deleted by
  the previous session (`Male Black` headers, `micro usb/1m`) were present the
  whole time — they had simply never mounted. `locate()` in `cartlib.py` now
  scrolls until a row mounts before concluding anything about it, and every
  membership claim in this document is the output of that function, not of a
  single-viewport read.
- **A verified refusal beats a confident guess.** `add.py` returned
  `NEEDS_DECISION` on a MOSFET listing whose default variant was `IRFZ34N` — a
  different part than the requested `IRLZ44N`. The default would have shipped
  silently.

**Shipping is invisible to a per-item flow.** A $0.78 IRLZ44N 5-pack carried a
**$59.41** shipping fee, visible only on the cart line, never on the listing card.
Comparing three sellers found the same part at $2.26 shipped free. `shipscan.py`
now reports per-line shipping, which turned out to dominate the order total far
more than any item-price optimisation: $45.99 of shipping against $165.61 of goods.

## Addendum 2 — re-sourcing for shipping, 2026-09-06

Item price is the wrong optimisation target on AliExpress. Shipping is charged
per seller, is invisible on search result cards, and is not always visible on the
listing page either — a $0.78 MOSFET carried $59.41 of it. On a 40-line order
spread across ~30 sellers, shipping reached $45.99 against $165.61 of goods.

`shipprobe.py` reads price, shipping, rating, order count and the full SKU option
tree off a listing in one pass, so candidates can be rejected *before* being added
to the cart. That inverted the workflow: search → probe → add only the winner,
instead of add → inspect → delete.

Six lines were re-sourced to free-shipping sellers, each verified twice — once on
the listing, then again on the cart line, because the two can disagree:

| Part | Was | Now |
|---|---|---|
| DS3231 RTC | $1.89 + $14.13 | $3.43, free |
| USB-C + micro-USB cables (3 lines) | $1.99 + $9.78 ×2 | 2-pack + 1, free |
| RC522 RFID | $1.74 + $5.10 | $1.96, free |
| ESP32 DevKit CP2102 | $5.32 + $4.01 | $4.79, free |
| 4×4 keypad | $1.78 + $3.19 | $1.66, free |

Result: shipping $45.99 → **$0.00**, total $211.40 → $177.99, while adding two
items back.

Two findings worth keeping:

- **A cheaper listing can ship dearer.** The first ESP32 replacement was $0.99
  against $5.32 but carried $8.62 shipping — worse all-in than the line it would
  have replaced. Probing before adding is what caught it.
- **Shipping cost can encode a product difference.** The DS3231's $14.13 was the
  lithium cell; battery-bearing modules attract special handling. The naive fix —
  switch to the free-shipping module — silently drops the battery. A
  with-battery seller shipping free existed, and only a variant-level read
  found it.

**A cart line can disappear on its own.** Two lines marked "Only 1 left" (a USB
power meter and a 9V adapter) were absent on a later read, deleted by no one in
this session. Every delete this tool performs prints the row text it removed,
which is what made it provable that neither was ours. Both were re-added. Treat
the cart as a remote system that mutates independently, and re-verify membership
rather than tracking it locally.
