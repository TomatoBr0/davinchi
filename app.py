#!/usr/bin/env python3
"""Offline handwriting sampler/composer. Preview-only G-code: NO machine control."""
from __future__ import annotations

import json
import math
import os
import random
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DB_PATH = Path(os.environ.get("DAVINCHI_DB", str(ROOT / "data" / "samples.sqlite3")))
MAX_BODY = 1_000_000


def num(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return float(value)


def validate_sample(payload):
    if not isinstance(payload, dict):
        raise ValueError("Expected an object")
    label = payload.get("text")
    if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
        raise ValueError("Label must be between 1 and 80 characters")
    before, after = payload.get("before", ""), payload.get("after", "")
    if not isinstance(before, str) or len(before) > 24 or not isinstance(after, str) or len(after) > 24:
        raise ValueError("Context strings must be <= 24 characters")
    strokes = payload.get("strokes")
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= 500:
        raise ValueError("Provide 1 to 500 strokes")
    cleaned = []
    total = 0
    for stroke in strokes:
        if not isinstance(stroke, list) or not 1 <= len(stroke) <= 12000:
            raise ValueError("Each stroke must have 1 to 12000 points")
        out = []
        last_t = -1
        for p in stroke:
            if not isinstance(p, dict):
                raise ValueError("Points must be objects")
            t = num(p.get("t", 0), "t", 0, 86400000)
            if t < last_t:
                raise ValueError("Stroke timestamps must be ordered")
            last_t = t
            out.append({"x": num(p.get("x"), "x", 0, 10000),
                        "y": num(p.get("y"), "y", 0, 10000), "t": t,
                        "pressure": num(p.get("pressure", .5), "pressure", 0, 1)})
        total += len(out)
        if total > 20000:
            raise ValueError("Maximum 20000 points per sample")
        cleaned.append(out)
    return {"text": label.strip(), "before": before, "after": after, "strokes": cleaned}


class Store:
    def __init__(self, path=DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL, before_text TEXT NOT NULL, after_text TEXT NOT NULL,
                strokes_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def add(self, payload):
        item = validate_sample(payload)
        with self.connect() as db:
            cur = db.execute(
                "INSERT INTO samples (text,before_text,after_text,strokes_json) VALUES (?,?,?,?)",
                (item["text"], item["before"], item["after"], json.dumps(item["strokes"], separators=(",", ":"))))
            return cur.lastrowid

    def all(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,text,before_text,after_text,strokes_json,created_at FROM samples ORDER BY id"
            ).fetchall()
        return [{"id": row[0], "text": row[1], "before": row[2], "after": row[3],
                 "strokes": json.loads(row[4]), "created_at": row[5]} for row in rows]

    def delete(self, sample_id):
        with self.connect() as db:
            return bool(db.execute("DELETE FROM samples WHERE id=?", (sample_id,)).rowcount)


DEFAULTS = {
    "page_width_mm": 200, "page_height_mm": 200, "margin_mm": 10, "height_mm": 7.5,
    "line_spacing_mm": 14, "letter_gap_mm": 1, "word_gap_mm": 3,
    "variation_mm": .3, "z_variation_mm": 0, "pen_up_z_mm": 2,
    "pen_down_z_mm": 0, "travel_feed_mm_min": 1800,
    "write_feed_mm_min": 750, "z_feed_mm_min": 100,
}
BOUNDS = {
    "page_width_mm": (40, 300), "page_height_mm": (40, 300),
    "margin_mm": (0, 40), "height_mm": (1, 30),
    "line_spacing_mm": (2, 50), "letter_gap_mm": (0, 12),
    "word_gap_mm": (0, 25), "variation_mm": (0, 2),
    "z_variation_mm": (0, .15), "pen_up_z_mm": (-10, 20),
    "pen_down_z_mm": (-10, 20), "travel_feed_mm_min": (30, 6000),
    "write_feed_mm_min": (30, 6000), "z_feed_mm_min": (10, 1000),
}


def options_from(payload):
    if not isinstance(payload, dict):
        raise ValueError("Options must be an object")
    opt = {k: num(payload.get(k, v), k, *BOUNDS[k]) for k, v in DEFAULTS.items()}
    if opt["margin_mm"] * 2 + opt["height_mm"] > opt["page_height_mm"]:
        raise ValueError("Page too small for the writing height")
    if opt["margin_mm"] * 2 >= opt["page_width_mm"]:
        raise ValueError("Margins exceed page width")
    if opt["pen_up_z_mm"] <= opt["pen_down_z_mm"] + opt["z_variation_mm"]:
        raise ValueError("Pen-up Z must be higher than pen-down Z plus variation")
    return opt


def select_sample(samples, text, index, rng, previous_id):
    eligible, weights = [], []
    for entry in samples:
        token = entry["text"]
        if not text.startswith(token, index):
            continue
        weight = float(len(token) ** 3)
        if entry["before"]:
            weight *= 2 if text[:index].endswith(entry["before"]) else .15
        if entry["after"]:
            weight *= 2 if text[index + len(token):].startswith(entry["after"]) else .15
        if entry["id"] == previous_id:
            weight *= .4
        eligible.append(entry)
        weights.append(weight)
    return rng.choices(eligible, weights=weights, k=1)[0] if eligible else None


def bounds(strokes):
    pts = [p for s in strokes for p in s]
    return (min(p["x"] for p in pts), min(p["y"] for p in pts),
            max(p["x"] for p in pts), max(p["y"] for p in pts))


def render_svg(strokes, width, height):
    from html import escape
    paths = []
    for stroke in strokes:
        if len(stroke) == 1:
            x, y, _ = stroke[0]
            paths.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r=".2" fill="#171717"/>')
        else:
            d = " ".join(("M" if i == 0 else "L") +
                         f"{p[0]:.3f},{p[1]:.3f}" for i, p in enumerate(stroke))
            paths.append(f'<path d="{escape(d)}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.2f}mm" '
            f'height="{height:.2f}mm" viewBox="0 0 {width:.3f} {height:.3f}">'
            '<rect width="100%" height="100%" fill="white"/>'
            '<g fill="none" stroke="#171717" stroke-width=".28" '
            'stroke-linecap="round" stroke-linejoin="round">' +
            "".join(paths) + '</g></svg>')


def render_gcode(strokes, opt):
    """Export for offline review. Coordinates assume an unverified positive-Z pen lift."""
    up, down = opt["pen_up_z_mm"], opt["pen_down_z_mm"]
    amp = opt["z_variation_mm"]
    lines = [
        "; UNCALIBRATED PREVIEW - do not run without verifying homing, bounds and Z polarity",
        "; All work coordinates are page-relative; XY maps require physical setup",
        "G21", "G90", "G94",
        f"G0 Z{up:.3f}",
    ]
    for stroke in strokes:
        x, y, _ = stroke[0]
        lines.append(f"G0 X{x:.3f} Y{y:.3f}")
        lines.append(f"G1 Z{down:.3f} F{opt['z_feed_mm_min']:.0f}")
        if len(stroke) == 1:
            lines.append("G4 P0.08")
        for i, (px, py, pressure) in enumerate(stroke[1:], 1):
            # Touch interfaces often report fixed pressure = 0.5. No fake sensor data.
            z = down + amp * (.5 - pressure) * 2
            z = min(up - .001, max(-10, z))
            if amp > 0:
                lines.append(f"G1 X{px:.3f} Y{py:.3f} Z{z:.3f} F{opt['write_feed_mm_min']:.0f}")
            else:
                lines.append(f"G1 X{px:.3f} Y{py:.3f} F{opt['write_feed_mm_min']:.0f}")
        lines.append(f"G0 Z{up:.3f}")
    lines.append("M2")
    return "\n".join(lines) + "\n"


def render_uno_gcode(strokes, opt):
    """Export the composed paths for the Uno XY plus M3/M5 pen protocol."""
    from slicer import render_uno_gcode
    return render_uno_gcode(strokes, opt)


def compose(payload, library):
    if not isinstance(payload, dict):
        raise ValueError("Expected an object")
    text = payload.get("text")
    if not isinstance(text, str) or not 1 <= len(text) <= 1000:
        raise ValueError("Text must be 1 to 1000 characters")
    opt = options_from(payload.get("options", {}))
    seed = payload.get("seed", 1)
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 2**31 - 1:
        raise ValueError("Seed must be a nonnegative integer")
    rng = random.Random(seed)
    x, baseline = opt["margin_mm"], opt["margin_mm"] + opt["height_mm"]
    strokes_out, missing, selected = [], [], []
    prev_id = None
    index = 0
    while index < len(text):
        ch = text[index]
        if ch == "\n":
            x = opt["margin_mm"]
            baseline += opt["line_spacing_mm"]
            index += 1
            continue
        if ch.isspace():
            x += opt["word_gap_mm"]
            if x > opt["page_width_mm"] - opt["margin_mm"]:
                x = opt["margin_mm"]
                baseline += opt["line_spacing_mm"]
            index += 1
            continue
        sample = select_sample(library, text, index, rng, prev_id)
        if sample is None:
            missing.append({"offset": index, "character": ch})
            x += opt["height_mm"] * .55
            index += 1
            prev_id = None
            continue
        sx0, sy0, sx1, sy1 = bounds(sample["strokes"])
        rawheight = max(sy1 - sy0, 1)
        scale = opt["height_mm"] / rawheight
        width = max((sx1 - sx0) * scale, opt["height_mm"] * .08)
        if width > opt["page_width_mm"] - 2 * opt["margin_mm"]:
            raise ValueError("Sample too wide for page; reduce writing height")
        if x + width > opt["page_width_mm"] - opt["margin_mm"]:
            x = opt["margin_mm"]
            baseline += opt["line_spacing_mm"]
        if baseline > opt["page_height_mm"] - opt["margin_mm"]:
            raise ValueError("Text exceeds page height; reduce size or length")
        # Per-sequence stable shifts retain original flowing stroke shapes.
        dx = rng.uniform(-opt["variation_mm"], opt["variation_mm"])
        dy = rng.uniform(-opt["variation_mm"], opt["variation_mm"])
        minx = x + dx
        miny = baseline - opt["height_mm"] + dy
        if minx < 0 or minx + width > opt["page_width_mm"] or miny < 0 or miny + opt["height_mm"] > opt["page_height_mm"]:
            dx = dy = 0
        for stroke in sample["strokes"]:
            placed = [
                (x + (p["x"] - sx0) * scale + dx,
                 baseline - opt["height_mm"] + (p["y"] - sy0) * scale + dy,
                 p["pressure"]) for p in stroke
            ]
            strokes_out.append(placed)
        selected.append({"id": sample["id"], "text": sample["text"], "offset": index})
        x += width + opt["letter_gap_mm"]
        prev_id = sample["id"]
        index += len(sample["text"])
        if len(strokes_out) > 5000:
            raise ValueError("Too many output strokes")
    if not strokes_out:
        raise ValueError("No dictionary matches. Record handwriting first.")
    if sum(len(s) for s in strokes_out) > 100000:
        raise ValueError("Composed output exceeds 100000 points")
    uno_gcode = render_uno_gcode(strokes_out, opt) if not missing else None
    return {
        "svg": render_svg(strokes_out, opt["page_width_mm"], opt["page_height_mm"]),
        "gcode": render_gcode(strokes_out, opt),
        "uno_gcode": uno_gcode,
        "selected": selected, "missing": missing, "stroke_count": len(strokes_out),
        "machine_ready": False,
    }


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, obj, status=200):
            encoded = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def _body(self):
            length = self.headers.get("Content-Length")
            if length is None or not length.isdecimal() or int(length) > MAX_BODY:
                raise ValueError("Invalid request body size")
            raw = self.rfile.read(int(length))
            try:
                return json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Malformed JSON") from exc

        def do_GET(self):
            url = urlparse(self.path).path
            if url == "/api/samples":
                return self._json({"samples": store.all()})
            path = {"/": WEB / "index.html", "/app.js": WEB / "app.js",
                    "/style.css": WEB / "style.css"}.get(url)
            if path is None or not path.is_file():
                return self._json({"error": "Not found"}, 404)
            raw = path.read_bytes()
            mime = "text/html" if path.suffix == ".html" else "text/javascript" if path.suffix == ".js" else "text/css"
            self.send_response(200)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            try:
                data = self._body()
                if self.path == "/api/samples":
                    return self._json({"id": store.add(data)}, 201)
                if self.path == "/api/compose":
                    return self._json(compose(data, store.all()))
                return self._json({"error": "Not found"}, 404)
            except (ValueError, TypeError) as exc:
                return self._json({"error": str(exc)}, 400)

        def do_DELETE(self):
            path = urlparse(self.path).path
            if not path.startswith("/api/samples/"):
                return self._json({"error": "Not found"}, 404)
            tail = path.removeprefix("/api/samples/")
            if not tail.isdecimal():
                return self._json({"error": "Invalid sample id"}, 400)
            if not store.delete(int(tail)):
                return self._json({"error": "Sample not found"}, 404)
            return self._json({"deleted": True})

        def log_message(self, fmt, *args):
            if os.environ.get("DAVINCHI_VERBOSE") == "1":
                super().log_message(fmt, *args)

    return Handler


def serve():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(Store()))
    print(f"Open http://{args.host}:{args.port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
