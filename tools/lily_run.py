"""Lily sketch SVG -> relative J jog commands (lily_cmds.txt), with per-stroke pressure.

  python tools/lily_run.py [file.svg] [fit=150] [ang=0] [press=0] [run]

Pen-down height = writing height + press * data-p (bed up is -Z). LIFT 2 mm between strokes.
Every Z move is paired: the bed comes back down by exactly what it went up, so each stroke returns
to the same travel height. The one deliberate exception is the wear step (WEAR mm every WEAR_EVERY mm
drawn), which raises the writing height permanently, as before.
The SVG is looked up in the cwd, then next to this script. lily_cmds.txt is written to the cwd.
"""
import math, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIFT, WEAR_EVERY, WEAR = 2.0, 2000.0, 0.1
JOIN, SAME_PRESS = 2.0, .15   # join gaps under JOIN mm, only between strokes whose pressure differs by < SAME_PRESS
PATH_RE = re.compile(r'<path\b([^>]*)>')
ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
POINT_RE = re.compile(r'(-?[\d.]+),(-?[\d.]+)')


def resolve(name):
    for base in (os.getcwd(), HERE):
        candidate = os.path.join(base, name)
        if os.path.isfile(candidate):
            return candidate
    return name


def parse_svg(text):
    """[(points, pressure)] for every <path d=...>; pressure is data-p (0 when absent)."""
    out = []
    for tag in PATH_RE.findall(text):
        attrs = dict(ATTR_RE.findall(tag))
        pts = [(float(a), float(b)) for a, b in POINT_RE.findall(attrs.get("d", ""))]
        if len(pts) > 1:
            out.append((pts, float(attrs.get("data-p", 0))))
    return out


def chain(paths):
    """Nearest-next chaining; a gap under JOIN between strokes of similar pressure is drawn through."""
    if not paths:
        raise ValueError("no paths in SVG")
    paths = list(paths)
    (cur, cp), chains = paths.pop(0), []
    while paths:
        e = cur[-1]
        i = min(range(len(paths)), key=lambda k: min(math.dist(e, paths[k][0][0]), math.dist(e, paths[k][0][-1])))
        q, qp = paths.pop(i)
        if math.dist(e, q[-1]) < math.dist(e, q[0]):
            q = q[::-1]
        if math.dist(e, q[0]) < JOIN and abs(qp - cp) < SAME_PRESS:
            cur = cur + q
        else:
            chains.append((cur, cp)); cur, cp = q, qp
    chains.append((cur, cp))
    return chains


def build(svg_text, fit=150.0, ang=0.0, press=0.0):
    """Return (commands, info) for an SVG string. press = extra pen-down height (mm) at data-p 1."""
    if press < 0:
        raise ValueError("press must be 0 or more")
    chains = chain(parse_svg(svg_text))
    xs = [a for q, _ in chains for a, b in q]; ys = [b for q, _ in chains for a, b in q]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    a_rad = math.radians(ang)
    ca, sa = math.cos(a_rad), math.sin(a_rad)
    rot = lambda x, y: (x * ca - y * sa, x * sa + y * ca)
    rp = [rot(a - cx, b - cy) for q, _ in chains for a, b in q]
    k = fit / max(max(abs(a) for a, b in rp), max(abs(b) for a, b in rp)) / 2  # rotated drawing fits +-fit/2
    m = lambda p: (lambda x, y: (-x * k, -y * k))(*rot(p[0] - cx, p[1] - cy))  # svg right -> -X, svg down -> -Y

    cmds, pos, drawn, nextwear, wear = [], (0.0, 0.0), 0.0, WEAR_EVERY, 0.0
    def go(p, f):
        nonlocal pos
        dx, dy = p[0] - pos[0], p[1] - pos[1]
        if abs(dx) > 1e-3 or abs(dy) > 1e-3:
            cmds.append(f'J X{dx:.3f} Y{dy:.3f} F{f}'); pos = p
        return math.hypot(dx, dy)

    cmds.append(f'J Z-{5 - LIFT:.3f} F100')          # start (5 mm below writing) -> travel (LIFT below writing)
    for path, pr in chains:
        if len(path) < 2:
            continue
        rise = LIFT + press * pr                      # from travel up to this stroke's writing height
        go(m(path[0]), 600)
        cmds.append(f'J Z-{rise + wear:.3f} F100'); wear = 0.0
        for p in path[1:]:
            if math.dist(m(p), pos) < 0.6 and p is not path[-1]:
                continue
            drawn += go(m(p), 600)
        if drawn >= nextwear:
            wear = WEAR; nextwear += WEAR_EVERY
        cmds.append(f'J Z{rise:.3f} F100')            # paired return to travel height
    cmds += [f'J X{-pos[0]:.3f} Y{-pos[1]:.3f} F600', f'J Z{5 - LIFT:.3f} F100']
    info = dict(strokes=len(chains), moves=len(cmds), draw_cm=round(drawn / 10),
                size_mm=(round((max(xs) - min(xs)) * k), round((max(ys) - min(ys)) * k)))
    return cmds, info


def main(argv):
    opts = dict(a.split("=", 1) for a in argv[1:] if "=" in a)
    svg = next((a for a in argv[1:] if a.endswith(".svg")), "lily_scribble.svg")
    with open(resolve(svg), encoding="utf-8") as f:
        cmds, info = build(f.read(), float(opts.get("fit", 150)), float(opts.get("ang", 0)), float(opts.get("press", 0)))
    print(info["strokes"], "strokes", info["moves"], "moves", info["draw_cm"], "cm drawn", "size mm", info["size_mm"], file=sys.stderr)
    out = os.path.join(os.getcwd(), "lily_cmds.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(cmds))
    if "run" in argv[1:]:
        subprocess.run([sys.executable, os.path.join(HERE, "jog.py"), "@" + out])


if __name__ == "__main__":
    main(sys.argv)
