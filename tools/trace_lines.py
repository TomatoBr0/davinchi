import sys, math, cv2, numpy as np
# Line-art tracer: dark ink -> 1px skeleton -> polylines (one pen line per inked line).
src, out = sys.argv[1], sys.argv[2]
g = cv2.imread(src, cv2.IMREAD_GRAYSCALE)
if 'wm' in sys.argv: g[825:900, 355:490] = int(np.median(g[780:820, 355:490]))                       # watermark
g = cv2.resize(g, None, fx=900 / max(g.shape), fy=900 / max(g.shape), interpolation=cv2.INTER_CUBIC)
g = cv2.GaussianBlur(g, (3, 3), 0)
ink = (cv2.adaptiveThreshold(g, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 18)).astype(np.uint8)
ink |= (g < cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0] * .6).astype(np.uint8)
ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
n, lab, st, _ = cv2.connectedComponentsWithStats(ink, 8)
ink = np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 25]).astype(np.uint8)
sk = cv2.ximgproc.thinning(ink * 255) > 0 if hasattr(cv2, 'ximgproc') else None
if sk is None:  # Zhang-Suen
    im = ink.copy()
    while True:
        changed = False
        for step in (0, 1):
            p = np.pad(im, 1)
            P = [p[0:-2, 1:-1], p[0:-2, 2:], p[1:-1, 2:], p[2:, 2:], p[2:, 1:-1], p[2:, 0:-2], p[1:-1, 0:-2], p[0:-2, 0:-2]]
            B = sum(P); A = sum(((P[i] == 0) & (P[(i + 1) % 8] == 1)).astype(int) for i in range(8))
            c = (P[0] * P[2] * P[4] == 0) & (P[2] * P[4] * P[6] == 0) if step == 0 else (P[0] * P[2] * P[6] == 0) & (P[0] * P[4] * P[6] == 0)
            rm = (im == 1) & (B >= 2) & (B <= 6) & (A == 1) & c
            if rm.any(): im[rm] = 0; changed = True
        if not changed: break
    sk = im > 0
sk = sk & (cv2.dilate(cv2.erode(ink, np.ones((7, 7), np.uint8)), np.ones((9, 9), np.uint8)) == 0)  # solid areas get hatch fill instead
pts = set(zip(*np.nonzero(sk)))
N = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
nb = lambda q: [(q[0] + a, q[1] + b) for a, b in N if (q[0] + a, q[1] + b) in pts]
paths = []
while pts:
    start = next((q for q in pts if len(nb(q)) == 1), next(iter(pts)))
    path = [start]; pts.discard(start)
    while True:
        c = nb(path[-1])
        if not c: break
        if len(path) > 1:
            d = (path[-1][0] - path[-2][0], path[-1][1] - path[-2][1])
            c.sort(key=lambda q: -((q[0] - path[-1][0]) * d[0] + (q[1] - path[-1][1]) * d[1]))
        path.append(c[0]); pts.discard(c[0])
    if len(path) >= 10: paths.append(path)
h, w = g.shape; s = 150.0 / max(h, w)
# solid black areas: the skeleton only leaves a spine, so fill them with dense hatching
solid = cv2.erode(ink, np.ones((7, 7), np.uint8))
if solid.any():
    import math
    a = math.radians(float(next((x[4:] for x in sys.argv if x.startswith('fan=')), 65)))
    gap = 0.7 / s  # 0.7 mm between fill lines
    dx, dy = math.cos(a), math.sin(a); nx, ny = -dy, dx
    for k in np.arange(-(h + w), h + w, gap):
        run = []
        for t in np.arange(-(h + w), h + w, 1.0):
            x, y = nx * k + dx * t + w / 2, ny * k + dy * t + h / 2
            if 0 <= x < w and 0 <= y < h and solid[int(y), int(x)]: run.append((int(y), int(x)))
            else:
                if len(run) > 6: paths.append(run)
                run = []
        if len(run) > 6: paths.append(run)
d = []
for p in paths:
    a = cv2.approxPolyDP(np.array([[q[1], q[0]] for q in p], np.float32), 0.7, False)[:, 0]
    d.append('M' + ' L'.join(f'{x * s:.3f},{y * s:.3f}' for x, y in a))
open(out, 'w').write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w*s:.1f} {h*s:.1f}"><g fill="none" stroke="#000" stroke-width=".3">'
                     + ''.join(f'<path d="{x}"/>' for x in d) + '</g></svg>')
print(len(paths), 'lines')
