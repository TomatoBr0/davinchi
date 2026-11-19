#!/usr/bin/env python3
"""Slip-on square corner tabs for the Da Vinci base plate (cad/base-plate).

Reads plate_width / plate_depth / plate_thickness from DaVinci_Plate_Editable.scad,
models one square tab centred on the bottom-left plate corner, mirrors its box
intervals to the other three corners, and writes into this folder:
  corner_cap_id{0..3}.stl          single-colour tab, assembled plate coordinates
  aruco_markers_print.svg          four 24 mm ArUco stickers on US Letter (print at 100%)
  layout.json                      parameters, geometry, paper rect, marker centres
  preview_top.png, preview_iso.png, preview_cap_section.png

Coordinates: plate lower-left corner = origin, +X right, +Y up (top view), Z up.
The plate occupies x 0..W, y 0..D, z 0..T. Every solid is a union of axis-aligned
boxes (minus the spring pocket) meshed exactly on a grid: no CSG library.
Only numpy and Pillow are needed. Run: python make_corner_caps.py
"""
from __future__ import annotations

import json
import re
import struct
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "DaVinci_Plate_Editable.scad"

# ---- parameters (mm) ----------------------------------------------------------
PAPER_W, PAPER_H = 215.9, 279.4        # US Letter
S = 26.0                               # tab square side, centred on the plate corner
HALF = S / 2                           # 13.0: tab reach over the plate from each edge
TOP_T = 2.4                            # thin top
WALL = 3.0                             # wrapper wall outside the plate edge
CLEAR = 0.2                            # fit clearance, wall to plate edge
LIP_IN = 2.0                           # lip reaches this far under the plate from its edge
LIP_T = 1.6                            # lip thickness
LIP_ZCLR = 0.2                         # gap between plate bottom (z=0) and lip top
SPRING_OD = 4.5                        # click-pen spring defaults: MEASURE YOUR SPRING
SPRING_FREE = 12.0
PRELOAD = 3.0
POCKET = SPRING_OD + 0.5               # square spring indent side
INDENT = 1.2                           # indent depth into the underside of the top
GAP = SPRING_FREE - INDENT - PRELOAD   # 7.8: clear height, paper/plate top -> top underside
STICKER = 24.0                         # printed marker incl. quiet zone
CELL = 3.0                             # 6 cells = 18 mm black square
QUIET = 1                              # quiet-zone cells on each side (3 mm)
BLACK = 6 * CELL                       # 18 mm black square

# DICT_4X4_50 ids 0-3, inner 4x4 bits row-major from the top, 1 = white.
# Generated with cv2.aruco.generateImageMarker (opencv-contrib 4.10.0).
ARUCO = {0: "1011010100110010", 1: "0000111110011010",
         2: "0011001100101101", 3: "1001100101000110"}
DICTIONARY = "DICT_4X4_50"

CORNER_NAMES = {0: "bottom-left", 1: "bottom-right", 2: "top-right", 3: "top-left"}
CORNER_FLIP = {0: (False, False), 1: (True, False), 2: (True, True), 3: (False, True)}


def read_template(path: Path):
    text = path.read_text(encoding="utf-8")
    vals = []
    for name in ("plate_width", "plate_depth", "plate_thickness"):
        m = re.search(rf"^\s*{name}\s*=\s*([0-9]*\.?[0-9]+)\s*;", text, re.M)
        if m is None:
            raise SystemExit(f"{name} not found in {path}")
        vals.append(float(m.group(1)))
    return tuple(vals)


W, D, T = read_template(TEMPLATE)
SIDE_M = (W - PAPER_W) / 2                 # 2.05 paper margin along X
END_M = (D - PAPER_H) / 2                  # 2.80 paper margin along Y
assert SIDE_M > 0 and END_M > 0, "US Letter does not fit on the plate"
PAPER = (SIDE_M, END_M, SIDE_M + PAPER_W, END_M + PAPER_H)
PLATE_BOX = (0.0, 0.0, W, D, 0.0, T)
Z_TOP_BOT = T + GAP                        # underside of the thin top (17.8)
CAP_TOP = Z_TOP_BOT + TOP_T                # top face of the tab (20.2)
WALL_O = -(CLEAR + WALL)                   # outer face of the bottom-left walls (-3.2)
LIP_Z0, LIP_Z1 = -LIP_ZCLR - LIP_T, -LIP_ZCLR
POCKET_CX = (SIDE_M + HALF) / 2            # centre of the paper-overlap region
POCKET_CY = (END_M + HALF) / 2


# ---- exact grid mesher + ArUco cells ------------------------------------------
def black_cells(marker_id, x0, y0):
    bits = ARUCO[marker_id]
    cells = []
    for r in range(6):
        for c in range(6):
            border = r in (0, 5) or c in (0, 5)
            if border or bits[(r - 1) * 4 + (c - 1)] == "0":
                x = x0 + (QUIET + c) * CELL
                y = y0 + (QUIET + 5 - r) * CELL   # image row 0 is the top
                cells.append((x, y, x + CELL, y + CELL))
    # Cells touching only at a corner would make non-manifold edges; join each such
    # corner with a 0.5 mm square (invisible to the detector).
    have = {(round(c[0], 6), round(c[1], 6)) for c in cells}
    bridge = .25
    for x, y, _, _ in list(cells):
        for dx in (-CELL, CELL):
            for dy in (-CELL, CELL):
                diag = (round(x + dx, 6), round(y + dy, 6)) in have
                side_a = (round(x + dx, 6), round(y, 6)) in have
                side_b = (round(x, 6), round(y + dy, 6)) in have
                if diag and not side_a and not side_b:
                    px, py = x + (CELL if dx > 0 else 0), y + (CELL if dy > 0 else 0)
                    cells.append((px - bridge, py - bridge, px + bridge, py + bridge))
    return cells


def mesh(add, sub=()):
    xs = sorted({b[i] for b in (*add, *sub) for i in (0, 2)})
    ys = sorted({b[i] for b in (*add, *sub) for i in (1, 3)})
    zs = sorted({b[i] for b in (*add, *sub) for i in (4, 5)})
    X, Y, Z = (np.array(v) for v in (xs, ys, zs))
    cx, cy, cz = ((a[:-1] + a[1:]) / 2 for a in (X, Y, Z))
    gx, gy, gz = np.meshgrid(cx, cy, cz, indexing="ij")

    def inside(b):
        return (gx > b[0]) & (gx < b[2]) & (gy > b[1]) & (gy < b[3]) & (gz > b[4]) & (gz < b[5])

    occ = np.zeros(gx.shape, bool)
    for b in add:
        occ |= inside(b)
    for b in sub:
        occ &= ~inside(b)
    pad = np.pad(occ, 1)
    tris = []
    for axis in range(3):
        a = np.moveaxis(pad, axis, 0)
        diff = a[1:].astype(np.int8) - a[:-1].astype(np.int8)  # +1: solid starts, -1: ends
        coords = [X, Y, Z]
        others = [i for i in range(3) if i != axis]
        for idx in zip(*np.nonzero(diff)):
            k, i, j = idx[0], idx[1] - 1, idx[2] - 1
            if not (0 <= i < len(coords[others[0]]) - 1 and 0 <= j < len(coords[others[1]]) - 1):
                continue
            s = diff[idx]
            u0, u1 = coords[others[0]][i], coords[others[0]][i + 1]
            v0, v1 = coords[others[1]][j], coords[others[1]][j + 1]
            w = coords[axis][k]

            def P(u, v):
                p = [0.0, 0.0, 0.0]
                p[axis], p[others[0]], p[others[1]] = w, u, v
                return tuple(p)

            q = [P(u0, v0), P(u1, v0), P(u1, v1), P(u0, v1)]
            # Normal is -axis where solid starts (s=+1), +axis where it ends; with
            # (axis, others) cyclic, (u,v) order gives +axis, so reverse for s=+1.
            if (axis == 1) ^ (s > 0):
                q = q[::-1]
            n = [0.0, 0.0, 0.0]
            n[axis] = -1.0 if s > 0 else 1.0
            tris.append((n, q[0], q[1], q[2]))
            tris.append((n, q[0], q[2], q[3]))
    return tris


def write_stl(path, tris):
    with open(path, "wb") as f:
        f.write(b"davinchi paper corner tab".ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        for n, a, b, c in tris:
            f.write(struct.pack("<12fH", *n, *a, *b, *c, 0))


def check(tris):
    """Return (boundary_edges, nonmanifold_edges, volume_cm3)."""
    edges = Counter()
    vol = 0.0
    for _, a, b, c in tris:
        for e in ((a, b), (b, c), (c, a)):
            edges[e] += 1
        vol += np.dot(a, np.cross(b, c)) / 6
    bad_open = sum(1 for (p, q), n in edges.items() if edges.get((q, p), 0) != n)
    bad_multi = sum(1 for n in edges.values() if n > 1)
    return bad_open, bad_multi, vol / 1000


# ---- geometry -----------------------------------------------------------------
def overlaps(a, b):
    return (a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
            and a[4] < b[5] and b[4] < a[5])


def mirror_box(b, mx, my):
    x0, y0, x1, y1, z0, z1 = b
    if mx:
        x0, x1 = W - x1, W - x0
    if my:
        y0, y1 = D - y1, D - y0
    return (x0, y0, x1, y1, z0, z1)


def marker_center(k):
    """The sticker is centred on its tab, and the tab is centred on the plate corner."""
    mx, my = CORNER_FLIP[k]
    return (W if mx else 0.0, D if my else 0.0)


def sticker_origin(k):
    cx, cy = marker_center(k)
    return (cx - STICKER / 2, cy - STICKER / 2)


def sticker_cells_plate(k):
    ox, oy = sticker_origin(k)
    return black_cells(k, ox, oy)


def cap_boxes_bl():
    """Bottom-left tab in plate coordinates: (solid boxes by name, spring pocket box)."""
    solid = {
        "top": (-HALF, -HALF, HALF, HALF, Z_TOP_BOT, CAP_TOP),
        "wall_left": (WALL_O, WALL_O, -CLEAR, HALF, LIP_Z0, Z_TOP_BOT),
        "wall_bottom": (WALL_O, WALL_O, HALF, -CLEAR, LIP_Z0, Z_TOP_BOT),
        "lip_left": (WALL_O, WALL_O, LIP_IN, HALF, LIP_Z0, LIP_Z1),
        "lip_bottom": (WALL_O, WALL_O, HALF, LIP_IN, LIP_Z0, LIP_Z1),
    }
    h = POCKET / 2
    pocket = (POCKET_CX - h, POCKET_CY - h, POCKET_CX + h, POCKET_CY + h,
              Z_TOP_BOT - 1.0, Z_TOP_BOT + INDENT)
    return solid, pocket


def check_design():
    """Asserts on the parameters and the bottom-left box list."""
    solid, pocket = cap_boxes_bl()
    for name, b in solid.items():
        assert not overlaps(b, PLATE_BOX), f"{name} intersects the plate"
    px0, py0, px1, py1, pz0, pz1 = pocket
    assert px0 >= SIDE_M - 1e-9 and py0 >= END_M - 1e-9, "pocket not over the paper"
    assert px1 < HALF and py1 < HALF, "pocket leaves the plate quarter of the tab"
    assert POCKET >= SPRING_OD, "pocket smaller than the spring"
    assert pz0 < Z_TOP_BOT < pz1 < CAP_TOP, "pocket z range"
    assert abs((Z_TOP_BOT + INDENT - T) - (SPRING_FREE - PRELOAD)) < 1e-9, \
        "installed spring length != SPRING_FREE - PRELOAD"
    assert abs(CAP_TOP - (T + GAP + TOP_T)) < 1e-9
    assert abs(GAP - (SPRING_FREE - INDENT - PRELOAD)) < 1e-9
    assert abs(2 * HALF - S) < 1e-12
    assert STICKER == (6 + 2 * QUIET) * CELL and BLACK == 6 * CELL
    assert STICKER <= S, "sticker does not fit on the tab top"


def check_corner(k, solid, pocket):
    for b in solid:
        assert not overlaps(b, PLATE_BOX), f"id {k}: tab part intersects the plate"
    mx, my = CORNER_FLIP[k]
    px0, py0, px1, py1 = mirror_box(pocket, mx, my)[:4]   # back in bottom-left frame
    assert px0 >= SIDE_M - 1e-9 and py0 >= END_M - 1e-9, f"id {k}: pocket not over paper"
    assert px1 < HALF and py1 < HALF, f"id {k}: pocket outside plate quarter"
    cx, cy = marker_center(k)
    assert (cx, cy) in {(0.0, 0.0), (W, 0.0), (W, D), (0.0, D)}


def build_cap(k):
    mx, my = CORNER_FLIP[k]
    solid_bl, pocket_bl = cap_boxes_bl()
    solid = [mirror_box(b, mx, my) for b in solid_bl.values()]
    pocket = mirror_box(pocket_bl, mx, my)
    check_corner(k, solid, pocket)
    return {"solid": solid, "pocket": pocket, "mesh": mesh(solid, [pocket])}


# ---- analytic volume (inclusion-exclusion over boxes) -------------------------
def _isect(a, b):
    box = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]),
           min(a[3], b[3]), max(a[4], b[4]), min(a[5], b[5]))
    return box if box[2] > box[0] and box[3] > box[1] and box[5] > box[4] else None


def _vol(b):
    return (b[2] - b[0]) * (b[3] - b[1]) * (b[5] - b[4])


def union_volume(boxes):
    total = 0.0
    n = len(boxes)
    for mask in range(1, 1 << n):
        inter, cnt, ok = None, 0, True
        for i in range(n):
            if mask >> i & 1:
                cnt += 1
                inter = boxes[i] if inter is None else _isect(inter, boxes[i])
                if inter is None:
                    ok = False
                    break
        if ok:
            total += (1 if cnt % 2 else -1) * _vol(inter)
    return total


def analytic_volume_bl():
    """Volume (cm3) of the bottom-left tab: union of solid boxes minus the pocket."""
    solid, pocket = cap_boxes_bl()
    boxes = list(solid.values())
    cut = [c for c in (_isect(b, pocket) for b in boxes) if c is not None]
    return (union_volume(boxes) - union_volume(cut)) / 1000


# ---- output: STL --------------------------------------------------------------
def write_stls(caps):
    report = {}
    for k, c in caps.items():
        name = f"corner_cap_id{k}.stl"
        write_stl(HERE / name, c["mesh"])
        bo, bm, vol = check(c["mesh"])
        assert bo == 0 and bm == 0 and vol > 0, f"{name}: open={bo} nonmanifold={bm} vol={vol}"
        report[k] = (bo, bm, vol, len(c["mesh"]))
        print(f"{name}: {len(c['mesh'])} tris, open={bo} nonmanifold={bm} volume_cm3={vol:.4f}")
    vols = [r[2] for r in report.values()]
    assert max(vols) - min(vols) < 1e-6, "mirrored tabs differ in volume"
    return report


# ---- output: layout.json -------------------------------------------------------
def write_layout(caps):
    layout = {
        "units": "mm",
        "origin": ("plate lower-left corner, top view: +X right, +Y up, Z up; plate occupies "
                   "x 0..W, y 0..D, z 0..T; all tabs are in assembled plate coordinates"),
        "plate": {"template": TEMPLATE.name, "width": W, "depth": D, "thickness": T},
        "paper": {"size": [PAPER_W, PAPER_H], "rect_xy": [round(v, 4) for v in PAPER],
                  "margin_side": round(SIDE_M, 4), "margin_end": round(END_M, 4),
                  "centred": True, "thickness_drawn_in_preview": 0.1},
        "tab": {"side": S, "half": HALF, "centred_on": "plate corner",
                "top_t": TOP_T, "top_z_bottom": round(Z_TOP_BOT, 4), "top_z": round(CAP_TOP, 4),
                "top_above_plate_top": round(CAP_TOP - T, 4),
                "footprint_bl_xy": [-HALF, -HALF, HALF, HALF],
                "paper_covered_bl_xy": [round(SIDE_M, 4), round(END_M, 4), HALF, HALF],
                "print_orientation": "top face down on the bed"},
        "walls": {"wall": WALL, "clear": CLEAR, "outer_face_bl": WALL_O,
                  "z_range": [round(LIP_Z0, 4), round(Z_TOP_BOT, 4)]},
        "lips": {"inset_under_plate": LIP_IN, "thickness": LIP_T, "zclear": LIP_ZCLR,
                 "z_range": [round(LIP_Z0, 4), round(LIP_Z1, 4)],
                 "below_plate_bottom": round(LIP_ZCLR + LIP_T, 4)},
        "spring": {"od": SPRING_OD, "free": SPRING_FREE, "preload": PRELOAD,
                   "installed": SPRING_FREE - PRELOAD, "pocket_side": POCKET,
                   "pocket_bl_xy": [round(v, 4) for v in cap_boxes_bl()[1][:4]],
                   "pocket_z": [round(Z_TOP_BOT - 1.0, 4), round(Z_TOP_BOT + INDENT, 4)],
                   "indent": INDENT},
        "gap": round(GAP, 4),
        "gap_definition": "SPRING_FREE - INDENT - PRELOAD; clear height from plate top to top underside",
        "sticker": {"size": STICKER, "cell": CELL, "quiet_cells": QUIET,
                    "black_size": BLACK, "printed": True, "print_scale": "100%"},
        "dictionary": DICTIONARY,
        "markers": {},
        "footprint_assembled": {
            "tabs_overall_xy": [round(W + S, 4), round(D + S, 4)],
            "walls_and_lips_overall_xy": [round(W + 2 * (WALL + CLEAR), 4),
                                          round(D + 2 * (WALL + CLEAR), 4)],
        },
    }
    for k in range(4):
        cx, cy = marker_center(k)
        ox, oy = sticker_origin(k)
        layout["markers"][str(k)] = {
            "corner": CORNER_NAMES[k],
            "center": [cx, cy],
            "sticker_origin_bl": [round(ox, 4), round(oy, 4)],
            "top_z": round(CAP_TOP, 4),
            "tab_xy": [round(v, 4) for v in mirror_box(cap_boxes_bl()[0]["top"], *CORNER_FLIP[k])[:4]],
        }
    (HERE / "layout.json").write_text(json.dumps(layout, indent=2), encoding="utf-8")


# ---- output: printable stickers (SVG, mm units, y down) ------------------------
def write_svg(path):
    PW, PH = PAPER_W, PAPER_H
    gap = 40.0
    xs = [PW / 2 - gap / 2 - STICKER, PW / 2 + gap / 2]
    ys = [50.0, 50.0 + STICKER + 36.0]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{PW}mm" height="{PH}mm" '
           f'viewBox="0 0 {PW} {PH}">',
           f'<rect x="0" y="0" width="{PW}" height="{PH}" fill="#fff"/>']

    def text(x, y, s, size=3.5, weight="normal", anchor="start"):
        out.append(f'<text x="{x:.2f}" y="{y:.2f}" font-family="Arial, Helvetica, sans-serif" '
                   f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" '
                   f'fill="#000">{s}</text>')

    text(PW / 2, 18, f"Paper-corner tab stickers: ArUco {DICTIONARY}, ids 0-3", 5.0, "bold", "middle")
    text(PW / 2, 26, "Print at 100% (no fit to page). Cut on the dashed lines (24 mm).", 3.2, anchor="middle")
    text(PW / 2, 31, "Glue each sticker centred on its tab top. Keep the white border (quiet zone).", 3.2,
         anchor="middle")
    for k in range(4):
        ox, oy = xs[k % 2], ys[k // 2]
        out.append(f'<rect x="{ox:.3f}" y="{oy:.3f}" width="{STICKER}" height="{STICKER}" fill="#fff"/>')
        for x0, y0, x1, y1 in black_cells(k, 0.0, 0.0):
            # SVG y points down: flip within the sticker (row 0 at the top).
            out.append(f'<rect x="{ox + x0:.3f}" y="{oy + STICKER - y1:.3f}" '
                       f'width="{x1 - x0:.3f}" height="{y1 - y0:.3f}" fill="#000"/>')
        out.append(f'<rect x="{ox:.3f}" y="{oy:.3f}" width="{STICKER}" height="{STICKER}" fill="none" '
                   f'stroke="#000" stroke-width="0.25" stroke-dasharray="2,1.5"/>')
        text(ox, oy + STICKER + 6, f"id {k} - glue on {CORNER_NAMES[k]} tab", 3.6)
    yb = ys[1] + STICKER + 30
    text(PW / 2, yb, "print at 100%: black square must measure 18 mm", 3.6, "bold", "middle")
    out.append(f'<rect x="{PW / 2 - BLACK / 2:.3f}" y="{yb + 4:.3f}" width="{BLACK}" height="3" fill="#000"/>')
    text(PW / 2, yb + 11, "check bar above: 18 mm, black square: 18 mm", 3.0, anchor="middle")
    out.append("</svg>")
    Path(path).write_text("\n".join(out), encoding="utf-8")


# ---- previews -----------------------------------------------------------------
def load_font(size):
    from PIL import ImageFont
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def write_preview_top(path):
    from PIL import Image, ImageDraw
    S_PX = 3.0                                     # px per mm
    pad = 16.0
    ex0, ey0 = -HALF - pad, -HALF - pad
    ex1, ey1 = W + HALF + pad, D + HALF + pad
    head, foot = 64, 150
    bw, bh = round((ex1 - ex0) * S_PX), round((ey1 - ey0) * S_PX)
    img = Image.new("RGB", (bw, bh + head + foot), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f_big, f_small = load_font(18), load_font(14)

    def px(x, y):
        return ((x - ex0) * S_PX, head + (ey1 - y) * S_PX)

    def rect(b, **kw):
        a, c = px(b[0], b[3]), px(b[2], b[1])
        d.rectangle([round(a[0]), round(a[1]), round(c[0]), round(c[1])], **kw)

    def dash(a, c, colour, width=2, on=7, off=5):
        L = float(np.hypot(c[0] - a[0], c[1] - a[1]))
        ux, uy = (c[0] - a[0]) / L, (c[1] - a[1]) / L
        t = 0.0
        while t < L:
            t2 = min(t + on, L)
            d.line([(a[0] + ux * t, a[1] + uy * t), (a[0] + ux * t2, a[1] + uy * t2)],
                   fill=colour, width=width)
            t += on + off

    def dashed_rect(b, colour):
        p0, p1 = px(b[0], b[3]), px(b[2], b[1])
        cs = [p0, (p1[0], p0[1]), p1, (p0[0], p1[1])]
        for i in range(4):
            dash(cs[i], cs[(i + 1) % 4], colour)

    d.text((10, 8), "Paper corner tabs - top view, plate coordinates (+X right, +Y up)",
           fill=(0, 0, 0), font=f_big)
    d.text((10, 36), f"grey = plate {W:g} x {D:g} x {T:g} (template)   "
                     f"white = US Letter paper {PAPER_W} x {PAPER_H}   "
                     f"blue-grey = tab top",
           fill=(60, 60, 60), font=f_small)

    rect(PLATE_BOX, fill=(214, 214, 214), outline=(140, 140, 140))
    rect(PAPER, fill=(255, 255, 255), outline=(110, 110, 110))
    solid_bl, pocket_bl = cap_boxes_bl()
    for k in range(4):
        mx, my = CORNER_FLIP[k]
        rect(mirror_box(solid_bl["top"], mx, my), fill=(92, 120, 148), outline=(50, 70, 90))
        ox, oy = sticker_origin(k)
        rect((ox, oy, ox + STICKER, oy + STICKER), fill="white")
        for x0, y0, x1, y1 in sticker_cells_plate(k):
            rect((x0, y0, x1, y1), fill="black")
        dashed_rect(mirror_box(pocket_bl, mx, my), (230, 60, 0))
        ax = (W + HALF + 2) if mx else (-HALF - 2)
        ay = (D + HALF + 2) if my else (-HALF - 2)
        anchor = ("l" if mx else "r") + ("a" if my else "d")
        d.text(px(ax, ay), f"id {k}", fill=(0, 0, 0), font=f_big, anchor=anchor)

    base = head + bh
    d.text((10, base + 6), f"Tabs: {S:g} x {S:g} mm, centred on each plate corner "
                           f"({HALF:g} mm over the plate each way). Stickers {STICKER:g} mm, "
                           f"black square {BLACK:g} mm.",
           fill=(0, 0, 0), font=f_small)
    d.text((10, base + 28), f"Dashed orange = spring pocket {POCKET:g} mm square, centre "
                            f"({POCKET_CX:.2f}, {POCKET_CY:.2f}) on the paper corner. "
                            f"Cap top z = {CAP_TOP:g}.",
           fill=(0, 0, 0), font=f_small)
    d.text((10, base + 50), f"Assembled tab extent {W + S:g} x {D + S:g} mm. Markers: {DICTIONARY}, "
                            f"ids 0 BL, 1 BR, 2 TR, 3 TL.",
           fill=(0, 0, 0), font=f_small)
    bx, by = 10, base + 90
    d.rectangle([bx, by, bx + 100 * S_PX, by + 6], fill=(0, 0, 0))
    d.rectangle([bx + 50 * S_PX, by, bx + 100 * S_PX, by + 6], fill=(255, 255, 255), outline=(0, 0, 0))
    d.text((bx, by + 10), "0", fill=(0, 0, 0), font=f_small)
    d.text((bx + 100 * S_PX, by + 10), "100 mm", fill=(0, 0, 0), font=f_small, anchor="ma")
    img.save(path)


def _view():
    c = np.array([1.0, -1.0, 1.2])
    c /= np.linalg.norm(c)                       # direction toward the viewer
    right = np.cross([0.0, 0.0, 1.0], c)
    right /= np.linalg.norm(right)
    up = np.cross(c, right)
    up /= np.linalg.norm(up)
    light = np.array([0.35, -0.6, 1.0])
    light /= np.linalg.norm(light)
    return c, np.stack([right, up], axis=1), light


def _tri_array(tris):
    return np.array([[a, b, c] for _, a, b, c in tris], dtype=float)


def quad_tris(x0, y0, x1, y1, z):
    a, b, c, d = (x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)
    return np.array([[a, b, c], [a, c, d]], dtype=float)


def write_preview_iso(path, layers):
    """Isometric z-buffer render. layers: list of (triangles Nx3x3, rgb, shaded)."""
    from PIL import Image
    c, basis, light = _view()
    allp = np.concatenate([(t.reshape(-1, 3)) @ basis for t, _, _ in layers])
    mn, mx = allp.min(axis=0), allp.max(axis=0)
    WIMG, M, HEAD = 1200, 30, 40
    scale = (WIMG - 2 * M) / (mx[0] - mn[0])
    HIMG = int(round((mx[1] - mn[1]) * scale + 2 * M + HEAD))
    zbuf = np.full((HIMG, WIMG), -np.inf)
    img = np.full((HIMG, WIMG, 3), 255, np.uint8)
    for tris, colour, shaded in layers:
        for tri in tris:
            n = np.cross(tri[1] - tri[0], tri[2] - tri[0])
            ln = np.linalg.norm(n)
            if ln < 1e-12:
                continue
            n = n / ln
            if n @ c < 0:
                n = -n
            col = np.array(colour, float)
            if shaded:
                col = col * (0.45 + 0.55 * max(float(n @ light), 0.0))
            col = np.clip(col, 0, 255).astype(np.uint8)
            # map so that +Y points up in the image
            p2 = np.stack([(tri @ basis)[:, 0] - mn[0], (mx[1] - (tri @ basis)[:, 1])], axis=1)
            p2 = p2 * scale + [M, M + HEAD]
            dep = tri @ c
            xs, ys = p2[:, 0], p2[:, 1]
            x0, x1 = max(int(np.floor(xs.min())), 0), min(int(np.ceil(xs.max())), WIMG - 1)
            y0, y1 = max(int(np.floor(ys.min())), 0), min(int(np.ceil(ys.max())), HIMG - 1)
            if x0 > x1 or y0 > y1:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            (ax, ay), (bx, by), (cx, cy) = p2
            den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(den) < 1e-12:
                continue
            l0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
            l1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
            l2 = 1.0 - l0 - l1
            inside = (l0 >= -1e-9) & (l1 >= -1e-9) & (l2 >= -1e-9)
            z = l0 * dep[0] + l1 * dep[1] + l2 * dep[2]
            zsub = zbuf[y0:y1 + 1, x0:x1 + 1]
            isub = img[y0:y1 + 1, x0:x1 + 1]
            m = inside & (z > zsub)
            zsub[m] = z[m]
            isub[m] = col
    Image.fromarray(img).save(path)


def write_preview_iso_all(path, caps, plate_tris, paper_tris):
    layers = [(_tri_array(plate_tris), (205, 205, 205), True),
              (_tri_array(paper_tris), (252, 252, 246), True)]
    for k in range(4):
        layers.append((_tri_array(caps[k]["mesh"]), (92, 120, 148), True))
    white, black = [], []
    for k in range(4):
        ox, oy = sticker_origin(k)
        white.append(quad_tris(ox, oy, ox + STICKER, oy + STICKER, CAP_TOP + 0.05))
        for x0, y0, x1, y1 in sticker_cells_plate(k):
            black.append(quad_tris(x0, y0, x1, y1, CAP_TOP + 0.10))
    layers.append((np.concatenate(white), (250, 250, 250), False))
    layers.append((np.concatenate(black), (15, 15, 15), False))
    write_preview_iso(path, layers)


def write_cap_section(path):
    from PIL import Image, ImageDraw
    S_PX = 8.0
    xmin, xmax, zmin, zmax = -34.0, 40.0, -7.0, 25.0
    left, top = 40, 70
    pw, ph = (xmax - xmin) * S_PX, (zmax - zmin) * S_PX
    img = Image.new("RGB", (int(left + pw + 380), int(top + ph + 70)), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f, fs = load_font(16), load_font(14)
    INK = (30, 30, 30)

    def P(x, z):
        return (left + (x - xmin) * S_PX, top + (zmax - z) * S_PX)

    def rect(x0, z0, x1, z1, **kw):
        a, b = P(x0, z1), P(x1, z0)
        d.rectangle([round(a[0]), round(a[1]), round(b[0]), round(b[1])], **kw)

    def text(x, z, s, anchor="lm", font=fs):
        d.text(P(x, z), s, fill=(20, 20, 20), font=font, anchor=anchor)

    def dim_v(x, z0, z1):
        a, b = P(x, z0), P(x, z1)
        d.line([a, b], fill=INK)
        for p in (a, b):
            d.line([p[0] - 4, p[1], p[0] + 4, p[1]], fill=INK)

    def dim_h(z, x0, x1):
        a, b = P(x0, z), P(x1, z)
        d.line([a, b], fill=INK)
        for p in (a, b):
            d.line([p[0], p[1] - 4, p[0], p[1] + 4], fill=INK)

    solid_bl, pocket = cap_boxes_bl()
    p0x, p1x = pocket[0], pocket[2]
    d.text((10, 10), f"Cross-section, tab id 0 at y = {POCKET_CY:.2f} (pocket centre), "
                     f"looking +Y, z up, 8 px/mm", fill=(0, 0, 0), font=f)

    rect(0, 0, xmax, T, fill=(205, 205, 205), outline=(120, 120, 120))            # plate
    text(20, 5.0, "plate, z 0..10", anchor="mm")
    rect(SIDE_M, T, xmax, T + 0.1, fill=(255, 255, 255), outline=(60, 60, 60))    # paper
    text(-6, 9.0, "paper / plate top z = 10", anchor="rm")
    # Lip under the plate, wall beside the plate edge (both on the cut plane y = pocket centre)
    rect(WALL_O, LIP_Z0, LIP_IN, LIP_Z1, fill=(92, 120, 148), outline=(50, 70, 90))
    rect(WALL_O, LIP_Z0, -CLEAR, Z_TOP_BOT, fill=(92, 120, 148), outline=(50, 70, 90))
    # Thin top with the spring indent cut into its underside
    top_poly = [P(-HALF, Z_TOP_BOT), P(p0x, Z_TOP_BOT), P(p0x, Z_TOP_BOT + INDENT),
                P(p1x, Z_TOP_BOT + INDENT), P(p1x, Z_TOP_BOT), P(HALF, Z_TOP_BOT),
                P(HALF, CAP_TOP), P(-HALF, CAP_TOP)]
    d.polygon(top_poly, fill=(92, 120, 148), outline=(50, 70, 90))
    # Spring: zigzag from the plate top to the indent ceiling (installed length 9)
    sx = POCKET_CX
    zs = np.linspace(T, Z_TOP_BOT + INDENT, 11)
    pts = [P(sx + (SPRING_OD / 2 - 0.25) * (1 if i % 2 else -1) * (0 if i in (0, 10) else 1), z)
           for i, z in enumerate(zs)]
    d.line(pts, fill=(170, 40, 40), width=2, joint="curve")

    # Labels and dimensions (kept apart so none overlap)
    dim_v(HALF + 1.5, CAP_TOP - TOP_T, CAP_TOP)
    text(HALF + 2.5, CAP_TOP - TOP_T / 2, f"TOP_T {TOP_T:g}")
    text(p1x + 0.6, CAP_TOP + 1.4, f"INDENT {INDENT:g} (pocket {POCKET:g} mm square)")
    dim_v(p1x + 0.6, Z_TOP_BOT, Z_TOP_BOT + INDENT)
    dim_v(-8.0, T, Z_TOP_BOT)
    text(-8.8, (T + Z_TOP_BOT) / 2 + 0.7, f"GAP {GAP:g}", anchor="rm")
    text(-8.8, (T + Z_TOP_BOT) / 2 - 0.9, "(clear height)", anchor="rm")
    text(p1x + 0.6, 15.0, f"spring OD {SPRING_OD:g}")
    text(p1x + 0.6, 13.6, f"spring free {SPRING_FREE:g} -> installed {SPRING_FREE - PRELOAD:g}")
    text(p1x + 0.6, 12.2, f"({PRELOAD:g} mm preload)")
    dim_h(LIP_Z0 - 1.2, WALL_O, -CLEAR)
    text((WALL_O - CLEAR) / 2, LIP_Z0 - 2.0, f"WALL {WALL:g}", anchor="mt")
    text(0.6, -5.8, f"CLEAR {CLEAR:g}", anchor="lm")
    text(LIP_IN + 1.2, (LIP_Z0 + LIP_Z1) / 2,
         f"LIP {LIP_T:g} thick, {LIP_IN:g} under plate, {LIP_ZCLR:g} gap to plate bottom")
    dim_v(WALL_O - 1.2, LIP_Z0, LIP_Z1)
    text(WALL_O - 1.8, (LIP_Z0 + LIP_Z1) / 2, "LIP", anchor="rm")
    text(-HALF - 0.6, CAP_TOP - 0.6, f"cap top z {CAP_TOP:g}", anchor="rm")
    text(-HALF - 0.6, CAP_TOP - 2.0, f"{CAP_TOP - T:g} above plate top", anchor="rm")
    d.text((10, top + ph + 30),
           "z = 0 is the plate bottom. Paper drawn 0.1 mm thick. Spring drawn from the plate top "
           "(z 10) to the indent ceiling: 9 mm installed.", fill=(60, 60, 60), font=fs)
    img.save(path)


# ---- main ----------------------------------------------------------------------
def main():
    check_design()
    for old in HERE.glob("corner_cap_id*_inlay_*.stl"):   # stale two-colour files
        old.unlink()
    caps = {k: build_cap(k) for k in range(4)}
    report = write_stls(caps)
    vol_mesh = report[0][2]
    vol_an = analytic_volume_bl()
    print(f"id 0 analytic volume {vol_an:.4f} cm3, mesh {vol_mesh:.4f} cm3, "
          f"diff {vol_mesh - vol_an:+.2e} cm3")
    assert abs(vol_mesh - vol_an) < 0.01, "mesh volume differs from analytic volume"
    write_layout(caps)
    write_svg(HERE / "aruco_markers_print.svg")
    plate_tris = mesh([PLATE_BOX])
    paper_tris = mesh([(PAPER[0], PAPER[1], PAPER[2], PAPER[3], T, T + 0.1)])
    write_preview_top(HERE / "preview_top.png")
    write_preview_iso_all(HERE / "preview_iso.png", caps, plate_tris, paper_tris)
    write_cap_section(HERE / "preview_cap_section.png")
    print(f"plate {W:g} x {D:g} x {T:g}; tab top z {CAP_TOP:g}; "
          f"tab extent {W + S:g} x {D + S:g} mm")


if __name__ == "__main__":
    main()
