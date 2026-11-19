#!/usr/bin/env python3
"""Parametric paper-holding plate with 4 corner stops and ArUco marker spots.

Outputs (in this folder):
  paper_plate.stl            plate + 4 L corner walls + square sticker pockets for markers
  paper_plate_inlay.stl      same plate, but marker black cells recessed (multi-tool print)
  aruco_inlay_black.stl      black marker cells that fill those recesses (2nd filament)
  aruco_markers.svg          markers at exact mm scale; print at 100% and stick in pockets
  aruco_layout.json          marker IDs/centres in paper coordinates for camera calibration
  preview.png                top view

Coordinates: origin = bottom-left corner of the paper, +X right, +Y up (top view), mm.
Only numpy is needed. Every solid is axis-aligned boxes, meshed exactly on a grid,
so the STL is watertight with no CSG library.
Run: python make_paper_plate.py
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

# ---- parameters -------------------------------------------------------------
PAPER_W, PAPER_H = 215.9, 279.4   # US Letter. A4: 210 x 297
CLEAR = 0.5          # gap between paper edge and corner wall
WALL_T = 10.0        # corner wall thickness ("1 cm")
WALL_L = 35.0        # corner leg length, measured from the outer corner
WALL_H = 3.0         # wall height above plate top (pen-up travel must clear this)
PLATE_T = 4.0
EDGE = 3.0           # plate border outside everything
CELL = 4.0           # ArUco cell size: 6 cells = 24 mm black square
QUIET = 1            # white quiet-zone cells around each marker
GAP = 3.0            # marker spot to corner wall
STICKER_DEPTH = 0.4  # locating pocket for a paper sticker
STICKER_CLEAR = 0.2
INLAY_DEPTH = 0.6    # 3 layers at 0.2 mm

# DICT_4X4_50 ids 0-3, inner 4x4 bits row-major from the top, 1 = white.
# Generated with cv2.aruco.generateImageMarker (opencv-contrib 4.10.0).
ARUCO = {0: "1011010100110010", 1: "0000111110011010",
         2: "0011001100101101", 3: "1001100101000110"}
DICTIONARY = "DICT_4X4_50"

# ---- layout -----------------------------------------------------------------
SPOT = (6 + 2 * QUIET) * CELL                   # white square incl. quiet zone
SIDE = CLEAR + WALL_T + GAP + SPOT + EDGE       # x margin (markers sit left/right)
END = CLEAR + WALL_T + EDGE                     # y margin
PLATE = (-SIDE, -END, PAPER_W + SIDE, PAPER_H + END)
TOP = PLATE_T


def corner_walls():
    boxes = []
    o = CLEAR + WALL_T
    for cx, sx in ((0, -1), (PAPER_W, 1)):
        for cy, sy in ((0, -1), (PAPER_H, 1)):
            ox, oy = cx + sx * o, cy + sy * o          # outer corner
            ix, iy = cx + sx * CLEAR, cy + sy * CLEAR  # inner face
            lx, ly = ox - sx * WALL_L, oy - sy * WALL_L
            boxes.append((min(ox, ix), min(oy, ly), max(ox, ix), max(oy, ly), TOP, TOP + WALL_H))
            boxes.append((min(ox, lx), min(oy, iy), max(ox, lx), max(oy, iy), TOP, TOP + WALL_H))
    return boxes


def marker_spots():
    """ids: 0 bottom-left, 1 bottom-right, 2 top-right, 3 top-left (counter-clockwise)."""
    x_left = -(CLEAR + WALL_T + GAP + SPOT)
    x_right = PAPER_W + CLEAR + WALL_T + GAP
    y_bot, y_top = -CLEAR, PAPER_H + CLEAR - SPOT
    return {0: (x_left, y_bot), 1: (x_right, y_bot), 2: (x_right, y_top), 3: (x_left, y_top)}


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


# ---- exact grid mesher ------------------------------------------------------
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


def write_svg(spots, path):
    w = PAPER_W
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{SPOT + 20}mm" '
             f'viewBox="0 0 {w} {SPOT + 20}">', '<rect width="100%" height="100%" fill="white"/>']
    for n, mid in enumerate(sorted(spots)):
        ox = 6 + n * (SPOT + 8)
        parts.append(f'<rect x="{ox}" y="4" width="{SPOT}" height="{SPOT}" fill="none" '
                     f'stroke="#bbb" stroke-width=".2" stroke-dasharray="1 1"/>')
        for x, y, x1, y1 in black_cells(mid, 0, 0):
            # SVG y points down: flip within the spot.
            parts.append(f'<rect x="{ox + x:.3f}" y="{4 + SPOT - y1:.3f}" '
                         f'width="{x1 - x:.3f}" height="{y1 - y:.3f}" fill="black"/>')
        parts.append(f'<text x="{ox}" y="{SPOT + 10}" font-size="3.5" font-family="sans-serif">'
                     f'id {mid} ({DICTIONARY}) cut on dashed line</text>')
    parts.append(f'<text x="6" y="{SPOT + 16}" font-size="3" font-family="sans-serif">'
                 f'Print at 100% / actual size. Black square must measure {6 * CELL:.0f} mm.</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def write_preview(add_walls, spots, path):
    from PIL import Image, ImageDraw
    s = 3
    x0, y0, x1, y1 = PLATE
    img = Image.new("RGB", (int((x1 - x0) * s) + 1, int((y1 - y0) * s) + 1), (235, 235, 235))
    d = ImageDraw.Draw(img)

    def R(b, **kw):
        d.rectangle([(b[0] - x0) * s, (y1 - b[3]) * s, (b[2] - x0) * s, (y1 - b[1]) * s], **kw)

    R((0, 0, PAPER_W, PAPER_H), fill=(255, 255, 250), outline=(150, 150, 150))
    for b in add_walls:
        R(b, fill=(70, 110, 170))
    for mid, (sx, sy) in spots.items():
        R((sx, sy, sx + SPOT, sy + SPOT), fill="white", outline=(120, 120, 120))
        for c in black_cells(mid, sx, sy):
            R(c, fill="black")
    img.save(path)


def main():
    plate = (*PLATE[:2], *PLATE[2:], 0.0, PLATE_T)
    walls = corner_walls()
    spots = marker_spots()
    sticker = [(sx - STICKER_CLEAR / 2, sy - STICKER_CLEAR / 2,
                sx + SPOT + STICKER_CLEAR / 2, sy + SPOT + STICKER_CLEAR / 2,
                TOP - STICKER_DEPTH, TOP + 1) for sx, sy in spots.values()]
    cells = [(*c, TOP - INLAY_DEPTH, TOP) for mid, (sx, sy) in spots.items()
             for c in black_cells(mid, sx, sy)]
    cell_recess = [(*c[:4], c[4], TOP + 1) for c in cells]

    outputs = {
        "paper_plate.stl": mesh([plate, *walls], sticker),
        "paper_plate_inlay.stl": mesh([plate, *walls], cell_recess),
        "aruco_inlay_black.stl": mesh(cells),
    }
    for name, tris in outputs.items():
        write_stl(HERE / name, tris)
        print(f"{name}: {len(tris)} tris, open/nonmanifold edges, volume cm3 = {check(tris)}")

    write_svg(spots, HERE / "aruco_markers.svg")
    layout = {
        "units": "mm", "origin": "paper bottom-left corner, +X right, +Y up (top view)",
        "paper": [PAPER_W, PAPER_H], "dictionary": DICTIONARY,
        "marker_black_size": 6 * CELL, "marker_surface_z": TOP,
        "markers": {str(mid): {"center": [round(sx + SPOT / 2, 3), round(sy + SPOT / 2, 3)]}
                    for mid, (sx, sy) in spots.items()},
        "plate_extent": [round(v, 3) for v in PLATE], "plate_thickness": PLATE_T,
        "wall": {"thickness": WALL_T, "leg": WALL_L, "height": WALL_H, "clearance": CLEAR},
    }
    (HERE / "aruco_layout.json").write_text(json.dumps(layout, indent=2), encoding="utf-8")
    write_preview(walls, spots, HERE / "preview.png")
    print("plate size mm:", round(PLATE[2] - PLATE[0], 2), "x", round(PLATE[3] - PLATE[1], 2))


if __name__ == "__main__":
    main()
