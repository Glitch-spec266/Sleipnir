# ArcaFlame brand decisions

This file records approved rebrand decisions so the identity can be applied consistently across the repository.

## Working thesis

**Contained voltage:** a near-black lightning bow stores tension, a violet string makes that tension visible, and a cold-blue flame arrow releases it upward. The product should feel controlled, fast, and formidable—not medieval or ornamental.

## Checkpoints

1. Logo direction — **03 selected**; refined as **Wild Current**.
2. Logo refinement and responsive mark system — refinement awaiting approval.
3. Core color and terminal-safe palette — pending.
4. Typography and ASCII wordmark — pending.
5. CLI information architecture and chrome — pending.
6. Motion, splash, and interaction behavior — pending.
7. Repository-wide naming, copy, package, command, paths, and docs migration — pending.
8. Accessibility, regression, and final visual QA — pending.

## Fixed input from the brief

- Product name: **ArcaFlame**.
- Meaning: bow with fire.
- Bow: jagged lightning construction, mostly near-black with dark-purple structure.
- String: thin purple, visibly pulled downward.
- Arrow: nocked and pointing upward, rendered as original cold-blue flame geometry with dark/light blue accents.
- Wordmark color split: **Arca** in dark purple; **Flame** in bright blue.
- Environment direction: light blue field with dark purple/near-black typography and controls.

## Logo refinement 01

- Direction 03 is the selected base.
- Replace the heavy symmetrical bow mass with one thin, consistently weighted lightning channel. Its left and right curves are unrelated rather than mirrored, with most of the silhouette extending through the right limb; asymmetry comes from composition, not uneven stroke weight.
- Give both bow and string a dark-purple sheath with a narrow bright-violet inner current.
- Wrap the arrow shaft in closed, tapered blue flame tongues—never stroked lines—held close to the arrow and layered behind/in front to show the wrap.
- Preserve one calm vertical axis—the arrow—against the irregular surrounding energy.

### Research translated into the mark

- NOAA describes lightning leaders as irregular paths. Transfer: a single off-axis channel mixing loose curvature with selective abrupt bends; no detached decorative branches. Source: <https://www.nssl.noaa.gov/education/svrwx101/lightning/types/>
- NASA flame-vortex research describes spiral flame-edge dynamics. Transfer: a narrow, uneven flame path that alternates behind and in front of the arrow shaft. Source: <https://ntrs.nasa.gov/citations/20050205869>
- The Fuga reference contributes concentrated ignition, sharp flame taper, and extreme contrast only; no character, pose, panel composition, or distinctive franchise asset is reproduced.

## Bow-trace transfer repair

- `04-bow-trace.svg` is the geometry source of truth for the hooked bow terminals and the small inward-facing fragments beside the arrow.
- The clean string connects 5.5% inward from each traced extremum so both hooks remain visible beyond a real junction instead of leaving the string floating.
- The original right-side string stub is removed independently; the left terminal remains protected because its hook overlaps the traced string corridor.
- The dark-purple sheath is reduced from 34px to 12px, keeping the bright-violet current present through slender bow segments.
- Near-arrow components use a lower cleanup threshold and lighter slimming so meaningful pieces survive export.
