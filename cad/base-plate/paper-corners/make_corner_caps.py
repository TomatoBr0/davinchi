#!/usr/bin/env python3
"""Slip-on paper corner caps for the Da Vinci base plate (cad/base-plate).

Reads plate_width / plate_depth / plate_thickness from DaVinci_Plate_Editable.scad,
models one L-shaped cap at the bottom-left plate corner, places the other three by
mirroring its box intervals, and writes into this folder:
  corner_cap_id{0..3}.stl                single colour cap
  corner_cap_id{N}_inlay_body.stl        cap with the ArUco black cells recessed
  corner_cap_id{N}_inlay_black.stl       black cells that fill that recess
  layout.json                            geometry, paper rect, marker centres
  preview_top.png, preview_iso.png, preview_cap_section.png

Coordinates: plate lower-left corner = origin, +X right, +Y up (top view), Z up.
The plate occupies z 0..T; the cap top is at z = T + HEIGHT_ABOVE_PAPER.
Only numpy and Pillow are needed. Every solid is built from axis-aligned boxes and
meshed exactly on a grid (exact grid mesher, no CSG library).
Run: python make_corner_caps.py
"""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "DaVinci_Plate_Editable.scad"

# ---- parameters -------------------------------------------------------------
PAPER_W, PAPER_H = 215.9, 279.4   # US Letter
WALL = 3.0                # wrapper wall thickness, outside the plate edge
CLEAR = 0.2               # fit clearance between plate edge and wall
CAP = 38.0                # cap reach from the plate edge inward
SLOT = 0.6                # paper slot above plate top
HEIGHT_ABOVE_PAPER = 10.0 # cap top = T + this ("1 cm")
CELL = 4.0                # ArUco cell size: 6 cells = 24 mm black square
QUIET = 1                 # white quiet-zone cells around each marker
INLAY_DEPTH = 0.6         # 3 layers at 0.2 mm

# DICT_4X4_50 ids 0-3, inner 4x4 bits row-major from the top, 1 = white.
# Generated with cv2.aruco.generateImageMarker (opencv-contrib 4.10.0).
ARUCO = {0: "1011010100110010", 1: "0000111110011010",
         2: "0011001100101101", 3: "1001100101000110"}
DICTIONARY = "DICT_4X4_50"

SPOT = (6 + 2 * QUIET) * CELL                  # white square incl. quiet zone
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
SIDE_M = (W - PAPER_W) / 2                    # paper margin along X
END_M = (D - PAPER_H) / 2                     # paper margin along Y
assert SIDE_M > 0 and END_M > 0, "US Letter does not fit on the plate"
PAPER = (SIDE_M, END_M, SIDE_M + PAPER_W, END_M + PAPER_H)
CAP_TOP = T + HEIGHT_ABOVE_PAPER
SLOT_TOP = T + SLOT
EDGE_O = -(CLEAR + WALL)                      # outer face of the bottom-left cap
FOOT = CAP - EDGE_O                           # cap footprint (square), 41.2 mm
MARKER_C = (EDGE_O + CAP) / 2                 # marker centre on the cap top, 17.4 mm


# ---- exact grid mesher + ArUco cells (DICT_4X4_50 bits from OpenCV 4.10) ----------------------
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
        f.write(b"davinchi paper plate".ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        for n, a, b, c in tris:
            f.write(struct.pack("<12fH", *n, *a, *b, *c, 0))


def check(tris):
    """Return (boundary_edges, nonmanifold_edges, volume_cm3)."""
    from collections import Counter
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
def mirror_box(b, mx, my):
    x0, y0, x1, y1, z0, z1 = b
    if mx:
        x0, x1 = W - x1, W - x0
    if my:
        y0, y1 = D - y1, D - y0
    return (x0, y0, x1, y1, z0, z1)


def marker_center(k):
    mx, my = CORNER_FLIP[k]
    return (W - MARKER_C if mx else MARKER_C, D - MARKER_C if my else MARKER_C)


def cap_boxes_bl():
    """Bottom-left cap in plate coordinates: (solid, pocket) boxes."""
    solid = (EDGE_O, EDGE_O, CAP, CAP, 0.0, CAP_TOP)
    pocket = (-CLEAR, -CLEAR, CAP + 1, CAP + 1, -1.0, SLOT_TOP)
    return solid, pocket


def check_pocket(k, solid, pocket):
    """Assert the pocket interval checks for corner k (plate edges at x=0/W, y=0/D)."""
    mx, my = CORNER_FLIP[k]
    # Boundary of the pocket nearest the plate edge, and the outer wall face, per axis.
    px_in = pocket[2] if mx else pocket[0]
    px_out = solid[2] if mx else solid[0]
    py_in = pocket[3] if my else pocket[1]
    py_out = solid[3] if my else solid[1]
    xe = W if mx else 0.0
    ye = D if my else 0.0
    assert abs(abs(px_in - xe) - CLEAR) < 1e-9, f"id {k}: x clearance != CLEAR"
    assert abs(abs(py_in - ye) - CLEAR) < 1e-9, f"id {k}: y clearance != CLEAR"
    assert abs(abs(px_in - px_out) - WALL) < 1e-9, f"id {k}: x wall != WALL"
    assert abs(abs(py_in - py_out) - WALL) < 1e-9, f"id {k}: y wall != WALL"
    assert abs((pocket[5] - T) - SLOT) < 1e-9, f"id {k}: slot != SLOT"
    assert abs(solid[5] - CAP_TOP) < 1e-9 and abs(CAP_TOP - T - HEIGHT_ABOVE_PAPER) < 1e-9
    # Slot must sit above the plate top and leave the paper (on z = T) inside it.
    assert pocket[4] < 0.0 and pocket[5] > T


def build_cap(k):
    mx, my = CORNER_FLIP[k]
    solid_bl, pocket_bl = cap_boxes_bl()
    solid = mirror_box(solid_bl, mx, my)
    pocket = mirror_box(pocket_bl, mx, my)
    check_pocket(k, solid, pocket)
    cx, cy = marker_center(k)
    cells = [(x0, y0, x1, y1, CAP_TOP - INLAY_DEPTH, CAP_TOP)
             for x0, y0, x1, y1 in black_cells(k, cx - SPOT / 2, cy - SPOT / 2)]
    recess = [(x0, y0, x1, y1, CAP_TOP - INLAY_DEPTH, CAP_TOP + 1)
              for x0, y0, x1, y1, _, _ in cells]
    return {
        "solid": solid, "pocket": pocket, "cells": cells,
        "single": mesh([solid], [pocket]),
        "body": mesh([solid], [pocket, *recess]),
        "black": mesh(cells),
    }


# ---- output -------------------------------------------------------------------
def write_stls(caps):
    report = {}
    for k, c in caps.items():
        for key, name in (("single", f"corner_cap_id{k}.stl"),
                          ("body", f"corner_cap_id{k}_inlay_body.stl"),
                          ("black", f"corner_cap_id{k}_inlay_black.stl")):
            tris = c[key]
            write_stl(HERE / name, tris)
            bo, bm, vol = check(tris)
            report[name] = (bo, bm, vol, len(tris))
            assert bo == 0 and bm == 0 and vol > 0, f"{name}: open={bo} nonmanifold={bm} vol={vol}"
            print(f"{name}: {len(tris)} tris, open={bo} nonmanifold={bm} volume_cm3={vol:.4f}")
        vs = report[f"corner_cap_id{k}.stl"][2]
        vb = report[f"corner_cap_id{k}_inlay_body.stl"][2]
        vk = report[f"corner_cap_id{k}_inlay_black.stl"][2]
        assert abs(vs - (vb + vk)) < 0.01, f"id {k}: single {vs} != body {vb} + black {vk}"
        print(f"  id {k}: single {vs:.4f} vs body+black {vb + vk:.4f} cm3 (diff {vs - vb - vk:+.2e})")
    return report


def write_layout(caps):
    layout = {
        "units": "mm",
        "origin": ("plate lower-left corner, top view: +X right, +Y up, Z up; "
                   "plate occupies z 0..T; all caps are in assembled plate coordinates"),
        "plate": {"template": TEMPLATE.name, "width": W, "depth": D, "thickness": T,
                  "extent_xy": [0, 0, W, D]},
        "paper": {"size": [PAPER_W, PAPER_H], "rect_xy": [round(v, 3) for v in PAPER],
                  "margin_side": round(SIDE_M, 3), "margin_end": round(END_M, 3),
                  "centred": True},
        "cap": {"wall": WALL, "clearance": CLEAR, "reach": CAP, "slot": SLOT,
                "height_above_paper": HEIGHT_ABOVE_PAPER, "top_z": CAP_TOP,
                "footprint_xy_bl": [EDGE_O, EDGE_O, CAP, CAP],
                "footprint_size": round(FOOT, 3),
                "inlay_depth": INLAY_DEPTH, "cell": CELL, "print_orientation": "top face down"},
        "footprint_assembled": [round(W + 2 * (WALL + CLEAR), 3), round(D + 2 * (WALL + CLEAR), 3)],
        "dictionary": DICTIONARY,
        "marker_black_size": 6 * CELL,
        "markers": {},
    }
    for k in range(4):
        cx, cy = marker_center(k)
        layout["markers"][str(k)] = {
            "corner": CORNER_NAMES[k],
            "center": [round(cx, 3), round(cy, 3)],
            "top_z": CAP_TOP,
            "cap_xy": [round(v, 3) for v in mirror_box(cap_boxes_bl()[0], *CORNER_FLIP[k])[:4]],
        }
    (HERE / "layout.json").write_text(json.dumps(layout, indent=2), encoding="utf-8")


# ---- previews -----------------------------------------------------------------
def load_font(size):
    from PIL import ImageFont
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def write_preview_top(path, caps):
    from PIL import Image, ImageDraw
    S = 3.0                       # px per mm
    pad = 14.0
    ex0, ey0 = EDGE_O - pad, EDGE_O - pad
    ex1, ey1 = W + WALL + CLEAR + pad, D + WALL + CLEAR + pad
    head, foot = 64, 130
    body_w = (ex1 - ex0) * S
    body_h = (ey1 - ey0) * S
    img = Image.new("RGB", (int(round(body_w)), int(round(body_h + head + foot))), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f_big, f_small = load_font(18), load_font(15)

    def px(x, y):
        return ((x - ex0) * S, head + (ey1 - y) * S)

    def rect(b, **kw):
        a, c = px(b[0], b[3]), px(b[2], b[1])
        d.rectangle([round(a[0]), round(a[1]), round(c[0]), round(c[1])], **kw)

    d.text((10, 8), "Paper corner caps - top view, plate coordinates (+X right, +Y up)",
           fill=(0, 0, 0), font=f_big)
    d.text((10, 34), f"grey = plate: {W:g} x {D:g} x {T:g} plate (template)   "
                     f"white = paper: US Letter {PAPER_W} x {PAPER_H}",
           fill=(60, 60, 60), font=f_small)

    rect((0, 0, W, D), fill=(214, 214, 214), outline=(140, 140, 140))
    rect(PAPER, fill=(255, 255, 255), outline=(110, 110, 110))
    for k, c in caps.items():
        mx, my = CORNER_FLIP[k]
        sx0, sy0, sx1, sy1 = mirror_box(cap_boxes_bl()[0], mx, my)[:4]
        rect((sx0, sy0, sx1, sy1), fill=(92, 120, 148), outline=(50, 70, 90))
        cx, cy = marker_center(k)
        rect((cx - SPOT / 2, cy - SPOT / 2, cx + SPOT / 2, cy + SPOT / 2), fill="white")
        for x0, y0, x1, y1 in black_cells(k, cx - SPOT / 2, cy - SPOT / 2):
            rect((x0, y0, x1, y1), fill="black")
        lx = (W - EDGE_O + 2) if mx else (EDGE_O - 2)
        ly = (D - EDGE_O + 2) if my else (EDGE_O - 2)
        lp = px(lx, ly)
        d.text(lp, f"id {k}", fill=(0, 0, 0), font=f_small,
               anchor=("l" if mx else "r") + "m")

    base = head + body_h
    d.text((10, base + 8), f"Caps (blue-grey, 4 corners): {FOOT:.1f} x {FOOT:.1f} mm footprint, "
                           f"WALL {WALL:g} + CLEAR {CLEAR:g} per side, reach {CAP:g} mm, "
                           f"top z = {CAP_TOP:g}",
           fill=(0, 0, 0), font=f_small)
    d.text((10, base + 30), f"Assembled footprint {W + 2 * (WALL + CLEAR):.1f} x "
                            f"{D + 2 * (WALL + CLEAR):.1f} mm. Markers: {DICTIONARY}, black square "
                            f"{6 * CELL:g} mm, ids 0 BL, 1 BR, 2 TR, 3 TL.",
           fill=(0, 0, 0), font=f_small)
    # 100 mm scale bar
    bx, by = 10, base + 66
    d.rectangle([bx, by, bx + 100 * S, by + 6], fill=(0, 0, 0))
    d.rectangle([bx + 100 * S / 2, by, bx + 100 * S, by + 6], fill=(255, 255, 255), outline=(0, 0, 0))
    d.text((bx, by + 12), "0", fill=(0, 0, 0), font=f_small)
    d.text((bx + 100 * S, by + 12), "100 mm", fill=(0, 0, 0), font=f_small, anchor="ma")
    img.save(path)


def _project_setup():
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


def write_preview_iso(path, plate_tris, paper_tris, cap_body, cap_black):
    from PIL import Image, ImageDraw
    c, basis, light = _project_setup()
    layers = [
        (_tri_array(plate_tris), (205, 205, 205), False),
        (_tri_array(paper_tris), (252, 252, 246), False),
        (np.concatenate([_tri_array(t) for t in cap_body]), (92, 120, 148), True),
        (np.concatenate([_tri_array(t) for t in cap_black]), (22, 22, 22), True),
    ]
    prepared = []
    for tris, base_col, sort in layers:
        n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        ln = np.linalg.norm(n, axis=1)
        ok = (ln > 1e-9) & ((n @ c) > 0)            # back-face culling
        tris, n, ln = tris[ok], n[ok], ln[ok]
        n = n / ln[:, None]
        depth = tris.mean(axis=1) @ c
        order = np.argsort(depth) if sort else np.arange(len(tris))   # far first
        inten = 0.45 + 0.55 * np.clip(n @ light, 0, None)
        cols = np.clip(np.array(base_col)[None, :] * inten[:, None], 0, 255).astype(int)
        prepared.append((tris[order] @ basis, cols[order]))

    allp = np.concatenate([p.reshape(-1, 2) for p, _ in prepared])
    mn, mx = allp.min(axis=0), allp.max(axis=0)
    W_IMG, M = 1200, 30
    scale = (W_IMG - 2 * M) / (mx[0] - mn[0])
    H_IMG = int(round((mx[1] - mn[1]) * scale + 2 * M))
    img = Image.new("RGB", (W_IMG, H_IMG), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for p2, cols in prepared:
        for tri, col in zip(p2, cols):
            poly = [((x - mn[0]) * scale + M, H_IMG - ((y - mn[1]) * scale + M)) for x, y in tri]
            fill = tuple(int(v) for v in col)
            d.polygon(poly, fill=fill, outline=fill)
    d.text((M, 8), "Isometric: plate (grey), paper (white sheet), caps (blue-grey) with "
                   "ArUco black top layer", fill=(40, 40, 40), font=load_font(16))
    img.save(path)


def write_cap_section(path):
    from PIL import Image, ImageDraw
    S = 8.0                         # px per mm
    xmin, xmax = -8.0, 60.0
    zmin, zmax = -6.0, 28.0
    left, top = 130, 64
    width = int((xmax - xmin) * S) + left + 430
    height = int((zmax - zmin) * S) + top + 40
    img = Image.new("RGB", (width, height), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f, fs = load_font(16), load_font(14)

    def P(x, z):
        return (left + (x - xmin) * S, top + (zmax - z) * S)

    def rect(x0, z0, x1, z1, **kw):
        a, b = P(x0, z1), P(x1, z0)
        d.rectangle([round(a[0]), round(a[1]), round(b[0]), round(b[1])], **kw)

    def dim_h(x0, x1, z, label, anchor="mm", dx=0, dz=0):
        a, b = P(x0, z), P(x1, z)
        d.line([a, b], fill=(30, 30, 30), width=1)
        for p in (a, b):
            d.line([p[0], p[1] - 5, p[0], p[1] + 5], fill=(30, 30, 30))
        tx = (a[0] + b[0]) / 2 if anchor == "mm" else (b[0] if anchor[0] == "l" else a[0])
        d.text((tx + dx, a[1] + dz), label, fill=(30, 30, 30), font=fs, anchor=anchor)

    def dim_v(z0, z1, x, label, anchor="lm", dx=0):
        a, b = P(x, z0), P(x, z1)
        d.line([a, b], fill=(30, 30, 30))
        for p in (a, b):
            d.line([p[0] - 5, p[1], p[0] + 5, p[1]], fill=(30, 30, 30))
        d.text(((a[0] + b[0]) / 2 + dx, (a[1] + b[1]) / 2), label, fill=(30, 30, 30),
               font=fs, anchor=anchor)

    d.text((10, 10), f"Cross-section through cap id 0 at y = {CAP / 2:g} (looking +Y), "
                     f"z up, 8 px/mm", fill=(0, 0, 0), font=f)

    # Plate: x 0..50, z 0..T
    rect(0, 0, 50, T, fill=(205, 205, 205), outline=(120, 120, 120))
    d.text(P(25, T / 2), "plate (z 0..T)", fill=(30, 30, 30), font=fs, anchor="mm")
    # Paper sheet on the plate top, starting SIDE_M inside the plate edge (0.1 mm drawn 3 px)
    a, b = P(SIDE_M, T + 0.1), P(50, T)
    d.rectangle([round(a[0]), round(a[1]), round(b[0]), round(b[1]) + 1],
                fill=(255, 255, 255), outline=(60, 60, 60))
    # Cap: L-wall (x -3.2..-0.2, z 0..20) plus top (x -0.2..38, z T+SLOT..20)
    cap_poly = [P(EDGE_O, 0), P(-CLEAR, 0), P(-CLEAR, SLOT_TOP), P(CAP, SLOT_TOP),
                P(CAP, CAP_TOP), P(EDGE_O, CAP_TOP)]
    d.polygon(cap_poly, fill=(92, 120, 148), outline=(50, 70, 90))
    d.text(P(18, 15.3), "cap", fill=(255, 255, 255), font=fs, anchor="mm")
    # Dimensions
    dim_h(EDGE_O, -CLEAR, -2.2, f"WALL {WALL:g}", anchor="rm", dx=-8)
    dim_h(-CLEAR, 0, -4.8, f"CLEAR {CLEAR:g}", anchor="lm", dx=12)
    dim_v(T, SLOT_TOP, CAP + 2.5, "", anchor="lm")
    d.text(P(52, T + 0.3), f"SLOT {SLOT:g} (paper tucks in here)", fill=(30, 30, 30), font=fs,
           anchor="lm")
    d.text(P(52, 8.0), f"paper (on plate top, inset {SIDE_M:.2f} from edge)", fill=(30, 30, 30),
           font=fs, anchor="lm")
    dim_v(T, CAP_TOP, CAP + 6, "", anchor="lm")
    d.text(P(CAP + 8, 16.5), f"{HEIGHT_ABOVE_PAPER:g} mm above paper", fill=(30, 30, 30), font=fs,
           anchor="lm")
    d.text(P(CAP + 8, 14.7), f"(cap top z = T + {HEIGHT_ABOVE_PAPER:g} = {CAP_TOP:g})",
           fill=(30, 30, 30), font=fs, anchor="lm")
    dim_h(0, CAP, 24.2, f"CAP reach {CAP:g} mm from plate edge", anchor="mm", dz=-14)
    d.text((10, height - 26), "Paper is drawn 0.1 mm thick for visibility; sheet sits on the plate "
                              "top inside the 0.6 mm slot. z = 0 is the plate bottom.",
           fill=(60, 60, 60), font=fs)
    img.save(path)


# ---- main ---------------------------------------------------------------------
def main():
    caps = {k: build_cap(k) for k in range(4)}
    write_stls(caps)
    write_layout(caps)

    plate_tris = mesh([(0.0, 0.0, W, D, 0.0, T)])
    paper_tris = mesh([(PAPER[0], PAPER[1], PAPER[2], PAPER[3], T, T + 0.1)])
    write_preview_top(HERE / "preview_top.png", caps)
    write_preview_iso(HERE / "preview_iso.png", plate_tris, paper_tris,
                      [caps[k]["body"] for k in range(4)],
                      [caps[k]["black"] for k in range(4)])
    write_cap_section(HERE / "preview_cap_section.png")
    print(f"plate {W:g} x {D:g} x {T:g}; assembled footprint "
          f"{W + 2 * (WALL + CLEAR):.1f} x {D + 2 * (WALL + CLEAR):.1f} mm")


if __name__ == "__main__":
    main()
