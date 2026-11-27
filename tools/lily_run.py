import re, sys, math, subprocess
# Lily scribble -> relative J moves, centred on the current head position.
# Starts with bed 5 mm below writing height. +X = user's left, +Y = back.
LIFT, WEAR_EVERY, WEAR = 2.0, 2000.0, 0.1
t = open('lily_scribble.svg').read().split('<g', 1)[1]
paths = [[(float(a), float(b)) for a, b in re.findall(r'([\d.]+),([\d.]+)', d)]
         for d in re.findall(r'd="([^"]+)"', t)]
paths = [p for p in paths if len(p) > 1]
# chain: nearest-next path (either direction); gaps < JOIN mm are drawn through, no lift
JOIN, chains, cur = 3.0, [], paths.pop(0)
while paths:
    e = cur[-1]
    d = lambda q: min(math.dist(e, q[0]), math.dist(e, q[-1]))
    i = min(range(len(paths)), key=lambda k: d(paths[k])); q = paths.pop(i)
    if math.dist(e, q[-1]) < math.dist(e, q[0]): q = q[::-1]
    if math.dist(e, q[0]) < JOIN: cur += q
    else: chains.append(cur); cur = q
chains.append(cur); paths = chains
LIFT = 1.0
cx, cy = (35.117 + 117.073) / 2, (10.685 + 127.633) / 2
m = lambda p: (-(p[0] - cx), -(p[1] - cy))  # svg right -> -X, svg down -> -Y
cmds, pos, drawn, nextwear, lift = [], (0.0, 0.0), 0.0, WEAR_EVERY, 0.0
def go(p, f):
    global pos
    dx, dy = p[0] - pos[0], p[1] - pos[1]
    if abs(dx) > 1e-3 or abs(dy) > 1e-3:
        cmds.append(f'J X{dx:.3f} Y{dy:.3f} F{f}'); pos = p
    return math.hypot(dx, dy)
cmds.append(f'J Z-{5-LIFT} F100')  # travel height = LIFT below writing
for path in paths:
    if len(path) < 2: continue
    go(m(path[0]), 1200)
    cmds.append(f'J Z-{LIFT + lift:.3f} F100'); lift = 0.0
    for p in path[1:]:
        if math.dist(m(p), pos) < 0.6 and p is not path[-1]: continue
        drawn += go(m(p), 600)
    if drawn >= nextwear:
        lift = WEAR; nextwear += WEAR_EVERY
    cmds.append(f'J Z{LIFT:.3f} F100')
cmds += [f'J X{-pos[0]:.3f} Y{-pos[1]:.3f} F1200', f'J Z{5-LIFT} F100']
print(len(paths), 'paths', len(cmds), 'moves', round(drawn / 10), 'cm drawn', file=sys.stderr)
if 'run' in sys.argv:
    open('lily_cmds.txt', 'w').write('\n'.join(cmds))
    subprocess.run([sys.executable, 'jog.py', '@lily_cmds.txt'])
