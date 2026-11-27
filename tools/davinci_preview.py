import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
# Plot davinci_cmds.txt as seen facing the printer: user-right = -X, back (+Y) = up.
x = y = z = 0.0; seg = [[(0, 0)]]; down = False
for c in open('davinci_cmds.txt').read().split('\n'):
    v = {w[0]: float(w[1:]) for w in c.split()[1:]}
    if 'Z' in v:
        z += v['Z']; down = z < -4.5
        seg.append([(-x, y)]); continue
    x += v.get('X', 0); y += v.get('Y', 0)
    if down: seg[-1].append((-x, y))
    else: seg.append([(-x, y)])
plt.figure(figsize=(6, 6)); plt.gca().set_aspect('equal')
plt.plot([-90, 90, 90, -90, -90], [-90, -90, 90, 90, -90], 'r--', lw=.8)
for s in seg:
    if len(s) > 1: plt.plot(*zip(*s), 'k', lw=.4)
plt.title('facing the printer, red = +-90 mm'); plt.savefig('davinci_preview.png', dpi=120)
