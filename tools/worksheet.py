"""Fill a paper worksheet with the pen plotter, one phone photo per paper placement.

Usage:
  python tools/worksheet.py photo.jpg answers.json [--out-dir DIR] [--start-mm X Y] [--dark 110]
  python tools/davinci_jog.py @DIR/cmds.txt        (runs the job; you do this, not this script)

answers.json: [{"x": 20, "y": 30, "text": "NAME: ALEX", "size_mm": 5}, ...]
  {"region": "rule-3", "text": "...", "size_mm": 5} lays text into a ruled line or blank box
  (ids in DIR/regions.png); uses your handwriting from data/handwriting when available.
  x, y: left end of the text baseline in worksheet mm. Origin = top-left corner of the
  worksheet as you read it, y grows downward. size_mm = cap height (default 5).

Writes DIR/rectified.png (top-down virtual page, 4 px/mm), DIR/preview.png and
DIR/cmds.txt (J moves for davinci_jog.py). Machine frame: +X = user's left, +Y = away from user.
With the worksheet top edge pointing away from you, page x -> machine -X and page y -> machine -Y.
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calibrate_from_photo import order_quad  # reuse the corner ordering
import hand_layout as hl  # blank areas, text into regions

HAND_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "handwriting")

PAGE_W, PAGE_H = 215.9, 279.4  # US Letter, mm
LIMIT = 88.0                   # usable travel: +-LIMIT mm from the head start, each axis
PX = 4                         # rectified pixels per mm
LIFT = 2.0                     # pen-down = Z-2 from travel height (same as davinci_draw.py)
TRAVEL_Z = -3.0                # travel height, measured from the bottom stop (z=0)

# Single-stroke font. Glyph box is 3 wide x 5 high units; advance 4 units. Each glyph is a
# list of polylines (pen lifts between them). Lowercase is drawn as uppercase.
GLYPHS = {
    "0": [[(0, 0), (3, 0), (3, 5), (0, 5), (0, 0)]],
    "1": [[(0.5, 4), (1.5, 5), (1.5, 0)], [(0.5, 0), (2.5, 0)]],
    "2": [[(0, 4), (1, 5), (2, 5), (3, 4), (3, 3), (0, 0), (3, 0)]],
    "3": [[(0, 5), (3, 5), (1.5, 3), (3, 2), (3, 1), (2, 0), (0, 0)]],
    "4": [[(2, 0), (2, 5), (0, 2), (3, 2)]],
    "5": [[(3, 5), (0, 5), (0, 3), (2, 3), (3, 2), (3, 1), (2, 0), (0, 0)]],
    "6": [[(3, 5), (1, 5), (0, 4), (0, 1), (1, 0), (2, 0), (3, 1), (3, 2), (2, 3), (0, 3)]],
    "7": [[(0, 5), (3, 5), (1, 0)]],
    "8": [[(1, 2.5), (0, 3.75), (1, 5), (2, 5), (3, 3.75), (2, 2.5), (1, 2.5), (0, 1.25),
           (1, 0), (2, 0), (3, 1.25), (2, 2.5)]],
    "9": [[(0, 1), (1, 0), (2, 0), (3, 1), (3, 4), (2, 5), (1, 5), (0, 4), (0, 3), (1, 2), (3, 2)]],
    "A": [[(0, 0), (0, 4), (1.5, 5), (3, 4), (3, 0)], [(0, 2.5), (3, 2.5)]],
    "B": [[(0, 0), (0, 5), (2, 5), (3, 4), (2, 3), (0, 3)], [(2, 3), (3, 2), (3, 1), (2, 0), (0, 0)]],
    "C": [[(3, 4), (2, 5), (1, 5), (0, 4), (0, 1), (1, 0), (2, 0), (3, 1)]],
    "D": [[(0, 0), (0, 5), (2, 5), (3, 4), (3, 1), (2, 0), (0, 0)]],
    "E": [[(3, 5), (0, 5), (0, 0), (3, 0)], [(0, 2.5), (2, 2.5)]],
    "F": [[(3, 5), (0, 5), (0, 0)], [(0, 2.5), (2, 2.5)]],
    "G": [[(3, 4), (2, 5), (1, 5), (0, 4), (0, 1), (1, 0), (2, 0), (3, 1), (3, 2), (2, 2)]],
    "H": [[(0, 0), (0, 5)], [(3, 0), (3, 5)], [(0, 2.5), (3, 2.5)]],
    "I": [[(0, 5), (3, 5)], [(1.5, 5), (1.5, 0)], [(0, 0), (3, 0)]],
    "J": [[(3, 5), (3, 1), (2, 0), (1, 0), (0, 1)]],
    "K": [[(0, 0), (0, 5)], [(3, 5), (0, 2)], [(1, 3), (3, 0)]],
    "L": [[(0, 5), (0, 0), (3, 0)]],
    "M": [[(0, 0), (0, 5), (1.5, 3), (3, 5), (3, 0)]],
    "N": [[(0, 0), (0, 5), (3, 0), (3, 5)]],
    "O": [[(0, 1), (1, 0), (2, 0), (3, 1), (3, 4), (2, 5), (1, 5), (0, 4), (0, 1)]],
    "P": [[(0, 0), (0, 5), (2, 5), (3, 4), (3, 3), (2, 2), (0, 2)]],
    "Q": [[(0, 1), (1, 0), (2, 0), (3, 1), (3, 4), (2, 5), (1, 5), (0, 4), (0, 1)], [(2, 1), (3, 0)]],
    "R": [[(0, 0), (0, 5), (2, 5), (3, 4), (3, 3), (2, 2), (0, 2)], [(1, 2), (3, 0)]],
    "S": [[(3, 4), (2, 5), (1, 5), (0, 4), (0, 3), (1, 2.5), (2, 2), (3, 1), (2, 0), (1, 0), (0, 1)]],
    "T": [[(0, 5), (3, 5)], [(1.5, 5), (1.5, 0)]],
    "U": [[(0, 5), (0, 1), (1, 0), (2, 0), (3, 1), (3, 5)]],
    "V": [[(0, 5), (1.5, 0), (3, 5)]],
    "W": [[(0, 5), (0.75, 0), (1.5, 3), (2.25, 0), (3, 5)]],
    "X": [[(0, 5), (3, 0)], [(0, 0), (3, 5)]],
    "Y": [[(0, 5), (1.5, 2.5), (3, 5)], [(1.5, 2.5), (1.5, 0)]],
    "Z": [[(0, 5), (3, 5), (0, 0), (3, 0)]],
    " ": [],
    ".": [[(1.5, 0), (1.5, 0.3)]],
    ",": [[(1.5, 0.5), (1.2, -0.8)]],
    "-": [[(0.5, 2.5), (2.5, 2.5)]],
    "_": [[(0, 0), (3, 0)]],
    ":": [[(1.5, 1), (1.5, 1.3)], [(1.5, 3.7), (1.5, 4)]],
    "/": [[(0, 0), (3, 5)]],
    "?": [[(0, 4), (1, 5), (2, 5), (3, 4), (2, 3), (1.5, 2), (1.5, 1.3)], [(1.5, 0), (1.5, 0.3)]],
    "+": [[(0, 2.5), (3, 2.5)], [(1.5, 1), (1.5, 4)]],
    "=": [[(0, 1.8), (3, 1.8)], [(0, 3.2), (3, 3.2)]],
    "(": [[(2.5, 5), (1, 4), (1, 1), (2.5, 0)]],
    ")": [[(0.5, 5), (2, 4), (2, 1), (0.5, 0)]],
}


def text_strokes(text, x, y, size_mm):
    """Polylines in worksheet mm (y down) for text whose first baseline starts at (x, y)."""
    s = size_mm / 5.0
    out = []
    for li, line in enumerate(text.split("\n")):
        base = y + li * 1.4 * size_mm
        for ci, ch in enumerate(line.upper()):
            if ch not in GLYPHS:
                raise ValueError(f"no glyph for {ch!r} (supported: A-Z 0-9 and . , - _ : / ? + = ( ))")
            ox = x + ci * 4 * s
            for pl in GLYPHS[ch]:
                out.append([(ox + gx * s, base - gy * s) for gx, gy in pl])
    return out


def rectify(photo):
    """Warp the photographed worksheet to a top-down PX-px-per-mm image (page origin top-left)."""
    gray = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(cv2.GaussianBlur(gray, (5, 5), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        raise ValueError("no paper found in the photo: use a dark background and show all four corners")
    c = max(cnts, key=cv2.contourArea)
    quad = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
    pts = quad.reshape(-1, 2) if len(quad) == 4 else cv2.boxPoints(cv2.minAreaRect(c))
    tl, tr, br, bl = order_quad(pts)
    if np.hypot(*(tr - tl)) > np.hypot(*(bl - tl)):
        raise ValueError("the paper looks landscape in the photo: rotate the photo so the worksheet top edge is at the top")
    dst = np.float32([[0, 0], [PAGE_W * PX, 0], [PAGE_W * PX, PAGE_H * PX], [0, PAGE_H * PX]])
    H = cv2.getPerspectiveTransform(np.float32([tl, tr, br, bl]), dst)
    size = (round(PAGE_W * PX), round(PAGE_H * PX))
    return cv2.warpPerspective(photo, H, size, borderValue=(255, 255, 255))


def find_start(rect_gray, dark):
    """Centre (page mm) of the single solid pen dot that marks the head position."""
    mask = (rect_gray < dark).astype(np.uint8)
    n, _, st, cen = cv2.connectedComponentsWithStats(mask, connectivity=8)
    dots = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        dw, dh = w / PX, h / PX
        if 3.5 <= dw <= 8 and 3.5 <= dh <= 8 and 0.75 <= dw / dh <= 1.33 and a / (w * h) >= 0.6:
            dots.append((float(cen[i][0] / PX), float(cen[i][1] / PX)))
    if not dots:
        raise ValueError("no start dot found: put a solid pen dot 4-6 mm wide where the head is, or pass --start-mm X Y")
    if len(dots) > 1:
        listed = ", ".join(f"({x:.1f}, {y:.1f})" for x, y in dots)
        raise ValueError(f"{len(dots)} dots found at {listed} mm; pass --start-mm X Y for the one you just made")
    return dots[0]


def to_machine(p, start):
    """Worksheet mm -> machine mm relative to the head start (top edge away: X=-x, Y=-y)."""
    return (round(-(p[0] - start[0]), 3), round(-(p[1] - start[1]), 3))


def jog_commands(strokes):
    """Machine-mm polylines in drawing order -> davinci_jog.py J lines (pen up at travel height between strokes)."""
    cmds = [f"J Z{TRAVEL_Z:.3f} F100"]
    pos = [0.0, 0.0]

    def move(p, feed):
        tx, ty = round(p[0], 3), round(p[1], 3)
        dx, dy = round(tx - pos[0], 3), round(ty - pos[1], 3)
        if dx or dy:
            cmds.append(f"J X{dx:.3f} Y{dy:.3f} F{feed}")
            pos[:] = [tx, ty]

    for s in strokes:
        move(s[0], 600)
        cmds.append(f"J Z{-LIFT:.3f} F100")
        for p in s[1:]:
            move(p, 600)
        cmds.append(f"J Z{LIFT:.3f} F100")
    move((0.0, 0.0), 600)
    cmds.append(f"J Z{-TRAVEL_Z:.3f} F100")
    return cmds


def plan(photo, elements, dark=110, start_mm=None, hand_root=HAND_ROOT):
    """Return the rectified page, the head start, J commands and what fits this placement.

    An element with "region": "rule-3" (an id from regions.png) is laid into that rule or blank box
    with the user's handwriting (data/handwriting) when it has been harvested; size_mm is then the letter height.
    """
    rect = rectify(photo)
    start = tuple(start_mm) if start_mm else find_start(cv2.cvtColor(rect, cv2.COLOR_BGR2GRAY), dark)
    sx, sy = start
    regions = hl.detect_regions(rect)
    by_id = {r["id"]: r for r in regions}
    glyphs = hl.load_glyphs(hand_root) if any("region" in el for el in elements) else []
    style = hl.learn_style(glyphs)
    ok_page, bad_page, skipped = [], [], []
    for i, el in enumerate(elements):
        if "region" in el:
            reg = by_id.get(el["region"])
            if reg is None:
                skipped.append((i, f"no region {el['region']!r}: see regions.png"))
                continue
            try:
                res = hl.layout_text(str(el["text"]), reg, float(el.get("size_mm", 5.0)), glyphs, style, seed=i)
            except ValueError as e:
                skipped.append((i, str(e)))
                continue
            if res["overflow"]:
                skipped.append((i, f"does not fit {el['region']} even at {res['size_mm']} mm"))
                continue
            strokes = res["paths"]
        else:
            strokes = text_strokes(str(el["text"]), float(el["x"]), float(el["y"]), float(el.get("size_mm", 5.0)))
        pts = [p for s in strokes for p in s]
        if not pts:
            skipped.append((i, "empty text"))
            continue
        if any(not (0 <= x <= PAGE_W and 0 <= y <= PAGE_H) for x, y in pts):
            bad_page += strokes
            skipped.append((i, "off the page"))
            continue
        if any(abs(x - sx) > LIMIT or abs(y - sy) > LIMIT for x, y in pts):
            bad_page += strokes
            skipped.append((i, "out of reach from this placement"))
            continue
        ok_page += strokes

    # Greedy nearest-stroke ordering to cut travel.
    pool = [[to_machine(p, start) for p in s] for s in ok_page]
    ordered, pos = [], (0.0, 0.0)
    while pool:
        k = min(range(len(pool)), key=lambda j: (pool[j][0][0] - pos[0]) ** 2 + (pool[j][0][1] - pos[1]) ** 2)
        s = pool.pop(k)
        ordered.append(s)
        pos = s[-1]
    return {"rect": rect, "start": start, "cmds": jog_commands(ordered), "regions": regions,
            "ok": ok_page, "bad": bad_page, "skipped": skipped, "strokes": len(ordered)}


def draw_preview(res):
    img = res["rect"].copy()
    sx, sy = res["start"]
    px = lambda s: np.int32([[round(x * PX), round(y * PX)] for x, y in s])
    cv2.rectangle(img, (round((sx - LIMIT) * PX), round((sy - LIMIT) * PX)),
                  (round((sx + LIMIT) * PX), round((sy + LIMIT) * PX)), (0, 160, 0), 2)
    for s in res["bad"]:
        cv2.polylines(img, [px(s)], False, (0, 0, 255), 2)
    for s in res["ok"]:
        cv2.polylines(img, [px(s)], False, (255, 80, 0), 2)
    cv2.circle(img, (round(sx * PX), round(sy * PX)), 10, (0, 200, 0), -1)
    return img


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo")
    ap.add_argument("answers")
    ap.add_argument("--out-dir", default="worksheet_out")
    ap.add_argument("--start-mm", type=float, nargs=2, metavar=("X", "Y"))
    ap.add_argument("--dark", type=int, default=110, help="grey level below which pen ink counts")
    a = ap.parse_args(argv)

    photo = cv2.imread(a.photo)
    if photo is None:
        print(f"cannot read {a.photo}")
        return 1
    with open(a.answers, encoding="utf-8") as f:
        elements = json.load(f)
    try:
        res = plan(photo, elements, a.dark, a.start_mm)
    except ValueError as e:
        print(f"error: {e}")
        return 1

    os.makedirs(a.out_dir, exist_ok=True)
    out = os.path.abspath(a.out_dir)
    cv2.imwrite(os.path.join(out, "rectified.png"), res["rect"])
    cv2.imwrite(os.path.join(out, "preview.png"), draw_preview(res))
    cv2.imwrite(os.path.join(out, "regions.png"), hl.draw_regions(res["rect"], res["regions"]))
    with open(os.path.join(out, "regions.json"), "w", encoding="utf-8") as f:
        json.dump(res["regions"], f, indent=1)
    cmds_path = os.path.join(out, "cmds.txt")
    with open(cmds_path, "w", encoding="utf-8") as f:
        f.write("\n".join(res["cmds"]) + "\n")

    sx, sy = res["start"]
    print(f"head start at worksheet ({sx:.1f}, {sy:.1f}) mm")
    print(f"{len(elements) - len(res['skipped'])} of {len(elements)} elements drawn here, {res['strokes']} strokes, {len(res['cmds'])} commands")
    for i, why in res["skipped"]:
        print(f"  skipped element {i} ({why}): {elements[i].get('text', '')!r}")
    print(f"preview: {os.path.join(out, 'preview.png')}")
    print(f"run: python tools/davinci_jog.py @{cmds_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
