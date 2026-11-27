"""My handwriting: harvest glyphs from notebook photos, label them, read them, write text in them.

Offline. Used by app.py under /api/handwriting/*. Never touches the machine.
Storage (data/handwriting/, gitignored):
  samples/<id>.<ext>      original photo, untouched
  samples/<id>_page.png   deskewed page the glyph boxes refer to
  index.json              sample list
  glyphs.json             lines and glyph candidates (strokes in units of the line's letter height)
  last_render.svg         last render, for tools/lily_run.py
"""
from __future__ import annotations

import base64
import binascii
import importlib.util
import io
import json
import os
import random
import shutil
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from worksheet import GLYPHS  # noqa: E402  built-in single-stroke font: 3x5 units, y up

CLAUDE_MODEL = "claude-sonnet-5-5"
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
MAX_SIDE = 2000  # working resolution: long side in px


class OcrUnavailable(Exception):
    pass


# ---------- page -> glyphs ----------

def zhang_suen(mask):
    """Zhang-Suen thinning on a 0/1 uint8 array. Same rules as tools/trace_lines.py."""
    im = (mask > 0).astype(np.uint8)
    while True:
        changed = False
        for step in (0, 1):
            p = np.pad(im, 1)
            P = [p[0:-2, 1:-1], p[0:-2, 2:], p[1:-1, 2:], p[2:, 2:],
                 p[2:, 1:-1], p[2:, 0:-2], p[1:-1, 0:-2], p[0:-2, 0:-2]]
            B = sum(P)
            A = sum(((P[i] == 0) & (P[(i + 1) % 8] == 1)).astype(int) for i in range(8))
            if step == 0:
                c = (P[0] * P[2] * P[4] == 0) & (P[2] * P[4] * P[6] == 0)
            else:
                c = (P[0] * P[2] * P[6] == 0) & (P[0] * P[4] * P[6] == 0)
            rm = (im == 1) & (B >= 2) & (B <= 6) & (A == 1) & c
            if rm.any():
                im[rm] = 0
                changed = True
        if not changed:
            return im


def skeleton_polylines(sk, min_len=6):
    """Walk 1px skeleton into pixel paths (row, col), like tools/trace_lines.py."""
    pts = {(int(r), int(c)) for r, c in zip(*np.nonzero(sk))}
    N = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]

    def nb(q):
        return [(q[0] + a, q[1] + b) for a, b in N if (q[0] + a, q[1] + b) in pts]

    paths = []
    while pts:
        start = next((q for q in pts if len(nb(q)) == 1), next(iter(pts)))
        path = [start]
        pts.discard(start)
        while True:
            c = nb(path[-1])
            if not c:
                break
            if len(path) > 1:
                d = (path[-1][0] - path[-2][0], path[-1][1] - path[-2][1])
                c.sort(key=lambda q: -((q[0] - path[-1][0]) * d[0] + (q[1] - path[-1][1]) * d[1]))
            path.append(c[0])
            pts.discard(c[0])
        if len(path) >= min_len:
            paths.append(path)
    return paths


def ink_mask(gray):
    """Dark handwriting as 255 on 0. Ruled notebook lines are long and straight, so they are removed."""
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    ink = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 41, 15)
    h, w = ink.shape
    hl = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, w // 10), 1)))
    vl = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, h // 6))))
    ink = cv2.subtract(ink, cv2.bitwise_or(hl, vl))
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink, 8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= 12  # specks
    return np.where(keep[lab], 255, 0).astype(np.uint8)


def estimate_skew(ink):
    """Angle (degrees) that makes text rows sharpest: maximise variance of the row sums."""
    if not ink.any():
        return 0.0
    h, w = ink.shape

    def score(a):
        r = cv2.warpAffine(ink, cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0), (w, h))
        return float(np.var(r.sum(axis=1, dtype=np.float64)))

    best = max(np.arange(-12, 12.01, .5), key=score)
    return float(max(np.arange(best - .5, best + .51, .1), key=score))


def _line_runs(ink):
    """Row bands that contain ink: (top, bottom) pairs, bottom exclusive."""
    prof = (ink > 0).sum(axis=1).astype(float)
    if not prof.any():
        return []
    k = max(5, ink.shape[0] // 150)
    smooth = np.convolve(prof, np.ones(k) / k, mode="same")
    on = (smooth > max(1.0, .03 * smooth.max())).astype(int)
    d = np.diff(np.concatenate([[0], on, [0]]))
    runs = zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0])
    return [(int(s), int(e)) for s, e in runs if e - s >= 12]


def _merge_overlaps(comps, st):
    """Group components that share most of their x-range (i dots, t bars, broken letters)."""
    order = sorted(comps, key=lambda i: st[i, 0])
    parent = {i: i for i in order}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for ai, a in enumerate(order):
        ax, aw = int(st[a, 0]), int(st[a, 2])
        for b in order[ai + 1:]:
            bx, bw = int(st[b, 0]), int(st[b, 2])
            if bx >= ax + aw:
                break
            if min(ax + aw, bx + bw) - bx > .5 * min(aw, bw):
                parent[find(a)] = find(b)
    groups = {}
    for i in order:
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def harvest(arr, sid):
    """BGR/gray photo -> (deskewed gray page, line records, glyph records). Strokes are unit-height."""
    gray = arr if arr.ndim == 2 else cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    f = min(1.0, MAX_SIDE / max(gray.shape))
    if f < 1:
        gray = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    ink = ink_mask(gray)
    f = min(1.0, 800 / max(gray.shape))
    angle = estimate_skew(cv2.resize(ink, None, fx=f, fy=f, interpolation=cv2.INTER_AREA))
    if abs(angle) >= .05:
        h, w = gray.shape
        gray = cv2.warpAffine(gray, cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0), (w, h), borderValue=255)
        ink = ink_mask(gray)
    page = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)

    n, lab, st, _ = cv2.connectedComponentsWithStats(ink, 8)
    lines, glyphs = [], []
    for top, bottom in _line_runs(ink):
        comps = [i for i in range(1, n) if top <= st[i, 1] + st[i, 3] / 2 < bottom]
        groups = _merge_overlaps(comps, st)
        if not groups:
            continue
        boxes = []
        for members in groups:
            x0 = int(min(st[c, 0] for c in members))
            y0 = int(min(st[c, 1] for c in members))
            x1 = int(max(st[c, 0] + st[c, 2] for c in members))
            y1 = int(max(st[c, 1] + st[c, 3] for c in members))
            boxes.append((x0, y0, x1 - x0, y1 - y0))
        ref = float(np.median([b[3] for b in boxes]))  # letter height in px: the unit for this line
        base = float(np.median([b[1] + b[3] for b in boxes if b[3] >= .6 * ref]))  # baseline in px
        lid = f"{sid}.{len(lines)}"
        for members, box in zip(groups, boxes):
            x0, y0, w, h = box
            mask = np.isin(lab[y0:y0 + h, x0:x0 + w], members).astype(np.uint8)
            glyphs.append(_glyph_record(sid, f"{sid}.{len(glyphs)}", lid, box, mask, ref, base))
        lines.append({"id": lid, "sample": sid, "bbox": [min(b[0] for b in boxes), min(b[1] for b in boxes),
                                                         max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)],
                      "text": ""})
    return page, lines, glyphs


def _glyph_record(sid, gid, lid, box, mask, ref, base):
    x0, y0, w, h = box
    sk = zhang_suen(np.pad(mask, 1))
    strokes = []
    for path in skeleton_polylines(sk):
        pts = np.array([[c - 1, r - 1] for r, c in path], np.float32)  # back to mask coordinates
        if len(pts) > 2:
            pts = cv2.approxPolyDP(pts, .7, False)[:, 0]
        strokes.append([[round(float(px) / ref, 3), round((base - (y0 + float(py))) / ref, 3)] for px, py in pts])
    if not strokes:  # a lone dot: keep a tiny mark so it can still be drawn
        yu = round((base - (y0 + h / 2)) / ref, 3)
        strokes = [[[round(w / 2 / ref, 3), yu], [round(w / 2 / ref + .02, 3), yu]]]
    M = cv2.moments(mask, binaryImage=True)
    slant = -M["mu11"] / M["mu02"] if M["mu02"] > 1e-6 else 0.0  # x per unit height, lean right = positive
    return {"id": gid, "sample": sid, "line_id": lid, "bbox": [int(x0), int(y0), int(w), int(h)],
            "char": "", "source": "", "height": round(h / ref, 3), "width": round(w / ref, 3),
            "bottom": round((base - (y0 + h)) / ref, 3), "slant": round(float(np.clip(slant, -.6, .6)), 3),
            "strokes": strokes}


# ---------- labels ----------

def align(text, glyphs):
    """Label glyphs (already sorted left to right) with the non-space characters of text.

    Equal counts map 1:1 ('aligned'). Otherwise glyphs are spread across the characters by
    position and marked 'guess' so the user knows to check them.
    ponytail: no width/shape matching; add it if guesses are common.
    """
    chars = [c for c in text if not c.isspace()]
    for g in glyphs:
        g["char"], g["source"] = "", ""
    n, m = len(chars), len(glyphs)
    if not n or not m:
        return
    for j, g in enumerate(glyphs):
        if n == m:
            k, src = j, "aligned"
        else:
            k, src = round(j * (n - 1) / max(m - 1, 1)), "guess"
        g["char"], g["source"] = chars[k], src


def variation(glyphs):
    """Spread of size, baseline and slant across the user's own samples of the same character."""
    by = {}
    for g in glyphs:
        if g.get("char"):
            by.setdefault(g["char"], []).append(g)
    res = {"height": [], "bottom": [], "slant": []}
    for items in by.values():
        if len(items) < 2:
            continue
        for key in res:
            vals = [g[key] for g in items]
            mu = sum(vals) / len(vals)
            res[key] += [v - mu for v in vals]

    def sd(xs, default):
        return float(np.std(xs)) if len(xs) >= 4 else default
    return {"height": sd(res["height"], .05), "bottom": sd(res["bottom"], .03), "slant": sd(res["slant"], .05)}


# ---------- text -> pen paths ----------

def render_text(text, size_mm=8.0, glyphs=(), seed=None):
    """Polylines in mm (y down, first baseline one letter below the top).

    Each character uses a random labeled sample of the user's hand, with small jitter in size,
    baseline and slant taken from the spread of their samples. Characters with no sample use the
    built-in font (A-Z, 0-9, punctuation; lowercase is drawn as uppercase).
    """
    rng = random.Random(seed)
    labeled = {}
    for g in glyphs:
        if g.get("char") and g.get("strokes"):
            labeled.setdefault(g["char"], []).append(g)
    var = variation(glyphs)
    out = []
    for li, line in enumerate(text.split("\n")):
        base = size_mm * (1 + 1.4 * li)
        pen = 0.0
        for ch in line:
            if ch == " ":
                pen += .8 * size_mm
            elif ch in labeled:
                g = rng.choice(labeled[ch])
                sc = max(.8, rng.gauss(1, var["height"]))
                dy = rng.gauss(0, var["bottom"]) * size_mm
                shear = g["slant"] + rng.gauss(0, var["slant"])
                for pl in g["strokes"]:
                    out.append([(pen + (x + shear * y) * size_mm * sc, base - y * size_mm * sc - dy) for x, y in pl])
                pen += (g["width"] * sc + .25) * size_mm
            else:
                key = ch.upper()
                if key not in GLYPHS:
                    raise ValueError(f"no glyph for {ch!r}: label it on handwriting.html or use A-Z, 0-9 and . , - _ : / ? + = ( )")
                s = size_mm / 5.0
                for pl in GLYPHS[key]:
                    out.append([(pen + gx * s, base - gy * s) for gx, gy in pl])
                pen += 4 * s
    return out


def to_svg(paths, margin=5.0):
    """SVG in mm, same <path d="M x,y L ..."> shape that tools/lily_run.py parses."""
    pts = [p for pl in paths for p in pl]
    if pts:
        minx = min(x for x, _ in pts)
        miny = min(y for _, y in pts)
        paths = [[(x - minx + margin, y - miny + margin) for x, y in pl] for pl in paths]
        w = max(x for x, _ in pts) - minx + 2 * margin
        h = max(y for _, y in pts) - miny + 2 * margin
    else:
        w = h = 2 * margin
    d = "".join('<path d="M' + " L".join(f"{x:.3f},{y:.3f}" for x, y in pl) + '"/>' for pl in paths if len(pl) > 1)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.1f}mm" height="{h:.1f}mm" viewBox="0 0 {w:.1f} {h:.1f}">'
            f'<g fill="none" stroke="#000" stroke-width=".3">{d}</g></svg>')


# ---------- OCR ----------

def read_text(raw, mime):
    """(text, backend). Tesseract if installed, else Claude if ANTHROPIC_API_KEY is set."""
    if shutil.which("tesseract") and importlib.util.find_spec("pytesseract") and importlib.util.find_spec("PIL"):
        import pytesseract
        from PIL import Image
        return pytesseract.image_to_string(Image.open(io.BytesIO(raw))).strip(), "tesseract"
    if os.environ.get("ANTHROPIC_API_KEY") and importlib.util.find_spec("anthropic"):
        import anthropic  # the SDK reads ANTHROPIC_API_KEY itself; no key is stored in code
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=4000,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime,
                                             "data": base64.b64encode(raw).decode("ascii")}},
                {"type": "text", "text": "Transcribe the handwritten text in this photo exactly as written, "
                                         "line by line. Output only the transcription."}]}])
        if msg.stop_reason == "refusal":
            raise OcrUnavailable("Claude declined to read this image.")
        return "\n".join(b.text for b in msg.content if b.type == "text").strip(), "anthropic"
    raise OcrUnavailable("No OCR backend configured: install pytesseract and tesseract, "
                         "or pip install anthropic and set ANTHROPIC_API_KEY.")


# ---------- storage + API payloads ----------

class Handwriting:
    def __init__(self, root):
        self.root = Path(root)
        self.samples_dir = self.root / "samples"
        self.samples_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()  # ponytail: one global lock, fine for one user

    def _read(self, name, default):
        path = self.root / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    def _write(self, name, obj):
        path = self.root / name
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)

    def _glyphs(self):
        return self._read("glyphs.json", {"lines": [], "glyphs": []})

    def samples(self):
        return self._read("index.json", {"samples": []})["samples"]

    def upload(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Expected an object")
        data = payload.get("data")
        if not isinstance(data, str) or not data:
            raise ValueError("Send the photo as base64 in 'data'")
        if data.startswith("data:"):
            data = data.split(",", 1)[-1]
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("'data' is not valid base64") from exc
        name = str(payload.get("filename") or "page.jpg")
        ext = Path(name).suffix.lower()
        if ext not in MIME:
            raise ValueError("Use a .jpg, .png or .webp photo (export HEIC photos as JPEG first)")
        arr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            raise ValueError("Could not read that image")
        with self.lock:
            index = self._read("index.json", {"samples": []})
            sid = 1 + max((s["id"] for s in index["samples"]), default=0)
            page, lines, glyphs = harvest(arr, sid)
            (self.samples_dir / f"{sid}{ext}").write_bytes(raw)
            cv2.imwrite(str(self.samples_dir / f"{sid}_page.png"), page)
            index["samples"].append({
                "id": sid, "file": f"{sid}{ext}", "filename": name,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "width": int(page.shape[1]), "height": int(page.shape[0]),
                "lines": len(lines), "glyphs": len(glyphs)})
            store = self._glyphs()
            store["lines"] += lines
            store["glyphs"] += glyphs
            self._write("glyphs.json", store)
            self._write("index.json", index)
        return {"id": sid, "lines": len(lines), "glyphs": len(glyphs)}

    def detail(self, sid):
        entry = next((s for s in self.samples() if s["id"] == sid), None)
        if entry is None:
            return None
        store = self._glyphs()
        return {
            "sample": entry,
            "lines": [{k: l[k] for k in ("id", "bbox", "text")} for l in store["lines"] if l["sample"] == sid],
            "glyphs": [{k: g[k] for k in ("id", "line_id", "bbox", "char", "source")}
                       for g in store["glyphs"] if g["sample"] == sid],
        }

    def page_png(self, sid):
        path = self.samples_dir / f"{sid}_page.png"
        return path.read_bytes() if path.exists() else None

    def transcribe(self, payload):
        line_id, text = (payload or {}).get("line"), (payload or {}).get("text")
        if not isinstance(line_id, str) or not isinstance(text, str) or len(text) > 200:
            raise ValueError("Send 'line' and 'text' (text up to 200 characters)")
        with self.lock:
            store = self._glyphs()
            line = next((l for l in store["lines"] if l["id"] == line_id), None)
            if line is None:
                raise ValueError("Unknown line")
            line["text"] = text
            gs = sorted((g for g in store["glyphs"] if g["line_id"] == line_id), key=lambda g: g["bbox"][0])
            align(text, gs)  # re-labels the whole line; re-do manual fixes after changing the text
            self._write("glyphs.json", store)
            return {"line": line, "labeled": sum(1 for g in gs if g["char"])}

    def label(self, payload):
        gid, ch = (payload or {}).get("glyph"), (payload or {}).get("char", "")
        if not isinstance(gid, str) or not isinstance(ch, str) or len(ch) > 1 or ch.isspace():
            raise ValueError("Send 'glyph' and 'char' (one character, or '' to clear)")
        with self.lock:
            store = self._glyphs()
            g = next((x for x in store["glyphs"] if x["id"] == gid), None)
            if g is None:
                raise ValueError("Unknown glyph")
            g["char"], g["source"] = ch, ("manual" if ch else "")
            self._write("glyphs.json", store)
        return {"glyph": {k: g[k] for k in ("id", "char", "source")}}

    def read(self, payload):
        sid = (payload or {}).get("id")
        entry = next((s for s in self.samples() if s["id"] == sid), None) if isinstance(sid, int) else None
        if entry is None:
            raise ValueError("Unknown sample id")
        raw = (self.samples_dir / entry["file"]).read_bytes()
        text, backend = read_text(raw, MIME[Path(entry["file"]).suffix.lower()])
        return {"backend": backend, "text": text}

    def render(self, payload):
        payload = payload or {}
        text, size = payload.get("text"), payload.get("size_mm", 8)
        if not isinstance(text, str) or not 1 <= len(text.strip()) or len(text) > 500:
            raise ValueError("Send 'text' (1 to 500 characters)")
        if isinstance(size, bool) or not isinstance(size, (int, float)) or not 2 <= size <= 40:
            raise ValueError("size_mm must be between 2 and 40")
        seed = payload.get("seed")
        seed = seed if isinstance(seed, int) and not isinstance(seed, bool) else None
        paths = render_text(text, float(size), self._glyphs()["glyphs"], seed=seed)
        svg = to_svg(paths)
        out = self.root / "last_render.svg"
        out.write_text(svg, encoding="utf-8")
        return {"svg": svg, "file": str(out)}
