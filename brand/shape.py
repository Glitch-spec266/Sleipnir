"""Rebuild the ArcaFlame bow as clean geometry derived from the sketch.

The sketch supplies the SHAPE; this supplies the drawing. Nothing here traces an
individual pen stroke: the outer contour is the sketch's own silhouette with the
pen wobble rounded off it, the violet current is a constant inset of that
contour, and the string is three measured anchors drawn as straight lines.

Tunables come from the environment so variants can be compared without editing:

    SLIM    px to narrow every limb by, per side   (0 = the sketch's own weight)
    SHEATH  px of dark sheath left outside the violet current
    MARGIN  px of clearance around the sketched arrow's own pen outline
    FLAME_MARGIN  px of clearance around the replacement flame's silhouette
    OUT     where to write the path data
"""
import os, json
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
import potrace

HERE = Path(__file__).resolve().parent
SRC = Path(os.environ.get('SRC', HERE / 'sketch-150dpi.png'))
SLIM = int(os.environ.get('SLIM', 12))
SHEATH = int(os.environ.get('SHEATH', 12))
MARGIN = int(os.environ.get('MARGIN', 24))
DETAIL_SPECK = int(os.environ.get('DETAIL_SPECK', 8_000))
JOIN_INSET = float(os.environ.get('JOIN_INSET', 0.055))
OUT = Path(os.environ.get('OUT', HERE / 'shape.json'))

PAL = [(255, 255, 255), (68, 12, 88), (225, 146, 253), (81, 213, 251)]


def disk(r):
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r


def drop_specks(m, area):
    lab, k = ndi.label(m)
    if not k:
        return m
    return np.isin(lab, np.nonzero(ndi.sum(m, lab, range(1, k + 1)) >= area)[0] + 1)


def fill_small(m, area):
    inv, k = ndi.label(~m)
    if not k:
        return m
    sizes = ndi.sum(~m, inv, range(1, k + 1))
    bg = inv[0, 0]
    small = [i + 1 for i, s in enumerate(sizes) if s < area and i + 1 != bg]
    return m | np.isin(inv, small) if small else m


def smooth(m, sigma):
    """Round the wobble off a boundary without moving it: blur, re-threshold."""
    return ndi.gaussian_filter(m.astype(np.float32), sigma) > 0.5


def corridor(shape, p0, p1, half):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float32)
    ax, ay, bx, by = float(p0[0]), float(p0[1]), float(p1[0]), float(p1[1])
    vx, vy = bx - ax, by - ay
    t = np.clip(((xx - ax) * vx + (yy - ay) * vy) / (vx * vx + vy * vy), 0, 1)
    return (xx - (ax + t * vx))**2 + (yy - (ay + t * vy))**2 <= half * half


def to_paths(mask, alphamax=1.334, opttolerance=0.9):
    out = []
    # potracer treats LOW values as ink, so the mask goes in inverted.
    for curve in potrace.Bitmap(~mask).trace(turdsize=8, alphamax=alphamax,
                                             opttolerance=opttolerance):
        s = curve.start_point
        d = [f'M{s.x:.0f} {s.y:.0f}']
        for seg in curve:
            e = seg.end_point
            if seg.is_corner:
                d.append(f'L{seg.c.x:.0f} {seg.c.y:.0f}L{e.x:.0f} {e.y:.0f}')
            else:
                d.append(f'C{seg.c1.x:.0f} {seg.c1.y:.0f} '
                         f'{seg.c2.x:.0f} {seg.c2.y:.0f} {e.x:.0f} {e.y:.0f}')
        out.append(''.join(d) + 'Z')
    return out


a = np.asarray(Image.open(SRC).convert('RGB')).astype(np.float32)
idx = ((a[:, :, None, :] - np.array(PAL, np.float32)[None, None])**2).sum(-1).argmin(-1)

# 1. the pen strokes become solid ribbons: gaps bridged, interiors filled, specks gone
solid = fill_small(drop_specks(ndi.binary_closing((idx == 1) | (idx == 2), disk(20)), 4000), 60000)

# 2. String anchors, taken BEFORE anything is clipped away — the arrow is fitted
#    to the apex, so the apex may not move when the arrow's footprint changes.
cols = np.array([(x, np.nonzero(solid[:, x])[0].max())
                 for x in range(solid.shape[1]) if solid[:, x].any()])
TRACE_LEFT = tuple(int(v) for v in cols[0])
APEX = tuple(int(v) for v in cols[cols[:, 1].argmax()])
TRACE_RIGHT = tuple(int(v) for v in cols[-1])

def toward(point, target, fraction):
    return tuple(int(round(a + (b - a) * fraction)) for a, b in zip(point, target))

# The extrema include the hand-drawn terminal hooks. The string joins slightly
# inside those hooks, so the hook remains visible beyond the connection instead
# of the clean string projecting past the bow.
LEFT = toward(TRACE_LEFT, APEX, JOIN_INSET)
RIGHT = toward(TRACE_RIGHT, APEX, JOIN_INSET)

# 3. Remove only the sketch's blue arrow and its immediately adjacent pen
#    outline.  The replacement flame is drawn later *over* the bow, so clipping
#    to its glow would wrongly delete the two inward-facing bow details that
#    make the sketch distinctive.
limbs = solid & ~ndi.binary_dilation(idx == 3, disk(MARGIN))

# 4. Drop the hand-drawn string while protecting the terminal hooks. The clean
#    string joins inside those hooks. Outside each new join, remove only the
#    narrow old-string corridor so no stray stroke projects past the bow.
strip = (corridor(solid.shape, LEFT, APEX, 80) | corridor(solid.shape, APEX, RIGHT, 80))
yy, xx = np.ogrid[:solid.shape[0], :solid.shape[1]]
terminal_guard = (((xx - TRACE_LEFT[0])**2 + (yy - TRACE_LEFT[1])**2 <= 220**2)
                  | ((xx - TRACE_RIGHT[0])**2 + (yy - TRACE_RIGHT[1])**2 <= 220**2))
outer_stubs = corridor(solid.shape, RIGHT, TRACE_RIGHT, 24)
limbs = limbs & ~(strip & ~terminal_guard) & ~outer_stubs
limbs = ndi.binary_closing(drop_specks(limbs, DETAIL_SPECK), disk(18))

# Preserve the small inward-facing lightning pieces beside the arrow. They are
# separate islands after the old arrow outline is removed, so a large generic
# speck threshold silently erased them in the previous export.
near_arrow = ((np.abs(xx - APEX[0]) <= 520) & (yy < APEX[1] - 520))
details = drop_specks(limbs & near_arrow, max(1200, DETAIL_SPECK // 4))
if SLIM:
    slimmed = ndi.binary_erosion(limbs, disk(SLIM))
    detail_slimmed = ndi.binary_erosion(details, disk(max(2, SLIM // 3)))
    limbs = slimmed | detail_slimmed | (limbs & terminal_guard)
    limbs = drop_specks(limbs, max(1200, DETAIL_SPECK // 4))

# 5. Clean contour, constant violet inset. A 12px sheath preserves a narrow
#    dark edge while keeping the bright current continuous through slender
#    details; the previous 34px inset deleted it from those segments entirely.
dark = drop_specks(smooth(limbs, 9), max(1200, DETAIL_SPECK // 4))
core = drop_specks(smooth(ndi.binary_erosion(dark, disk(SHEATH)), 5), 800)

json.dump({'size': [solid.shape[1], solid.shape[0]],
           'dark': to_paths(dark), 'core': to_paths(core),
           'string': {'left': list(LEFT), 'apex': list(APEX), 'right': list(RIGHT),
                      'trace_left': list(TRACE_LEFT), 'trace_right': list(TRACE_RIGHT)}},
          OUT.open('w'))
print(f'slim {SLIM} sheath {SHEATH} margin {MARGIN} | dark {dark.sum()} core {core.sum()} '
      f'| joins {LEFT} {APEX} {RIGHT} | trace ends {TRACE_LEFT} {TRACE_RIGHT}')
