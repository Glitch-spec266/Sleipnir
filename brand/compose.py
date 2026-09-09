"""Lockup v2: clean bow geometry (shape.py) + the Wild Current v3 flame arrow.

The bow is no longer a trace of pen strokes.  shape.py takes the sketch's
silhouette, rounds the wobble off its contour and insets a constant violet
current; the string is three measured anchors drawn as clean lines.  The arrow
is lifted verbatim from ~/ArcaFlame Sigil.html and placed by a two-point fit.
"""
import json, re, pathlib

HERE = pathlib.Path(__file__).resolve().parent
S = json.load((HERE / 'shape.json').open())
DARK, CORE, ST = S['dark'], S['core'], S['string']
L, A, R = ST['left'], ST['apex'], ST['right']

# --- the v3 arrow, as extracted, minus its wordmark and slogan ---------------
src = (HERE / 'logo-directions/07-wild-current-v3-arrow.svg').read_text()
defs = re.search(r'<defs>.*?</defs>', src, re.S).group(0)
art = re.search(r'<g transform="translate\(0 10\)">.*?</g>\s*\n\s*<g font-family', src, re.S).group(0)
art = art[:art.rindex('<g font-family')].strip()

# two-point fit: v3 flame tip (300, 46) -> the sketch's arrow tip height,
# v3 flame base (300, 470) -> the string apex, so the arrow reads as nocked.
V_TIP_Y, V_BASE_Y, V_AXIS = 46, 470, 300
TIP_Y = 443
SC = (A[1] - TIP_Y) / (V_BASE_Y - V_TIP_Y)
TX = A[0] - V_AXIS * SC
TY = TIP_Y - V_TIP_Y * SC

# --- frame ------------------------------------------------------------------
BOX = dict(x0=418, x1=2994, y0=419, y1=A[1])
PAD = 90
OX, OY = PAD - BOX['x0'], PAD - BOX['y0']
MARK_W = BOX['x1'] - BOX['x0']
MARK_BOTTOM = PAD + (BOX['y1'] - BOX['y0'])
W = MARK_W + 2 * PAD
WORD, SLOG = 345, 70
WORD_BASE = MARK_BOTTOM + 430
SLOG_BASE = WORD_BASE + 165
H = SLOG_BASE + 100

STRING_SHEATH, STRING_CORE = 24, 13


def build(path, sheath, current, bg='#FFFFFF'):
    string = f'M{L[0]} {L[1]} L{A[0]} {A[1]} L{R[0]} {R[1]}'
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">
<title id="t">ArcaFlame</title>
<desc id="d">A hand-traced asymmetric lightning bow retains its hooked ends and inner fragments around a single flame arrow nocked on a connected violet string.</desc>
{defs}
<rect width="{W}" height="{H}" fill="{bg}"/>
<g transform="translate({OX} {OY})">
  <g fill="none" stroke-linecap="round" stroke-linejoin="round">
    <path d="{string}" stroke="{sheath}" stroke-width="{STRING_SHEATH}"/>
    <path d="{string}" stroke="{current}" stroke-width="{STRING_CORE}"/>
  </g>
  <path fill="{sheath}" fill-rule="evenodd" d="{' '.join(DARK)}"/>
  <path fill="{current}" fill-rule="evenodd" d="{' '.join(CORE)}"/>
  <g transform="translate({TX:.2f} {TY:.2f}) scale({SC:.4f})">{art}</g>
</g>
<g font-family="Inter, Avenir Next, ui-sans-serif, system-ui, sans-serif" font-size="{WORD}" font-weight="800" letter-spacing="{-4 * WORD / 76:.1f}">
  <text x="{W//2}" y="{WORD_BASE}" text-anchor="middle"><tspan fill="#30105F">Arca</tspan><tspan fill="#28BFF8">Flame</tspan></text>
</g>
<text x="{W//2}" y="{SLOG_BASE}" text-anchor="middle" fill="#574A69" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="{SLOG}" letter-spacing="{5 * SLOG / 16:.1f}">AIM THE SYSTEM</text>
</svg>'''
    (HERE / path).write_text(svg)


build('logo-directions/05-bow-lockup.svg', '#440C58', '#E192FD')
build('logo-directions/06-bow-lockup-brand.svg', '#211039', '#B46FFF')
print(f'scale {SC:.4f} tx {TX:.1f} ty {TY:.1f} viewBox {W}x{H} anchors {L} {A} {R}')
