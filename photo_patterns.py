"""Tone-aware pen paths for photo plotting (millimetre coordinates)."""
import math


def squiggle_paths(ink, width, height, spacing):
    """Alternating horizontal ribbons; darker samples pull each ribbon into waves."""
    if width <= 0 or height <= 0 or spacing <= 0:
        return []
    paths = []
    rows = max(1, int(math.ceil(height / spacing)))
    # Roughly three samples per smallest wave cycle, with a hard global ceiling.
    n = max(2, min(79000 // rows, int(math.ceil(width / max(.10, spacing / 12))) + 1))
    for row in range(rows):
        y0 = min(height, (row + .5) * spacing)
        path = []
        phase = 0.0
        for i in range(n):
            x = width * i / (n - 1)
            tone = ink(x, y0)
            # Integrate local frequency so adjacent samples join smoothly.
            phase += (width / (n - 1)) * math.tau * (.12 + 2.8 * tone) / spacing
            amp = min(spacing * .46, y0, height - y0) * tone
            y = max(0.0, min(height, y0 + amp * math.sin(phase)))
            path.append((x, y))
        if row % 2:
            path.reverse()
        paths.append(path)
    return paths


def spiral_paths(ink, width, height, spacing):
    """A single elliptical Archimedean spiral with tone-driven radial ripples."""
    if width <= 0 or height <= 0 or spacing <= 0:
        return []
    rx, ry = width / 2.0, height / 2.0
    # Turn spacing is set in physical units along the tighter ellipse axis.
    turns = max(1.0, min(500.0, min(width, height) / max(spacing, .15) / 2.0))
    samples = max(2, min(79000, int(math.ceil(turns * 2 * math.pi * max(width, height) / max(.3, spacing / 3))) + 1))
    pts = []
    phase = 0.0
    previous = (rx, ry)
    for i in range(samples):
        t = i / (samples - 1)
        angle = t * turns * math.tau
        # Elliptic radius grows linearly, fitting an oval inside the frame.
        base = t
        x0, y0 = rx + rx * base * math.cos(angle), ry + ry * base * math.sin(angle)
        tone = ink(x0, y0)
        # Tone controls high-frequency radial oscillation around the spiral.
        phase += math.dist(previous, (x0, y0)) * math.tau * (.15 + 2.8 * tone) / spacing
        previous = (x0, y0)
        ripple = spacing * .43 / min(rx, ry) * tone * math.sin(phase)
        rad = max(0.0, min(1.0, base + ripple))
        pts.append((rx + rx * rad * math.cos(angle), ry + ry * rad * math.sin(angle)))
    return [pts]


def _orient(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])


def _crosses(a, b, c, d):
    return _orient(a, b, c) * _orient(a, b, d) < 0 and _orient(c, d, a) * _orient(c, d, b) < 0


def tour_paths(ink, width, height, spacing, rng):
    """Seeded tone-weighted point tour, locally untangled with bounded 2-opt."""
    if width <= 0 or height <= 0 or spacing <= 0:
        return []
    target = min(8000, max(4, int(width * height / spacing ** 2 * 2)))
    nx = max(1, round(math.sqrt(target * width / height)))
    ny = max(1, round(target / nx))
    step_x, step_y = width / nx, height / ny
    pts = []
    fallback = None
    for gy in range(ny):
        for gx in range(nx):
            x, y = (gx + .5) * step_x, (gy + .5) * step_y
            tone = ink(x, y)
            if tone and (fallback is None or tone > fallback[0]):
                fallback = (tone, x, y)
            # Tone-weighted acceptance concentrates the tour in the shadows.
            if tone > 0 and rng.random() < tone ** 1.5:
                x += rng.uniform(-.4, .4) * step_x
                y += rng.uniform(-.4, .4) * step_y
                pts.append((x, y))
    if not pts and fallback is not None:
        pts.append((fallback[1], fallback[2]))
    if not pts:
        return []
    if len(pts) > 3500:
        # Deterministic seeded thinning; retain the original spatial order first.
        keep = sorted(rng.sample(range(len(pts)), 3500))
        pts = [pts[i] for i in keep]

    # Greedy nearest-neighbour tour. Squared distances avoid unnecessary roots.
    remaining = set(range(len(pts)))
    first = rng.randrange(len(pts))
    order = [first]
    remaining.remove(first)
    while remaining:
        x, y = pts[order[-1]]
        nxt = min(remaining, key=lambda j: (pts[j][0]-x)**2 + (pts[j][1]-y)**2)
        order.append(nxt)
        remaining.remove(nxt)
    path = [pts[i] for i in order]

    # A few sweeps over sampled edge pairs remove obvious crossings without
    # quadratic blow-up on dense inputs. Reversal preserves one continuous tour.
    n = len(path)
    if n >= 4:
        stride = max(1, n // 180)
        for _ in range(3):
            changed = False
            for i in range(0, n - 2, stride):
                j_end = min(n - 1, i + max(12, n // 5))
                for j in range(i + 2, j_end, stride):
                    if _crosses(path[i], path[i+1], path[j], path[j+1]):
                        before = math.dist(path[i], path[i+1]) + math.dist(path[j], path[j+1])
                        after = math.dist(path[i], path[j]) + math.dist(path[i+1], path[j+1])
                        if after < before:
                            path[i+1:j+1] = reversed(path[i+1:j+1])
                            changed = True
            if not changed:
                break
    return [path]
