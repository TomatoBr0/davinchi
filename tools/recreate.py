"""Recreate a sketch as closely as possible with one pencil.

Darkness is rebuilt from stroke density: each spot gets strokes packed just tight enough
(spacing = pencil width / darkness) to match how dark the original is there, and every
stroke follows the direction of the original's own lines at that spot. Light areas get
sparse thin strokes that fade out; solid blacks get packed strokes.
Self-check: renders the result and prints how close its darkness is to the original.

  python tools/recreate.py in.jpg out.svg [size=170] [pen=0.35] [gain=1.0] [seed=1]
"""
import sys, math, random, cv2, numpy as np

args = dict(a.split('=', 1) for a in sys.argv[3:] if '=' in a)
SIZE, PEN = float(args.get('size', 170)), float(args.get('pen', .35))
GAIN, rng = float(args.get('gain', 1.0)), random.Random(int(args.get('seed', 1)))

g = cv2.imread(sys.argv[1], cv2.IMREAD_GRAYSCALE).astype(np.float32)
if 'blank' in args:  # blank=x0,y0,x1,y1;... areas to leave empty (fractions of the image)
    h0, w0 = g.shape; keepmask = np.ones_like(g)
    for r in args['blank'].split(';'):
        x0, y0, x1, y1 = map(float, r.split(',')); keepmask[int(y0 * h0):int(y1 * h0), int(x0 * w0):int(x1 * w0)] = 0
else:
    keepmask = np.ones_like(g)
if 'crop' in args:  # crop=x0,y0,x1,y1 as fractions of the image
    x0, y0, x1, y1 = map(float, args['crop'].split(',')); h0, w0 = g.shape
    g = g[int(y0 * h0):int(y1 * h0), int(x0 * w0):int(x1 * w0)]; keepmask = keepmask[int(y0 * h0):int(y1 * h0), int(x0 * w0):int(x1 * w0)]
PENCIL = args.get('mode', 'pen') == 'pencil'  # pencil: light areas get many faint strokes you can smudge
ink_of = (lambda p: .2 + .8 * p) if PENCIL else (lambda p: .55 + .45 * p)   # how dark one stroke is at pressure p
sc = 900 / max(g.shape); g = cv2.resize(g, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA); keepmask = cv2.resize(keepmask, (g.shape[1], g.shape[0]), interpolation=cv2.INTER_NEAREST)
H, W = g.shape; S = SIZE / max(H, W); pw = PEN / S            # mm/px, pencil width in px
paper = cv2.GaussianBlur(cv2.dilate(g, np.ones((121, 121), np.uint8)), (0, 0), 40)  # local paper brightness (handles shading)
ink = np.percentile(g, 2)
D = np.clip((paper - g) / np.maximum(1, paper - ink) - .06, 0, 1) / .94 * keepmask  # 0 paper .. 1 solid ink
# filter: drop small isolated specks and stray marks away from the drawing (keeps every sizeable part)
blob = (cv2.GaussianBlur(D, (0, 0), 4) > .1).astype(np.uint8)
blob = cv2.morphologyEx(blob, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
n, lab, st, _ = cv2.connectedComponentsWithStats(blob, 8)
big = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= H * W * float(args.get('minpart', .002))]
D = D * cv2.dilate(np.isin(lab, big).astype(np.uint8), np.ones((9, 9), np.uint8))
if args.get('subject') == '1':  # keep only the main subject (largest dark shape), drop text and marks around it
    blob = (cv2.GaussianBlur(D, (0, 0), 6) > .15).astype(np.uint8)
    blob = cv2.morphologyEx(blob, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(blob, 8)
    if n > 1:
        keep = (lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
        keep = cv2.dilate(keep, np.ones((9, 9), np.uint8))
        D = D * keep
Ds = cv2.GaussianBlur(D, (0, 0), max(1.0, pw))                 # darkness as the pencil sees it

# stroke direction = along the original's lines (perpendicular to the brightness gradient)
gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
J = [cv2.GaussianBlur(a, (0, 0), 5) for a in (gx * gx, gx * gy, gy * gy)]
theta = 0.5 * np.arctan2(2 * J[1], J[0] - J[2]) + math.pi / 2
coh = np.sqrt((J[0] - J[2]) ** 2 + 4 * J[1] ** 2) / (J[0] + J[2] + 1e-6)  # 0 = no clear direction

def sep(x, y):  # spacing needed here to reproduce the darkness
    d = min(1.0, Ds[int(y), int(x)] * GAIN)
    if d <= .04: return None
    return pw * ink_of(d) / d if PENCIL else pw / d

CELL = 2.0; occ = {}                                           # spatial hash of placed points
def free(x, y, r):
    cx, cy = int(x / CELL), int(y / CELL); k = int(r / CELL) + 1
    for i in range(cx - k, cx + k + 1):
        for j in range(cy - k, cy + k + 1):
            for (px, py) in occ.get((i, j), ()):
                if (px - x) ** 2 + (py - y) ** 2 < r * r: return False
    return True
def mark(pts):
    for x, y in pts: occ.setdefault((int(x / CELL), int(y / CELL)), []).append((x, y))

def trace(x0, y0, sgn, maxlen, r0):
    out, x, y, a_prev = [], x0, y0, None
    for _ in range(int(maxlen)):
        if not (1 <= x < W - 1 and 1 <= y < H - 1): break
        r = sep(x, y)
        if r is None or not free(x, y, min(r, r0) * .6): break  # keep going until it really meets a neighbour
        a = theta[int(y), int(x)] if coh[int(y), int(x)] > .15 else (a_prev if a_prev is not None else math.radians(60))
        if a_prev is not None and math.cos(a - a_prev) < 0: a += math.pi
        if a_prev is None and sgn < 0: a += math.pi
        a_prev = a; out.append((x, y))
        x, y = x + math.cos(a), y + math.sin(a)
    return out

strokes = []
# 1) ink shapes thinner than a pencil sweep (eyelashes, outlines): fill them exactly with nested outlines
M = (D > float(args.get('solid', .55))).astype(np.uint8)
k = max(3, int(round(3 * pw)) | 1)
thin = M & (1 - cv2.morphologyEx(M, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))))
thin = cv2.dilate(thin, np.ones((3, 3), np.uint8)) & M
lay, ek = thin.copy(), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(1, int(round(pw))) * 2 + 1,) * 2)
while lay.any():
    for c in cv2.findContours(lay, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)[0]:
        if len(c) * S >= .8:
            pts = [(float(x), float(y)) for x, y in c[:, 0]]; pts.append(pts[0]); mark(pts); strokes.append((pts, 1.0))
    lay = cv2.erode(lay, ek)
# 2) shading: strokes along the original's lines, packed to match its darkness
for d_lo in (.6, .3, .12, .04):                                # darkest areas first, then fade out
    seeds = [(x + rng.random(), y + rng.random()) for y in range(1, H - 1, 2) for x in range(1, W - 1, 2)
             if d_lo <= Ds[y, x] * GAIN < (d_lo * 2 if d_lo < .6 else 9)]
    rng.shuffle(seeds)
    for x, y in seeds:
        r = sep(x, y)
        if r is None or not free(x, y, r): continue
        maxlen = rng.uniform(6, 16) / S                         # strokes ~6-16 mm like hand hatching
        b = trace(x, y, -1, maxlen / 2, r)[::-1]; f = trace(x, y, 1, maxlen / 2, r)
        pts = b + f[1:]
        if len(pts) * S < 1.0: continue
        mark(pts)
        p = float(np.mean([Ds[int(q[1]), int(q[0])] for q in pts]))
        strokes.append((pts, min(1.0, p * GAIN)))

# self-check: draw it like a pencil and compare darkness with the original
canvas = np.zeros((H, W), np.float32)
for pts, p in strokes:
    cv2.polylines(canvas, [np.int32(np.round(pts))], False, ink_of(p), max(1, int(round(pw))), cv2.LINE_AA)
a, b = cv2.GaussianBlur(D, (0, 0), 4), cv2.GaussianBlur(np.clip(canvas, 0, 1), (0, 0), 4)
err = float(np.mean(np.abs(a - b))); corr = float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
cv2.imwrite(sys.argv[2].rsplit('.', 1)[0] + '_compare.png', np.hstack([255 * (1 - D), 255 * (1 - np.clip(canvas, 0, 1))]).astype(np.uint8))
print(f'{len(strokes)} strokes, shape match {corr * 100:.0f}%, darkness off by {err * 100:.1f}% (gain {GAIN})')

d = []
for pts, p in strokes:
    pts = cv2.approxPolyDP(np.array(pts, np.float32), .6, False)[:, 0]
    d.append(f'<path data-p="{p:.2f}" d="M' + ' L'.join(f'{x * S:.3f},{y * S:.3f}' for x, y in pts) + '"/>')
open(sys.argv[2], 'w').write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W*S:.1f}mm" height="{H*S:.1f}mm" viewBox="0 0 {W*S:.1f} {H*S:.1f}">'
                             f'<rect width="100%" height="100%" fill="white"/><g fill="none" stroke="#222" stroke-width="{PEN}" stroke-linecap="round">{"".join(d)}</g></svg>')
