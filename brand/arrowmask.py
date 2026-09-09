"""Rasterise the placed flame at sketch resolution so the bow can be clipped to
its real silhouette rather than to a crude capsule around its axis."""
import re, pathlib, subprocess
src = pathlib.Path('v3-arrow-full.svg').read_text()
art = re.search(r'<g transform="translate\(0 10\)">.*?</g>\s*\n\s*<g font-family', src, re.S).group(0)
art = art[:art.rindex('<g font-family')].strip()
art = re.sub(r"filter=\"url\(#[^\"]+\)\"", "", art)
art = re.sub(r"fill=\"url\(#[^\"]+\)\"", "fill=\"#000\"", art)  # gradients are dead without defs
SC, TX, TY = 4.8561, 386.2, 219.6
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3413 2921" width="3413" height="2921">'
       f'<g transform="translate({TX} {TY}) scale({SC})" fill="#000" stroke="none">{art}</g></svg>')
pathlib.Path('arrow_only.svg').write_text(svg)
subprocess.run(['magick', '-background', 'none', 'arrow_only.svg', '-alpha', 'extract',
                '-threshold', '20%', 'arrow_mask.png'], check=True)
print('ok')
