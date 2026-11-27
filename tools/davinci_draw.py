"""DaVinci drawing SVG -> relative J jog commands (davinci_cmds.txt), with per-stroke pressure.

  python tools/davinci_draw.py [file.svg] [fit=150] [ang=0] [press=0] [run]

Pen-down height = writing height + press * data-p (bed up is -Z). LIFT 2 mm between strokes.
Every Z move is paired: the bed comes back down by exactly what it went up, so each stroke returns
to the same travel height. The one deliberate exception is the wear step (WEAR mm every WEAR_EVERY mm
drawn), which raises the writing height permanently, as before.
The SVG is looked up in the cwd, then next to this script. davinci_cmds.txt is written to the cwd.
"""
import math, os, re, subprocess, sys
BOX = float(next((a[4:] for a in sys.argv if a.startswith('box=')), 175))  # usable square, mm
FEED = int(next((a[5:] for a in sys.argv if a.startswith('feed=')), 600))  # mm/min, firmware max 1500

HERE = os.path.dirname(os.path.abspath(__file__))
LIFT, WEAR_EVERY, WEAR = 2.0, 2000.0, 0.1
JOIN, SAME_PRESS = 6.0, 1.0   # join gaps under JOIN mm, only between strokes whose pressure differs by < SAME_PRESS
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
    # work from the middle outward: start at the stroke nearest the centre, and prefer central strokes next
    xs = [p[0] for q, _ in paths for p in q]; ys = [p[1] for q, _ in paths for p in q]
    c = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    rad = lambda q: min(math.dist(c, q[0]), math.dist(c, q[-1]))
    (cur, cp), chains = paths.pop(min(range(len(paths)), key=lambda k: rad(paths[k][0]))), []
    while paths:
        e = cur[-1]
        i = min(range(len(paths)), key=lambda k: min(math.dist(e, paths[k][0][0]), math.dist(e, paths[k][0][-1])) + .3 * rad(paths[k][0]))
        q, qp = paths.pop(i)
        if math.dist(e, q[-1]) < math.dist(e, q[0]):
            q = q[::-1]
        if math.dist(e, q[0]) < JOIN and abs(qp - cp) < SAME_PRESS:
            cur = cur + q
        else:
            chains.append((cur, cp)); cur, cp = q, qp
    chains.append((cur, cp))
    return chains


def build(svg_text, fit=150.0, ang=0.0, press=0.0, anchor='center', pen_down=False, wear_on=True):
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
    m0 = lambda p: (lambda x, y: (-x * k, -y * k))(*rot(p[0] - cx, p[1] - cy))  # svg right -> -X, svg down -> -Y
    # anchor: where the head starts. center, or a corner of the drawing (f/b = front/back, l/r = user's left/right)
    pts = [m0(p) for q, _ in chains for p in q]
    ox = oy = 0.0
    if anchor.startswith('sq'):  # head starts at a corner of the BOX mm work square; drawing is centred in it
        ox = BOX / 2 if 'r' in anchor else -BOX / 2    # head at the right corner -> square lies to the left (+X)
        oy = -BOX / 2 if 'b' in anchor else BOX / 2    # head at the back corner -> square lies toward the front (-Y)
    elif anchor != 'center':
        ox = -max(a for a, b in pts) if 'l' in anchor else -min(a for a, b in pts)   # +X is the user's left
        oy = -min(b for a, b in pts) if 'f' in anchor else -max(b for a, b in pts)   # +Y is back
    m = lambda p: (lambda x, y: (x + ox, y + oy))(*m0(p))

    cmds, pos, drawn, nextwear, wear = [], (0.0, 0.0), 0.0, WEAR_EVERY, 0.0
    def go(p, f):
        nonlocal pos
        dx, dy = p[0] - pos[0], p[1] - pos[1]
        if abs(dx) > 1e-3 or abs(dy) > 1e-3:
            cmds.append(f'J X{dx:.3f} Y{dy:.3f} F{f}'); pos = p
        return math.hypot(dx, dy)

    START_Z = 0.0 if pen_down else 5.0                # pen_down: the pen starts touching the paper
    cmds.append(f'J Z{LIFT - START_Z:.3f} F100')      # start -> travel (LIFT below writing)
    for path, pr in chains:
        if len(path) < 2:
            continue
        rise = LIFT + press * pr                      # from travel up to this stroke's writing height
        go(m(path[0]), FEED)
        cmds.append(f'J Z-{rise + wear:.3f} F100'); wear = 0.0
        for p in path[1:]:
            if math.dist(m(p), pos) < 0.6 and p is not path[-1]:
                continue
            drawn += go(m(p), FEED)
        if wear_on and drawn >= nextwear:
            wear = WEAR; nextwear += WEAR_EVERY
        cmds.append(f'J Z{rise:.3f} F100')            # paired return to travel height
    cmds += [f'J X{-pos[0]:.3f} Y{-pos[1]:.3f} F{FEED}', f'J Z{START_Z - LIFT:.3f} F100']  # back to the start spot and height
    travel = sum(math.hypot(*(float(w[1:]) for w in c.split()[1:3])) for c in cmds if ' X' in c)
    zmm = sum(abs(float(c.split()[1][1:])) for c in cmds if c.split()[1][0] == 'Z')
    # measured on the bear run: ~0.035 s overhead per command on top of pure travel time
    eta_min = round((travel / FEED + zmm / 100 + len(cmds) * .035 / 60), 1)
    info = dict(strokes=len(chains), moves=len(cmds), draw_cm=round(drawn / 10), eta_min=eta_min,
                size_mm=(round((max(xs) - min(xs)) * k), round((max(ys) - min(ys)) * k)))
    return cmds, info


def main(argv):
    opts = dict(a.split("=", 1) for a in argv[1:] if "=" in a)
    svg = next((a for a in argv[1:] if a.endswith(".svg")), None)
    if not svg:
        sys.exit("usage: davinci_draw.py drawing.svg [fit=150] [ang=0] [press=0] [feed=600] [anchor=center|fl|fr|bl|br] [start=down] [wear=0] [run]")
    with open(resolve(svg), encoding="utf-8") as f:
        cmds, info = build(f.read(), float(opts.get("fit", 150)), float(opts.get("ang", 0)), float(opts.get("press", 0)),
                           opts.get("anchor", "center"), opts.get("start") == "down", opts.get("wear", "1") != "0")
    print(info["strokes"], "strokes", info["moves"], "moves", info["draw_cm"], "cm drawn", "size mm", info["size_mm"], "ETA about", info["eta_min"], "min", file=sys.stderr)
    out = os.path.join(os.getcwd(), "davinci_cmds.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(cmds))
    if "run" in argv[1:]:
        subprocess.run([sys.executable, os.path.join(HERE, "davinci_jog.py"), "@" + out])


if __name__ == "__main__":
    main(sys.argv)
