"""Level-1 handwriting layout: style from your samples, glyph choice, text into regions, blank areas.

Units: glyph strokes are in letter-height units (one unit is a typical letter, as in handwriting.py),
so size_mm is the height of a typical letter. Page geometry is page mm, y down, the frame that
worksheet.py uses. Offline: numpy and OpenCV only.

Public API:
  learn_style(glyphs), load_glyphs(root), load_style(root), refresh_style(root)
  layout_text(text, region, size_mm, glyphs, style, seed)  -> paths, rows, size_mm, overflow
  detect_regions(rect_bgr)                                  -> ruled lines and empty boxes, ids
  draw_regions(rect_bgr, regions), to_svg(paths, data_p)
Region: box {"x","y","w","h"} (top-left, page mm) or ruled line {"x0","y0","x1","y1"} (text sits on
the line and rises above it; optional "rise_mm" allows extra rows upward).
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
PX = 4.0  # worksheet.py rectifies at 4 px/mm

DEFAULT_STYLE = {
    "x_height": 0.7, "ascender_ratio": 1.5, "descender_ratio": 0.45,
    "slant": 0.0, "letter_gap": 0.15, "word_gap": 0.6,
    "wobble": 0.03, "size_jitter": 0.05, "joins": [], "samples": 0,
}
LOWER = frozenset("acemnorsuvwxz")
ASC = frozenset("bdfhkl")
DESC = frozenset("gjpqy")
JOIN_GAP = 0.08    # units: adjacent samples this close count as connected
JOIN_REACH = 0.35  # units: draw a joining stroke only when the pen gap is this small


# ---------- style from labeled samples ----------

def learn_style(glyphs):
    """Stats from the user's labeled glyph records (glyphs.json). Lengths in letter-height units."""
    glyphs = list(glyphs)
    style = {**DEFAULT_STYLE, "joins": []}
    lab = [g for g in glyphs if g.get("char") and g.get("strokes")]
    if not lab:
        return style

    def med(chars, key, default):
        vals = [g[key] for g in lab if g["char"] in chars]
        return float(np.median(vals)) if vals else default

    xh = max(.2, med(LOWER, "height", DEFAULT_STYLE["x_height"]))
    style["x_height"] = round(xh, 3)
    # 90th percentile, not median: rows are spaced to clear the tall and deep letters
    asc_vals = [g["height"] for g in lab if g["char"] in ASC]
    desc_vals = [-g["bottom"] for g in lab if g["char"] in DESC]
    style["ascender_ratio"] = round(float(np.percentile(asc_vals, 90)) / xh, 3) if asc_vals else 1.5
    style["descender_ratio"] = round(max(0.0, float(np.percentile(desc_vals, 90))) / xh, 3) if desc_vals else .45
    style["slant"] = round(float(np.mean([g.get("slant", 0.0) for g in lab])), 3)

    by_line, joins, wob, gaps = {}, set(), [], []
    for g in glyphs:
        by_line.setdefault(g.get("line_id"), []).append(g)
    for items in by_line.values():
        items.sort(key=lambda g: g["bbox"][0])
        for a, b in zip(items, items[1:]):
            ref = a["bbox"][3] / a["height"] if a.get("height") else 1.0
            gap = (b["bbox"][0] - a["bbox"][0] - a["bbox"][2]) / ref
            gaps.append(gap)
            if a.get("char") and b.get("char") and gap < JOIN_GAP:
                joins.add(a["char"] + b["char"])
        vals = [g["bottom"] for g in items if g.get("char") in LOWER]
        if len(vals) >= 3:
            wob.append(float(np.std(vals)))
    if gaps:
        arr = np.array(gaps)
        mid = max(float(np.median(arr)), .05)
        small, big = arr[arr < 1.8 * mid], arr[arr >= 1.8 * mid]
        letter = max(0.0, float(np.median(small)) if small.size else mid)
        style["letter_gap"] = round(letter, 3)
        style["word_gap"] = round(max(float(np.median(big)) if big.size else 0.0, 3 * letter), 3)
    if wob:
        style["wobble"] = round(float(np.median(wob)), 3)
    by_char, res = {}, []
    for g in lab:
        by_char.setdefault(g["char"], []).append(g["height"])
    for vals in by_char.values():
        if len(vals) >= 2:
            mu = sum(vals) / len(vals)
            res += [v - mu for v in vals]
    if len(res) >= 4:
        style["size_jitter"] = round(float(np.std(res)), 3)
    style["joins"] = sorted(joins)
    style["samples"] = len({g["sample"] for g in glyphs})
    return style


def load_glyphs(root):
    path = Path(root) / "glyphs.json"
    return json.loads(path.read_text(encoding="utf-8")).get("glyphs", []) if path.exists() else []


def load_style(root):
    return learn_style(load_glyphs(root))


def refresh_style(root):
    """Learn from glyphs.json and save data/handwriting/style.json for inspection."""
    style = load_style(root)
    (Path(root) / "style.json").write_text(json.dumps(style, indent=1), encoding="utf-8")
    return style


# ---------- glyph choice ----------

def _fallback(ch):
    """Built-in single-stroke letter in unit height (cap = 1), width 0.6."""
    from worksheet import GLYPHS  # lazy: worksheet imports this module
    key = ch.upper()
    if key not in GLYPHS:
        raise ValueError(f"no glyph for {ch!r}: label it on handwriting.html or use A-Z, 0-9 and . , - _ : / ? + = ( )")
    return [[(x / 5, y / 5) for x, y in pl] for pl in GLYPHS[key]], 0.6, 0.0


class _Picker:
    """Random labeled sample per character; never the same sample twice in a row (unless only one exists)."""

    def __init__(self, glyphs, style, rng):
        self.by = {}
        for g in glyphs:
            if g.get("char") and g.get("strokes") and len(g["char"]) == 1:
                self.by.setdefault(g["char"], []).append(g)
        self.joins = set(style.get("joins", []))
        self.rng = rng
        self.last = None

    def pick(self, ch):
        """(strokes, width, slant, from_sample) for one character."""
        pool = self.by.get(ch, [])
        if pool:
            cand = [g for g in pool if g["id"] != self.last] or pool
            g = self.rng.choice(cand)
            self.last = g["id"]
            return g["strokes"], g["width"], g.get("slant", 0.0), True
        strokes, width, slant = _fallback(ch)
        self.last = None
        return strokes, width, slant, False


# ---------- text into a region ----------

def _frame(region):
    try:
        if "x0" in region:
            x0, y0, x1, y1 = (float(region[k]) for k in ("x0", "y0", "x1", "y1"))
            length = math.hypot(x1 - x0, y1 - y0)
            if length < 1:
                raise ValueError("ruled line is shorter than 1 mm")
            ux, uy = (x1 - x0) / length, (y1 - y0) / length
            return {"O": (x0, y0), "u": (ux, uy), "v": (uy, -ux), "W": length,
                    "H": float(region.get("rise_mm", 0.0)), "mode": "line"}
        x, y, w, h = (float(region[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError) as exc:
        raise ValueError("region needs x, y, w, h (a box) or x0, y0, x1, y1 (a ruled line)") from exc
    if w <= 0 or h <= 0:
        raise ValueError("box needs w > 0 and h > 0")
    return {"O": (x, y + h), "u": (1.0, 0.0), "v": (0.0, -1.0), "W": w, "H": h, "mode": "box"}


def _layout_once(text, fr, size, glyphs, style, seed):
    """Rows of frame-local polylines (along, up) at letter height `size`. Returns (rows, fits)."""
    rng = random.Random(seed)
    pick = _Picker(glyphs, style, rng)
    asc_u = style["ascender_ratio"] * style["x_height"]
    desc_u = style["descender_ratio"] * style["x_height"]
    asc, desc = asc_u * size, desc_u * size
    # row pitch clears ascenders and descenders even at the largest size jitter and wobble
    pitch = max(1.5, (asc_u + desc_u) * (1 + 3 * style["size_jitter"]) + 6 * style["wobble"] + .1) * size
    gap = style["letter_gap"] * size
    wgap = max(0.0, style["word_gap"] - style["letter_gap"]) * size
    wob = style["wobble"] * size
    pad = 3 * wob  # room for the baseline wobble at the top and bottom
    W, H = fr["W"], fr["H"]
    if fr["mode"] == "box":
        base_of = lambda r: H - asc - pad - r * pitch  # rows hang down from the top margin
    else:
        base_of = lambda r: r * pitch  # rows stack up from the line
    rows, cur, wob_v, fits = [[]], 0.0, 0.0, True
    for pi, para in enumerate(text.split("\n")):
        if pi:
            rows.append([])
            cur = 0.0
        for word in para.split():
            picks = []
            for ch in word:
                strokes, width, slant, sample = pick.pick(ch)
                sc = max(.8, rng.gauss(1, style["size_jitter"]))
                adv = width * sc * size + gap * max(.5, rng.gauss(1, .08))
                picks.append((ch, strokes, slant, sample, sc, adv))
            wlen = sum(p[5] for p in picks) - gap
            start = cur + (wgap if cur > 0 else 0.0)
            if cur > 0 and start + wlen > W:
                rows.append([])
                cur, start = 0.0, 0.0
            if start + wlen > W + 1e-9:
                fits = False
            b = base_of(len(rows) - 1)
            x, prev, pch = start, None, None
            for ch, strokes, slant, sample, sc, adv in picks:
                wob_v = .6 * wob_v + rng.gauss(0, .8 * wob)
                dy = b + wob_v
                polys = [[(x + (px + slant * py) * size * sc, dy + py * size * sc) for px, py in pl]
                         for pl in strokes]
                if sample and prev is not None and pch and (pch + ch) in pick.joins:
                    (ex, ey), (sx, sy) = prev, polys[0][0]
                    if math.hypot(sx - ex, sy - ey) <= JOIN_REACH * size:
                        rows[-1].append([prev, (sx, sy)])
                rows[-1].extend(polys)
                prev = polys[-1][-1] if sample else None
                pch = ch if sample else None
                x += adv
            cur = x
    n = len(rows)
    if fr["mode"] == "box":
        fits_v = (n - 1) * pitch + asc + desc + 2 * pad <= H + 1e-9
    else:
        fits_v = n == 1 or (n - 1) * pitch + asc + pad <= H + 1e-9
    return rows, fits and fits_v


def _to_page(fr, pl):
    (ox, oy), (ux, uy), (vx, vy) = fr["O"], fr["u"], fr["v"]
    return [(ox + a * ux + b * vx, oy + a * uy + b * vy) for a, b in pl]


def layout_text(text, region, size_mm=8.0, glyphs=(), style=None, seed=0, min_size_mm=3.0):
    """Lay text into a box or ruled line. Shrinks (bisects) the size until it fits, floor min_size_mm.

    Returns {"paths": [polyline in page mm], "rows": [[polyline]], "size_mm", "requested_mm",
    "overflow" (True when it does not fit even at the floor), "row_count"}. Same seed, same result.
    """
    text = str(text)
    if not text.strip():
        raise ValueError("empty text")
    glyphs = list(glyphs)
    style = style or learn_style(glyphs)
    fr = _frame(region)
    size = float(size_mm)
    floor = min(float(min_size_mm), size)
    rows, fits = _layout_once(text, fr, size, glyphs, style, seed)
    if not fits:
        low_rows, low_fits = _layout_once(text, fr, floor, glyphs, style, seed)
        if low_fits:
            lo, hi = floor, size
            for _ in range(14):
                mid = (lo + hi) / 2
                if _layout_once(text, fr, mid, glyphs, style, seed)[1]:
                    lo = mid
                else:
                    hi = mid
            size = lo
            rows, fits = _layout_once(text, fr, size, glyphs, style, seed)
        else:
            size, rows, fits = floor, low_rows, False
    row_paths = [[_to_page(fr, pl) for pl in row if len(pl) > 1] for row in rows]
    row_paths = [r for r in row_paths if r]
    return {"paths": [pl for r in row_paths for pl in r], "rows": row_paths,
            "size_mm": round(size, 2), "requested_mm": float(size_mm),
            "overflow": not fits, "row_count": len(row_paths)}


# ---------- rules and blank areas on a rectified page ----------

def detect_regions(rect, px_per_mm=PX):
    """Ruled lines (Hough, up to 15 degrees off horizontal) and empty boxes on a rectified page.

    Returns page-mm regions sorted top to bottom: {"id": "rule-1", "kind": "line", "x0","y0","x1","y1"}
    and {"id": "space-1", "kind": "box", "x","y","w","h"}. Boxes are free 4 mm cells bounded by ink and rules.
    ponytail: ids are by position only; matching "question 3" needs OCR, so read regions.png and pick an id.
    """
    gray = rect if rect.ndim == 2 else cv2.cvtColor(rect, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    px = px_per_mm
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    segs = cv2.HoughLinesP(cv2.Canny(blur, 40, 120), 1, np.pi / 720, threshold=int(8 * px),
                           minLineLength=int(20 * px), maxLineGap=int(1.5 * px))
    rules = []  # [angle_deg, y at page centre (px), x_min, x_max, count]
    for x1, y1, x2, y2 in ([] if segs is None else segs[:, 0]):
        if x2 < x1:
            x1, y1, x2, y2 = x2, y2, x1, y1
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
        if abs(ang) > 15:
            continue
        yc = y1 + (w / 2 - x1) * math.tan(math.radians(ang))
        for r in rules:
            if abs(r[0] - ang) < 2 and abs(r[1] - yc) < 1.5 * px:
                n = r[4]
                r[0], r[1] = (r[0] * n + ang) / (n + 1), (r[1] * n + yc) / (n + 1)
                r[2], r[3], r[4] = min(r[2], x1), max(r[3], x2), n + 1
                break
        else:
            rules.append([ang, yc, x1, x2, 1])
    rules.sort(key=lambda r: r[1])

    ink = (blur < 150).astype(np.uint8)
    block = cv2.dilate(ink, np.ones((int(2 * px) | 1, int(2 * px) | 1), np.uint8))
    regions = []
    for i, (ang, yc, x0, x1, _) in enumerate(rules, 1):
        t = math.tan(math.radians(ang))
        ya, yb = yc + (x0 - w / 2) * t, yc + (x1 - w / 2) * t
        # blocks the full page width so free space cannot leak around a rule's end into the margin
        cv2.line(block, (0, round(yc - w / 2 * t)), (w, round(yc + w / 2 * t)), 1, max(1, int(1.5 * px)))
        regions.append({"id": f"rule-{i}", "kind": "line", "x0": round(x0 / px, 2), "y0": round(ya / px, 2),
                        "x1": round(x1 / px, 2), "y1": round(yb / px, 2)})

    cell = int(4 * px)
    R, C = h // cell, w // cell
    blocked = block[:R * cell, :C * cell].reshape(R, cell, C, cell).mean(axis=(1, 3)) > .01
    n, _, st, _ = cv2.connectedComponentsWithStats((~blocked).astype(np.uint8), 8)
    spaces = []
    for i in range(1, n):
        x, y, cw, ch, area = (int(v) for v in st[i])
        if area < .85 * cw * ch or cw * 4 < 15 or ch * 4 < 6:
            continue
        spaces.append({"kind": "box", "x": x * 4.0, "y": y * 4.0, "w": cw * 4.0, "h": ch * 4.0})
    spaces.sort(key=lambda r: (r["y"], r["x"]))
    for i, s in enumerate(spaces, 1):
        s["id"] = f"space-{i}"
        regions.append(s)
    regions.sort(key=lambda r: r["y0"] if r["kind"] == "line" else r["y"])
    return regions


def draw_regions(rect, regions, px_per_mm=PX):
    """BGR copy of the rectified page with rules (green) and empty boxes (blue) labelled by id."""
    img = rect.copy() if rect.ndim == 3 else cv2.cvtColor(rect, cv2.COLOR_GRAY2BGR)
    for r in regions:
        if r["kind"] == "line":
            p0 = (round(r["x0"] * px_per_mm), round(r["y0"] * px_per_mm))
            p1 = (round(r["x1"] * px_per_mm), round(r["y1"] * px_per_mm))
            cv2.line(img, p0, p1, (0, 160, 0), 2)
            cv2.putText(img, r["id"], (p0[0], p0[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 160, 0), 2)
        else:
            x0, y0 = round(r["x"] * px_per_mm), round(r["y"] * px_per_mm)
            cv2.rectangle(img, (x0, y0), (round((r["x"] + r["w"]) * px_per_mm), round((r["y"] + r["h"]) * px_per_mm)),
                          (255, 120, 0), 2)
            cv2.putText(img, r["id"], (x0 + 6, y0 + 24), cv2.FONT_HERSHEY_SIMPLEX, .6, (255, 120, 0), 2)
    return img


def to_svg(paths, data_p=None):
    """SVG in page mm with no shift, one <path d="M x,y L ..."/> per polyline (davinci_draw.parse_svg shape).
    data_p: optional pen pressure 0..1 written on every path."""
    pts = [p for pl in paths for p in pl]
    if pts:
        x0 = min(x for x, _ in pts) - 5
        y0 = min(y for _, y in pts) - 5
        w = max(x for x, _ in pts) - x0 + 5
        h = max(y for _, y in pts) - y0 + 5
    else:
        x0, y0, w, h = 0.0, 0.0, 10.0, 10.0
    attr = f' data-p="{data_p:g}"' if data_p is not None else ""
    d = "".join('<path d="M' + " L".join(f"{x:.3f},{y:.3f}" for x, y in pl) + f'"{attr}/>'
                for pl in paths if len(pl) > 1)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.1f}mm" height="{h:.1f}mm" '
            f'viewBox="{x0:.3f} {y0:.3f} {w:.3f} {h:.3f}">'
            f'<g fill="none" stroke="#000" stroke-width=".3">{d}</g></svg>')
