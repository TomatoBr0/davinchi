"""Convert a grayscale image into bounded pen paths without external packages."""
import math
import random


def auto_levels(pixels):
    """Stretch so the darkest ~1% maps to black and the paper (~99th percentile) to white."""
    ordered = sorted(pixels)
    lo = ordered[int(.01 * (len(ordered) - 1))]
    hi = ordered[int(.99 * (len(ordered) - 1))]
    if hi - lo < 8:  # blank or near-flat: stretching would only amplify noise
        return list(pixels)
    scale = 255 / (hi - lo)
    return [max(0, min(255, round((p - lo) * scale))) for p in pixels]


CLEANUP = {  # strength -> thresholds; "off" skips every cleanup filter below
    "low": dict(morph=True, min_area=3, loop_mm=5, loop_area=12, spur=1.0, isolated=.6),
    "med": dict(morph=True, min_area=4, loop_mm=8, loop_area=25, spur=2.0, isolated=1.0),
    "high": dict(morph=True, min_area=6, loop_mm=12, loop_area=50, spur=3.0, isolated=1.5),
    "off": None,
}


def _drop_hairpins(pts):
    """Remove vertices where the path folds back on itself (interior angle under 60 degrees)."""
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = out[-1], pts[i], pts[i + 1]
        u, v = (a[0] - b[0], a[1] - b[1]), (c[0] - b[0], c[1] - b[1])
        nu, nv = math.hypot(*u), math.hypot(*v)
        if nu and nv and (u[0] * v[0] + u[1] * v[1]) / (nu * nv) > .5:
            continue
        out.append(b)
    out.append(pts[-1])
    return out


def smooth_path(pts, step=.3, radius=3, passes=2):
    """Resample by arc length about every `step` mm, then moving-average; endpoints stay fixed.
    A moving average cannot overshoot the way a spline does on uneven spacing."""
    if len(pts) < 3:
        return pts
    out, carry = [pts[0]], 0.0
    for a, b in zip(pts, pts[1:]):
        seg = math.dist(a, b)
        d = step - carry
        while d <= seg:
            t = d / seg
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            d += step
        carry = seg - (d - step)
    out.append(pts[-1])
    for _ in range(passes):
        n = len(out)
        out = [out[0]] + [
            (sum(p[0] for p in out[max(0, i - radius):i + radius + 1]) / len(out[max(0, i - radius):i + radius + 1]),
             sum(p[1] for p in out[max(0, i - radius):i + radius + 1]) / len(out[max(0, i - radius):i + radius + 1]))
            for i in range(1, n - 1)] + [out[-1]]
    return out


def _length(pts):
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def _segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    d2 = dx * dx + dy * dy
    t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / d2)) if d2 else 0
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def _turn_ok(current, path, chord):
    """True when the chord continues both the stroke's heading and the candidate's heading (< 45 deg)."""
    def cos(u, v):
        n = math.hypot(*u) * math.hypot(*v)
        return (u[0] * v[0] + u[1] * v[1]) / n if n else 1
    ahead = (current[-1][0] - current[-2][0], current[-1][1] - current[-2][1])
    start = (path[1][0] - path[0][0], path[1][1] - path[0][1])
    return cos(ahead, chord) > .707 and cos(chord, start) > .707


def tidy_strokes(strokes, cfg=None, join=.3, join_far=1.5, min_len=.5, tolerance=.2):
    """Simplify, smooth, drop slivers/loops/spurs, then chain by nearest endpoint to cut travel."""
    from photo_sketch import simplify
    paths = []
    for stroke in strokes:
        pts = [(x, y) for x, y, _ in stroke]
        if len(pts) > 2:
            # Tight RDP keeps the shape; Catmull-Rom then fits a smooth curve through the kept points.
            pts = simplify(pts, .1 if cfg else tolerance)
            if cfg:
                pts = smooth_path(_drop_hairpins(pts))
        if len(pts) > 1 and _length(pts) < min_len:
            continue
        if cfg and len(pts) > 2 and math.dist(pts[0], pts[-1]) <= 1.0:
            # Nearly closed loop: tiny loops are shading noise, not pen lines.
            diag = math.hypot(max(x for x, _ in pts) - min(x for x, _ in pts),
                              max(y for _, y in pts) - min(y for _, y in pts))
            area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2
            if diag < cfg["loop_mm"] or area < cfg["loop_area"]:
                continue
        paths.append(pts)
    if cfg:
        # Prune short branches: a short stroke touching another stroke, or a short isolated one.
        segments = [list(zip(p, p[1:])) or [(p[0], p[0])] for p in paths]
        def touching(i, p):
            return any(_segment_distance(p, a, b) <= .5
                       for j, segs in enumerate(segments) if j != i for a, b in segs)
        kept = []
        for i, p in enumerate(paths):
            length = _length(p)
            if len(p) > 1 and length < max(cfg["spur"], cfg["isolated"]):
                attached = touching(i, p[0]) or touching(i, p[-1])
                if (attached and length < cfg["spur"]) or (not attached and length < cfg["isolated"]):
                    continue
            kept.append(p)
        paths = kept
    # ponytail: O(n^2) nearest-endpoint scan; add a grid index if stroke counts pass ~5k.
    out, current, tail = [], None, None
    while paths:
        if tail is None:
            gap, index, reverse = 0, 0, False
        else:
            gap, index, reverse = min(((math.dist(tail, end), i, rev)
                                       for i, p in enumerate(paths)
                                       for rev, end in ((False, p[0]), (True, p[-1]))),
                                      key=lambda c: c[0])
        path = paths.pop(index)
        if reverse:
            path = path[::-1]
        # Single-point strokes are stipple dots (a press each), so they never merge.
        mergeable = current is not None and len(path) > 1 and len(current) > 1
        chord = (path[0][0] - current[-1][0], path[0][1] - current[-1][1]) if mergeable else None
        # Always require a continuing heading, so a fragment never folds back on the line it joins.
        if mergeable and gap <= join_far and _turn_ok(current, path, chord):
            current.extend(path)
        else:
            if current is not None:
                out.append(current)
            current = list(path)
        tail = current[-1]
    if current is not None:
        out.append(current)
    return [[(x, y, .5) for x, y in s] for s in out]


def slice_photo(payload):
    from app import num, render_svg
    from slicer import render_uno_gcode

    if not isinstance(payload, dict):
        raise ValueError("Expected an image object")
    width, height = payload.get("width"), payload.get("height")
    if type(width) is not int or type(height) is not int or not (2 <= width <= 480 and 2 <= height <= 480):
        raise ValueError("Image dimensions must be 2 to 480 pixels")
    pixels = payload.get("pixels")
    if not isinstance(pixels, list) or len(pixels) != width * height or any(type(p) is not int or not 0 <= p <= 255 for p in pixels):
        raise ValueError("Expected one grayscale byte per pixel")
    style = payload.get("style", "scribble")
    if style not in ("diagonal", "crosshatch", "scribble", "outlines", "stipple", "squiggle", "spiral", "tour", "springs", "halftone", "boxes"):
        raise ValueError("Unknown drawing style")
    cleanup = payload.get("cleanup", "med")
    if cleanup not in CLEANUP:
        raise ValueError("Cleanup must be off, low, med or high")
    cfg = CLEANUP[cleanup]
    outline_mode = payload.get("outline_mode", "edge")
    if outline_mode not in ("centerline", "edge"):
        raise ValueError("Outline mode must be centerline or edge")
    page_w = num(payload.get("page_width_mm", 150), "Page width", 20, 300)
    page_h = num(payload.get("page_height_mm", 150), "Page height", 20, 300)
    spacing = num(payload.get("spacing_mm", 1.2), "Spacing", .5, 5)
    contrast = num(payload.get("contrast", 1.4), "Contrast", .3, 3)
    threshold = num(payload.get("threshold", .18), "Threshold", .02, .9)
    seed = payload.get("seed", 1)
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError("Seed must be a nonnegative integer")
    rng = random.Random(seed)
    scale = min((page_w - 10) / (width - 1), (page_h - 10) / (height - 1))
    draw_w, draw_h = (width - 1) * scale, (height - 1) * scale
    ox, oy = (page_w - draw_w) / 2, (page_h - draw_h) / 2
    strokes = []
    points = 0

    # A small separable blur suppresses pixel staircases while retaining edges.
    tones = [max(0, min(1, ((1 - p / 255) - .5) * contrast + .5)) for p in auto_levels(pixels)]
    horizontal = []
    for y in range(height):
        for x in range(width):
            horizontal.append((tones[y*width+max(0,x-1)] + 2*tones[y*width+x] + tones[y*width+min(width-1,x+1)]) / 4)
    tones = [(horizontal[max(0,y-1)*width+x] + 2*horizontal[y*width+x] + horizontal[min(height-1,y+1)*width+x]) / 4
             for y in range(height) for x in range(width)]

    def ink(x, y):
        px = min(width - 1, max(0, x / scale))
        py = min(height - 1, max(0, y / scale))
        ix, iy = int(px), int(py)
        tx, ty = px - ix, py - iy
        jx, jy = min(width - 1, ix + 1), min(height - 1, iy + 1)
        top = tones[iy*width+ix]*(1-tx) + tones[iy*width+jx]*tx
        bottom = tones[jy*width+ix]*(1-tx) + tones[jy*width+jx]*tx
        return top*(1-ty) + bottom*ty

    def add(path):
        nonlocal points
        if not path:
            return
        points += len(path)
        if len(strokes) >= 20000 or points > 150000:
            raise ValueError("Drawing is too dense. Increase spacing or reduce page size.")
        strokes.append([(ox + min(draw_w, max(0, x)), oy + min(draw_h, max(0, y)), .5) for x, y in path])

    def outline_layer():
        from photo_sketch import edge_paths, centerline_paths
        if outline_mode == "edge":
            return edge_paths(tones, width, height, draw_w, draw_h, threshold,
                              min_area=cfg["min_area"] if cfg else 0, morph=bool(cfg))
        return centerline_paths(tones, width, height, draw_w, draw_h, threshold, morph=bool(cfg))

    if max(tones) <= threshold:
        raise ValueError("No drawable marks. Lower the threshold or use a darker image.")

    if style == "scribble":
        from photo_sketch import scribble_paths
        # Crisp feature contours anchor the looser shadow scribbles.
        for path in outline_layer():
            add(path)
        for path in scribble_paths(tones, width, height, draw_w, draw_h, spacing, rng, threshold):
            add(path)
    elif style == "outlines":
        for path in outline_layer():
            add(path)
    elif style in ("squiggle", "spiral", "tour"):
        from photo_patterns import squiggle_paths, spiral_paths, tour_paths
        if style == "tour":
            paths = tour_paths(ink, draw_w, draw_h, spacing, rng)
        elif style == "spiral":
            paths = spiral_paths(ink, draw_w, draw_h, spacing)
        else:
            paths = squiggle_paths(ink, draw_w, draw_h, spacing)
        for path in paths:
            add(path)
    elif style in ("springs", "halftone", "boxes"):
        from photo_plotterfun import plotterfun_paths
        for path in plotterfun_paths(style, ink, draw_w, draw_h, spacing, rng, threshold):
            add(path)
    elif style in ("diagonal", "crosshatch"):
        # Walk parallel scanlines. Shadow levels select extra hatch families.
        angles = (45, -45, 0) if style == "crosshatch" else (45,)
        step = min(.4, spacing / 2)
        for family, angle in enumerate(angles):
            a = math.radians(angle)
            dx, dy = math.cos(a), math.sin(a)
            nx, ny = -dy, dx
            corners = ((0, 0), (draw_w, 0), (0, draw_h), (draw_w, draw_h))
            vmin = min(x * nx + y * ny for x, y in corners)
            vmax = max(x * nx + y * ny for x, y in corners)
            umin = min(x * dx + y * dy for x, y in corners)
            umax = max(x * dx + y * dy for x, y in corners)
            rows = math.ceil((vmax - vmin) / spacing) + 1
            for row in range(rows):
                v = vmin + row * spacing
                path = []
                count = math.ceil((umax - umin) / step) + 1
                order = range(count) if row % 2 == 0 else range(count - 1, -1, -1)
                for i in order:
                    u = umin + i * step
                    x, y = u * dx + v * nx, u * dy + v * ny
                    active = False
                    if 0 <= x <= draw_w and 0 <= y <= draw_h:
                        tone = ink(x, y)
                        # Ordered line dithering preserves tone in one family.
                        level = (row % 5 + .5) / 5
                        cutoff = threshold + family * .30
                        active = tone > cutoff and (style == "crosshatch" or tone >= level)
                    if active:
                        path.append((x, y))
                    else:
                        add(path)
                        path = []
                add(path)
    else:
        # Independent cells prevent long pen-down bridges across white regions.
        for row in range(math.ceil(draw_h / spacing)):
            columns = range(math.ceil(draw_w / spacing))
            if row % 2:
                columns = reversed(columns)
            for col in columns:
                x, y = (col + .5) * spacing, (row + .5) * spacing
                if x > draw_w or y > draw_h:
                    continue
                tone = ink(x, y)
                if tone <= threshold:
                    continue
                if rng.random() < tone * tone:
                    x = min(draw_w, max(0, x + rng.uniform(-.42, .42) * spacing))
                    y = min(draw_h, max(0, y + rng.uniform(-.42, .42) * spacing))
                    add([(x, y)])
    # Loop/spur/smoothing filters target traced outlines; halftone dots and other marks are kept as drawn.
    strokes = tidy_strokes(strokes, cfg if style in ("outlines", "scribble") else None)
    if not strokes:
        raise ValueError("No drawable marks. Lower the threshold or use a darker image.")
    options = {"travel_feed_mm_min": 300, "write_feed_mm_min": 300}
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for s in strokes for a, b in zip(s, s[1:]))
    return {"svg": render_svg(strokes, page_w, page_h),
            "uno_gcode": render_uno_gcode(strokes, options),
            "stroke_count": len(strokes), "point_count": sum(len(s) for s in strokes),
            "draw_length_mm": round(length), "machine_ready": False}
