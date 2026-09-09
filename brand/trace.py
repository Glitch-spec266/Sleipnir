"""Trace the ArcaFlame bow sketch into vector paths, one layer per ink colour.

Faithful vectorisation: the geometry comes from potrace over the user's own
strokes.  The only "clean up" is (a) closing the pen gaps inside a scribbled
stroke so it reads as one ribbon, (b) dropping specks, (c) potrace's own curve
fitting.  Nothing is redrawn by hand.
"""
import json, sys
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
import potrace

SRC = 'hi-1.png'
PAL = {'white': (255,255,255), 'dark': (68,12,88), 'violet': (225,146,253), 'blue': (81,213,251)}

# close  = pen-gap bridging radius (px @150dpi)
# speck  = drop connected blobs smaller than this many px
# hole   = fill enclosed holes smaller than this many px
TUNE = {
    'dark':   dict(close=5,  speck=1400, hole=5000),
    'violet': dict(close=9,  speck=1400, hole=16000),
    'blue':   dict(close=6,  speck=1400, hole=8000),
}

def disk(r):
    y, x = np.ogrid[-r:r+1, -r:r+1]
    return x*x + y*y <= r*r

def clean(mask, close, speck, hole):
    m = ndi.binary_closing(mask, disk(close))
    lab, n = ndi.label(m)
    if n:
        sizes = ndi.sum(m, lab, range(1, n+1))
        keep = np.isin(lab, np.nonzero(sizes >= speck)[0] + 1)
        m = keep
    inv, n = ndi.label(~m)
    if n:
        sizes = ndi.sum(~m, inv, range(1, n+1))
        # index 0-based -> label i+1; never fill the background component
        bg = inv[0, 0]
        small = [i+1 for i, s in enumerate(sizes) if s < hole and i+1 != bg]
        if small:
            m = m | np.isin(inv, small)
    return m

def to_paths(mask, alphamax=1.0, opttolerance=0.35):
    bmp = potrace.Bitmap(~mask)  # potracer treats LOW values as ink
    path = bmp.trace(turdsize=2, alphamax=alphamax, opttolerance=opttolerance)
    out = []
    for curve in path:
        s = curve.start_point
        d = [f'M{s.x:.1f} {s.y:.1f}']
        for seg in curve:
            e = seg.end_point
            if seg.is_corner:
                c = seg.c
                d.append(f'L{c.x:.1f} {c.y:.1f}L{e.x:.1f} {e.y:.1f}')
            else:
                c1, c2 = seg.c1, seg.c2
                d.append(f'C{c1.x:.1f} {c1.y:.1f} {c2.x:.1f} {c2.y:.1f} {e.x:.1f} {e.y:.1f}')
        d.append('Z')
        out.append(''.join(d))
    return out

im = Image.open(SRC).convert('RGB')
a = np.asarray(im).astype(np.float32)
names = list(PAL)
cols = np.array([PAL[n] for n in names], np.float32)
idx = ((a[:, :, None, :] - cols[None, None, :, :])**2).sum(-1).argmin(-1)

layers = {}
for i, n in enumerate(names):
    if n == 'white':
        continue
    m = clean(idx == i, **TUNE[n])
    layers[n] = to_paths(m)
    ys, xs = np.nonzero(m)
    print(f'{n}: {len(layers[n])} subpaths, bbox x {xs.min()}..{xs.max()} y {ys.min()}..{ys.max()}', file=sys.stderr)

json.dump({'size': im.size, 'layers': layers}, open('traced.json', 'w'))
print('wrote traced.json')
