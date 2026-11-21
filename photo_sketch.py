"""Tone-guided pen sketches and connected edge tracing, using bounded paths."""
import math


def simplify(path, tolerance):
    """Iterative Douglas-Peucker simplification in millimeters."""
    if len(path) < 3:
        return path
    keep = {0, len(path) - 1}
    pending = [(0, len(path) - 1)]
    while pending:
        first, last = pending.pop()
        ax, ay = path[first]
        bx, by = path[last]
        dx, dy = bx - ax, by - ay
        denominator = dx * dx + dy * dy
        greatest, index = tolerance * tolerance, None
        for i in range(first + 1, last):
            px, py = path[i]
            ratio = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / denominator)) if denominator else 0
            distance = (px - ax - ratio * dx) ** 2 + (py - ay - ratio * dy) ** 2
            if distance > greatest:
                greatest, index = distance, i
        if index is not None:
            keep.add(index)
            pending.extend(((first, index), (index, last)))
    return [path[i] for i in sorted(keep)]


def scribble_paths(tones, width, height, draw_w, draw_h, spacing, rng, threshold):
    """Choose overlapping curved strokes against a diminishing darkness map."""
    sx, sy = draw_w / (width - 1), draw_h / (height - 1)
    residual = tones.copy()
    pen_radius = max(.35, min(sx, sy) * .7)
    # Ink demand scales with physical size and detail, with a bounded work budget.
    distance_budget = min(50000, sum(tones) * sx * sy / (spacing * .22))
    distance = 0.0
    segment_count = 0

    def sample(values, x, y):
        ix = min(width - 1, max(0, round(x / sx)))
        iy = min(height - 1, max(0, round(y / sy)))
        return values[iy * width + ix]

    def start_point():
        # Stratified random restarts find undrawn features without scanning
        # the whole raster at each stroke.
        candidates = rng.sample(range(len(residual)), min(350, len(residual)))
        index = max(candidates, key=residual.__getitem__)
        if residual[index] <= max(.03, threshold * .3):
            return None
        return (index % width * sx, index // width * sy)

    def erase(path):
        for a, b in zip(path, path[1:]):
            steps = max(1, math.ceil(math.dist(a, b) / (min(sx, sy) * .65)))
            for i in range(steps + 1):
                x = a[0] + (b[0] - a[0]) * i / steps
                y = a[1] + (b[1] - a[1]) * i / steps
                cx, cy = round(x / sx), round(y / sy)
                rx, ry = max(1, math.ceil(pen_radius / sx)), max(1, math.ceil(pen_radius / sy))
                for iy in range(max(0, cy - ry), min(height, cy + ry + 1)):
                    for ix in range(max(0, cx - rx), min(width, cx + rx + 1)):
                        d = math.hypot(ix * sx - x, iy * sy - y)
                        if d <= pen_radius:
                            index = iy * width + ix
                            residual[index] = max(-.3, residual[index] - .10 * (1 - .65 * d / pen_radius))

    while distance < distance_budget and segment_count < 14000:
        start = start_point()
        if start is None:
            break
        x, y = start
        heading = rng.uniform(-math.pi, math.pi)
        path = [(x, y)]
        for _ in range(110):
            # Try forward curves and wider turns. Shadows draw the line back
            # over itself until enough ink has been deposited.
            length = rng.uniform(1.1, 2.5) * spacing
            best_score, best_curve, best_heading = -1, None, heading
            for candidate in range(14):
                turn = (-1.5 + 3 * candidate / 13) + rng.uniform(-.12, .12)
                if candidate == 0:
                    turn = rng.uniform(-2.7, 2.7)
                curve = []
                cx, cy = x, y
                darkness, original, valid = 0.0, 0.0, True
                for step in range(1, 6):
                    angle = heading + turn * (step - .5) / 5
                    cx += math.cos(angle) * length / 5
                    cy += math.sin(angle) * length / 5
                    if not (0 <= cx <= draw_w and 0 <= cy <= draw_h):
                        valid = False
                        break
                    value = sample(tones, cx, cy)
                    if value < threshold * .45:
                        valid = False
                        break
                    darkness += sample(residual, cx, cy)
                    original += value
                    curve.append((cx, cy))
                if not valid:
                    continue
                # Following equal-tone contours retains facial boundaries.
                variation = abs(sample(tones, x, y) - original / 5)
                score = darkness / 5 - .11 * variation - .018 * abs(turn)
                score += rng.uniform(-.012, .012)
                if score > best_score:
                    best_score, best_curve, best_heading = score, curve, heading + turn
            if best_curve is None or best_score < .025:
                break
            erase([(x, y)] + best_curve)
            path.extend(best_curve)
            x, y = best_curve[-1]
            heading = best_heading
            distance += length
            segment_count += 1
            if distance >= distance_budget or segment_count >= 14000:
                break
        if len(path) > 2:
            yield simplify(path, .045)
        else:
            # A tiny isolated island cannot accommodate an arc.
            ix, iy = round(x / sx), round(y / sy)
            residual[iy * width + ix] = 0
            segment_count += 1


def edge_paths(tones, width, height, draw_w, draw_h, threshold):
    """Trace thinned local gradient edges into polylines."""
    sx, sy = draw_w / (width - 1), draw_h / (height - 1)
    gradient = [0.0] * len(tones)
    angles = [0.0] * len(tones)
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            i = y * width + x
            gx = (tones[i + 1] - tones[i - 1]) * .5
            gy = (tones[i + width] - tones[i - width]) * .5
            gradient[i] = math.hypot(gx, gy)
            angles[i] = math.atan2(gy, gx)
    edges = set()
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            i = y * width + x
            magnitude = gradient[i]
            if magnitude < threshold * .4:
                continue
            angle = round(angles[i] / (math.pi / 4)) % 4
            offset = (1, width + 1, width, width - 1)[angle]
            if magnitude >= gradient[i - offset] and magnitude >= gradient[i + offset]:
                edges.add(i)
    neighbors = lambda i: [j for j in (i-width-1, i-width, i-width+1, i-1, i+1, i+width-1, i+width, i+width+1)
                           if j in edges and abs(j % width - i % width) <= 1]
    # Endpoints first, then closed loops. Consume pixels to avoid repeated edges.
    starts = sorted(edges, key=lambda i: (len(neighbors(i)) != 1, i))
    for start in starts:
        if start not in edges:
            continue
        current, previous = start, None
        path = []
        while current in edges:
            path.append((current % width * sx, current // width * sy))
            edges.remove(current)
            choices = neighbors(current)
            if not choices:
                break
            if previous is None:
                next_pixel = min(choices)
            else:
                dx, dy = current % width - previous % width, current // width - previous // width
                next_pixel = max(choices, key=lambda j: dx * (j % width - current % width) + dy * (j // width - current // width))
            previous, current = current, next_pixel
        if len(path) >= 4:
            yield simplify(path, .12)
