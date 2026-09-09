# ArcaFlame brand assets

Approved decisions live in `DECISIONS.md`. This file records how the logo files
are produced, so a later change re-runs the pipeline instead of re-deriving it.

## Files

| File | What it is |
|---|---|
| `logo-directions/01-ascendant.svg` | direction 1, not selected |
| `logo-directions/02-rift.svg` | direction 2, not selected |
| `logo-directions/03-sigil.svg` | direction 3 "Wild Current", selected |
| `logo-directions/04-bow-trace.svg` | literal potrace of the operator's bow sketch; kept as the record of what the sketch actually says |
| `logo-directions/05-bow-lockup.svg` | **the mark** — clean bow geometry, Wild Current v3 flame, wordmark, slogan |
| `logo-directions/06-bow-lockup-brand.svg` | 05 recoloured to the `DECISIONS.md` palette |
| `logo-directions/07-wild-current-v3-arrow.svg` | the v3 flame arrow on its own, extracted from `~/ArcaFlame Sigil.html` |
| `sketch-150dpi.png` | the operator's bow sketch, rendered from `Oversized Pages.pdf` at 150 dpi |

## Rebuilding the mark

The bow in 05/06 is **not** a trace of the pen strokes. The sketch supplies the
shape; the scripts supply the drawing:

- `shape.py` takes the sketch's silhouette, rounds the pen wobble off its
  contour, insets a constant violet current, and lifts the three string anchors.
- `arrowmask.py` rasterises the placed flame so the bow can be cut at its
  silhouette rather than continuing under its glow.
- `compose.py` assembles the lockup and places the flame by a two-point fit —
  flame tip to the sketch's arrow tip, flame base to the string apex.

```sh
uv run --with pillow --with numpy --with scipy --with potracer brand/shape.py
uv run brand/compose.py
```

`pillow`, `scipy` and `potracer` are build-time only. They are deliberately not
runtime dependencies — the repository's two-dependency rule (`pydantic`,
`httpx`) still holds.

### Knobs

`shape.py` reads them from the environment so variants can be compared without
editing the file:

| Name | Shipped | What it does |
|---|---|---|
| `SLIM` | 12 | px each long limb is narrowed by, per side. Endpoint guards and small near-arrow details receive less or no erosion. |
| `SHEATH` | 12 | px of dark sheath outside the violet current. Kept narrow so the current survives every meaningful segment. |
| `MARGIN` | 24 | clearance around the sketched blue arrow and its old pen outline. The replacement flame overlays the bow instead of deleting nearby details. |
| `DETAIL_SPECK` | 8000 | minimum area for ordinary components. Near-arrow details use one quarter of this threshold. |
| `JOIN_INSET` | 0.055 | fraction each clean string endpoint moves toward the nock, preserving the bow hook beyond a visibly connected junction. |

### Two traps worth keeping

- **`potracer` treats LOW values as ink.** A boolean mask where `True` means ink
  traces the *background*, and it fails silently — one enormous contour covering
  the whole canvas, no error. Pass `~mask`.
- **Take the string anchors before any clipping.** The flame is fitted to the
  string apex, so if a clip is allowed to move the apex, the arrow placement
  chases it and the fit drifts every time a margin changes.
