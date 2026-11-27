"""Hand-sketch style: image -> SVG of loose edge lines + form-following hatching.

Each <path> carries data-p (0..1 pencil pressure) which tools/lily_run.py turns into bed height.
  python tools/sketch_style.py in.jpg out.svg [size=150] [loose=0.35] [passes=2] [hatch=1.0] [thr=0.45] [seed=1] [tune=1]

Tone: each hatch cell is budgeted with the ink it will actually lay down (edges already there are
subtracted, and a stroke's darkness follows its pressure), so the rendered darkness tracks the source.
Match (0..100): half shape correlation of blurred darkness, half tone agreement (1 - mean abs diff),
so over-dark hatching costs score. tune=1 tries a small grid of hatch/loose/thr and keeps the best.
"""
import itertools, math, random, sys
import cv2, numpy as np

DEFAULTS = dict(size=150.0, loose=.35, passes=2, hatch=1.0, thr=.45, seed=1)
TUNE_GRID = dict(hatch=(.8, 1.0, 1.25), loose=(.2, .35, .5), thr=(.35, .45, .55))
PEN_MM = .35            # pencil width used by the self-check (SVG draws .3 mm)
STROKE_MM = (4, 7)      # hatch stroke length range, mm
MEAN_STROKE_MM = sum(STROKE_MM) / 2


def _prepare(gray):
    g = cv2.resize(gray, None, fx=900 / max(gray.shape), fy=900 / max(gray.shape), interpolation=cv2.INTER_AREA)
    f = g.astype(np.float32) / 255
    bg = cv2.GaussianBlur(f, (0, 0), 25)           # remove paper shading / uneven light
    dark = np.clip((bg - f) / max(.05, float(np.percentile(bg - f, 99.5))), 0, 1)
    tone = cv2.GaussianBlur(dark, (0, 0), 4)       # smooth darkness for hatching
    # direction field: hatch runs along the form (perpendicular to the tone gradient)
    sm = cv2.GaussianBlur(f, (0, 0), 6)
    gx, gy = cv2.Sobel(sm, cv2.CV_32F, 1, 0, ksize=5), cv2.Sobel(sm, cv2.CV_32F, 0, 1, ksize=5)
    J = [cv2.GaussianBlur(a, (0, 0), 10) for a in (gx * gx, gx * gy, gy * gy)]
    ang = 0.5 * np.arctan2(2 * J[1], J[0] - J[2]) + math.pi / 2
    return dict(dark=dark, tone=tone, ang=ang, H=g.shape[0], W=g.shape[1])


def _thin(im):
    """Zhang-Suen thinning of a 0/1 uint8 image."""
    while True:
        changed = False
        for step in (0, 1):
            p = np.pad(im, 1)
            P = [p[0:-2, 1:-1], p[0:-2, 2:], p[1:-1, 2:], p[2:, 2:], p[2:, 1:-1], p[2:, 0:-2], p[1:-1, 0:-2], p[0:-2, 0:-2]]
            B = sum(P); A = sum(((P[i] == 0) & (P[(i + 1) % 8] == 1)).astype(int) for i in range(8))
            c = (P[0] * P[2] * P[4] == 0) & (P[2] * P[4] * P[6] == 0) if step == 0 else (P[0] * P[2] * P[6] == 0) & (P[0] * P[4] * P[6] == 0)
            rm = (im == 1) & (B >= 2) & (B <= 6) & (A == 1) & c
            if rm.any(): im[rm] = 0; changed = True
        if not changed: return im


def _centerlines(dark, thr):
    """Skeleton of the strong dark lines as ordered (row, col) polylines with mean darkness."""
    ink = (dark > thr).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink, 8)
    ink = np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 30]).astype(np.uint8)
    pts = set(zip(*np.nonzero(_thin(ink.copy()))))
    NB = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
    nb = lambda q: [(q[0] + a, q[1] + b) for a, b in NB if (q[0] + a, q[1] + b) in pts]
    lines = []
    while pts:
        s = next((q for q in pts if len(nb(q)) == 1), next(iter(pts)))
        pl = [s]; pts.discard(s)
        while (c := nb(pl[-1])):
            if len(pl) > 1:
                d = (pl[-1][0] - pl[-2][0], pl[-1][1] - pl[-2][1])
                c.sort(key=lambda q: -((q[0] - pl[-1][0]) * d[0] + (q[1] - pl[-1][1]) * d[1]))
            pl.append(c[0]); pts.discard(c[0])
        if len(pl) >= 12:
            lines.append((pl, float(np.mean([dark[q] for q in pl]))))
    return lines


def _edge_paths(lines, S, loose, passes, rng):
    """Each skeleton line drawn `passes` times with wobble; returns (points_px, pressure)."""
    out, wob = [], loose / S
    for pl, pr in lines:
        xy = cv2.approxPolyDP(np.array([[q[1], q[0]] for q in pl], np.float32), .8, False)[:, 0]
        for k in range(passes):
            ph, amp = rng.uniform(0, 6.3), wob * (0 if k == 0 else 1)
            L = len(xy); t0 = int(rng.uniform(0, .06) * L); t1 = L - int(rng.uniform(0, .06) * L)
            seg = [(x + amp * math.sin(ph + i * .35), y + amp * math.cos(ph * 1.3 + i * .3)) for i, (x, y) in enumerate(xy[t0:t1])]
            if len(seg) > 1:
                out.append((seg, min(1, .5 + .5 * pr) * (1 if k == 0 else .7)))
    return out


def _hatch_paths(P, S, hatch, edge_ink, rng):
    """Short strokes along the form, budgeted so their ink (plus the edges') matches the tone."""
    H, W, tone, ang = P["H"], P["W"], P["tone"], P["ang"]
    step = max(3, int(2.2 / S / hatch))
    cell_mm2 = (step * S) ** 2
    def stroke(x, y, a0, length):
        out = [(x, y)]; a = a0
        for _ in range(6):
            yi, xi = int(min(H - 1, max(0, out[-1][1]))), int(min(W - 1, max(0, out[-1][0])))
            a2 = ang[yi, xi] + (a0 - ang[int(y), int(x)])
            if math.cos(a2 - a) < 0: a2 += math.pi
            a = a2; out.append((out[-1][0] + math.cos(a) * length / 6, out[-1][1] + math.sin(a) * length / 6))
        return out
    out = []
    for layer, cut, rot in ((1, .12, 0), (2, .55, math.pi / 3)):
        for y in range(step // 2, H, step):
            for x in range(step // 2, W, step):
                jx, jy = x + rng.uniform(-step / 2, step / 2), y + rng.uniform(-step / 2, step / 2)
                iy, ix = int(min(H - 1, jy)), int(min(W - 1, jx))
                t = float(tone[iy, ix])
                if t < cut: continue
                pressure = .25 + .6 * t
                # ink one stroke lays down in this cell: pen intensity (.35 + .65 p) times its share of the cell
                per = (PEN_MM * MEAN_STROKE_MM / cell_mm2) * (.35 + .65 * pressure)
                # ink still missing here after the edges; layer 1 fills it, layer 2 cross-hatches what is left
                need = max(0., t - float(edge_ink[iy, ix]))
                p = min(1., need / per) if layer == 1 else min(1., max(0., need - per) / per)
                if rng.random() > p: continue
                a = ang[iy, ix] + rot + rng.uniform(-.15, .15)
                out.append((layer, stroke(min(W - 2, jx), min(H - 2, jy), a, rng.uniform(*STROKE_MM) / S), pressure))
    return out


def _render(P, S, lines, opts):
    rng = random.Random(opts["seed"])
    H, W = P["H"], P["W"]
    thick = max(1, int(round(PEN_MM / S)))
    edge_layer = np.zeros((H, W), np.float32)
    edges = _edge_paths(lines, S, opts["loose"], opts["passes"], rng)
    for seg, p in edges:
        cv2.polylines(edge_layer, [np.int32(np.round(seg))], False, float(.35 + .65 * p), thick, cv2.LINE_AA)
    edge_ink = cv2.GaussianBlur(edge_layer, (0, 0), 3)
    hatch = _hatch_paths(P, S, opts["hatch"], edge_ink, rng)
    layers = {1: np.zeros((H, W), np.float32), 2: np.zeros((H, W), np.float32)}
    for layer, seg, p in hatch:
        cv2.polylines(layers[layer], [np.int32(np.round(seg))], False, float(.35 + .65 * p), thick, cv2.LINE_AA)
    coverage = np.clip(edge_layer + layers[1] + layers[2], 0, 1)
    a = cv2.GaussianBlur(P["dark"], (0, 0), 3)
    b = cv2.GaussianBlur(coverage, (0, 0), 3)
    corr = 0. if a.std() < 1e-9 or b.std() < 1e-9 else float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
    tone_fit = 1 - float(np.mean(np.abs(a - b)))
    paths = [([(x * S, y * S) for x, y in seg], p) for seg, p in edges] + \
            [([(x * S, y * S) for x, y in seg], p) for _, seg, p in hatch]
    compare = np.hstack([255 * (1 - a), 255 * (1 - b)]).astype(np.uint8)
    return dict(paths=paths, match=50 * (max(0., corr) + tone_fit), compare=compare)


def _svg(paths, width_mm, height_mm):
    d = ''.join(f'<path data-p="{p:.2f}" d="M' + ' L'.join(f'{x:.3f},{y:.3f}' for x, y in seg) + '"/>' for seg, p in paths)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm:.1f}mm" height="{height_mm:.1f}mm" '
            f'viewBox="0 0 {width_mm:.1f} {height_mm:.1f}"><rect width="100%" height="100%" fill="white"/>'
            f'<g fill="none" stroke="#222" stroke-width=".3" stroke-linecap="round">{d}</g></svg>')


def sketch(gray, tune=False, **overrides):
    """Sketch a grayscale uint8 array. Returns paths (mm, pressure), svg, match %, settings, compare image.

    With tune=True, tries TUNE_GRID over hatch/loose/thr and keeps the best match.
    """
    opts = dict(DEFAULTS, **{k: v for k, v in overrides.items() if v is not None})
    P = _prepare(np.asarray(gray, np.uint8))
    S = opts["size"] / max(P["H"], P["W"])            # mm per pixel
    candidates = [dict(opts)]
    if tune:
        keys = list(TUNE_GRID)
        candidates = [dict(opts, **dict(zip(keys, values))) for values in itertools.product(*TUNE_GRID.values())]
    cache, best = {}, None
    for cand in candidates:
        if cand["thr"] not in cache:
            cache[cand["thr"]] = _centerlines(P["dark"], cand["thr"])
        result = _render(P, S, cache[cand["thr"]], cand)
        if best is None or result["match"] > best[0]["match"]:
            best = (result, cand)
    result, chosen = best
    settings = {k: chosen[k] for k in ("size", "loose", "passes", "hatch", "thr", "seed")}
    width_mm, height_mm = P["W"] * S, P["H"] * S
    return dict(paths=result["paths"], svg=_svg(result["paths"], width_mm, height_mm),
                match=result["match"], settings=settings, compare=result["compare"],
                width_mm=width_mm, height_mm=height_mm, stroke_count=len(result["paths"]),
                tried=len(candidates))


def _cli(argv):
    kw = dict(a.split('=', 1) for a in argv[3:] if '=' in a)
    options = dict(size=float(kw.get("size", DEFAULTS["size"])), loose=float(kw.get("loose", DEFAULTS["loose"])),
                   passes=int(kw.get("passes", DEFAULTS["passes"])), hatch=float(kw.get("hatch", DEFAULTS["hatch"])),
                   thr=float(kw.get("thr", DEFAULTS["thr"])), seed=int(kw.get("seed", DEFAULTS["seed"])))
    gray = cv2.imread(argv[1], cv2.IMREAD_GRAYSCALE)
    if gray is None:
        sys.exit(f"cannot read {argv[1]}")
    tune = kw.get("tune", "0") == "1"
    r = sketch(gray, tune=tune, **options)
    cv2.imwrite(argv[2].rsplit('.', 1)[0] + '_compare.png', r["compare"])
    open(argv[2], 'w').write(r["svg"])
    s = r["settings"]
    if tune:
        print(f'tuned over {r["tried"]} settings: hatch={s["hatch"]} loose={s["loose"]} thr={s["thr"]}')
    print(f'match {r["match"]:.0f}% (shape + tone, 100 = identical)')
    print(r["stroke_count"], 'strokes')


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    _cli(sys.argv)
