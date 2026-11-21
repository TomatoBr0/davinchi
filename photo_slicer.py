"""Convert a grayscale image into bounded pen paths without external packages."""
import math
import random


def slice_photo(payload):
    from app import num, render_svg
    from slicer import render_uno_gcode

    if not isinstance(payload, dict):
        raise ValueError("Expected an image object")
    width, height = payload.get("width"), payload.get("height")
    if type(width) is not int or type(height) is not int or not (2 <= width <= 320 and 2 <= height <= 320):
        raise ValueError("Image dimensions must be 2 to 320 pixels")
    pixels = payload.get("pixels")
    if not isinstance(pixels, list) or len(pixels) != width * height or any(type(p) is not int or not 0 <= p <= 255 for p in pixels):
        raise ValueError("Expected one grayscale byte per pixel")
    style = payload.get("style", "scribble")
    if style not in ("diagonal", "crosshatch", "scribble", "outlines", "stipple", "squiggle", "spiral", "tour"):
        raise ValueError("Unknown drawing style")
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
    tones = [max(0, min(1, ((1 - p / 255) - .5) * contrast + .5)) for p in pixels]
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

    if max(tones) <= threshold:
        raise ValueError("No drawable marks. Lower the threshold or use a darker image.")

    if style == "scribble":
        from photo_sketch import scribble_paths, edge_paths
        # Crisp feature contours anchor the looser shadow scribbles.
        for path in edge_paths(tones, width, height, draw_w, draw_h, threshold):
            add(path)
        for path in scribble_paths(tones, width, height, draw_w, draw_h, spacing, rng, threshold):
            add(path)
    elif style == "outlines":
        from photo_sketch import edge_paths
        for path in edge_paths(tones, width, height, draw_w, draw_h, threshold):
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
    if not strokes:
        raise ValueError("No drawable marks. Lower the threshold or use a darker image.")
    options = {"travel_feed_mm_min": 300, "write_feed_mm_min": 300}
    length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for s in strokes for a, b in zip(s, s[1:]))
    return {"svg": render_svg(strokes, page_w, page_h),
            "uno_gcode": render_uno_gcode(strokes, options),
            "stroke_count": len(strokes), "point_count": points,
            "draw_length_mm": round(length), "machine_ready": False}
