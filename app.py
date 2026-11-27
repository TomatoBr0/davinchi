#!/usr/bin/env python3
"""Offline handwriting sampler/composer. Preview-only G-code: NO machine control."""
from __future__ import annotations

import json
import math
import os
import random
import re
import socket
import sqlite3
import threading
import time
from collections import deque
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from send_plot import preflight

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DB_PATH = Path(os.environ.get("DAVINCHI_DB", str(ROOT / "data" / "samples.sqlite3")))
MAX_BODY = 1_000_000
MAX_JOB_BODY = 8_000_000
MAX_UPLOAD = 25_000_000  # handwriting photos (base64 JSON)
CALIBRATION_FILES = {"/calibration_test.nc": ROOT / "tools" / "calibration_test.nc",
                     "/calibration_sheet.pdf": ROOT / "docs" / "calibration" / "calibration_sheet.pdf"}
MIME = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
        ".nc": "text/plain", ".pdf": "application/pdf"}


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

    @contextmanager
    def connect(self):
        # sqlite3's own "with" only commits; close explicitly so Windows can delete the file.
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

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


def slice_sketch(payload):
    """Hand-sketch style: grayscale raster -> tools/sketch_style -> centred Uno G-code plus match report."""
    import base64
    import numpy as np
    import cv2
    from slicer import render_uno_gcode
    from tools.sketch_style import sketch

    if not isinstance(payload, dict):
        raise ValueError("Expected an image object")
    width, height = payload.get("width"), payload.get("height")
    if type(width) is not int or type(height) is not int or not (2 <= width <= 480 and 2 <= height <= 480):
        raise ValueError("Image dimensions must be 2 to 480 pixels")
    pixels = payload.get("pixels")
    if not isinstance(pixels, list) or len(pixels) != width * height or any(type(p) is not int or not 0 <= p <= 255 for p in pixels):
        raise ValueError("Expected one grayscale byte per pixel")
    page_w = num(payload.get("page_width_mm", 150), "Page width", 20, 300)
    page_h = num(payload.get("page_height_mm", 150), "Page height", 20, 300)
    seed = payload.get("seed", 1)
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError("Seed must be a nonnegative integer")
    tune = payload.get("tune", False)
    if type(tune) is not bool:
        raise ValueError("Tune must be true or false")
    gray = np.array(pixels, np.uint8).reshape(height, width)
    result = sketch(gray, tune=tune, size=min(page_w, page_h) - 10, seed=seed)
    ox, oy = (page_w - result["width_mm"]) / 2, (page_h - result["height_mm"]) / 2
    strokes = [[(x + ox, y + oy, p) for x, y in pts] for pts, p in result["paths"] if len(pts) > 1]
    if not strokes:
        raise ValueError("No drawable marks. Use a picture with darker tones.")
    options = {"travel_feed_mm_min": 300, "write_feed_mm_min": 300}
    ok, png = cv2.imencode(".png", result["compare"])
    return {"svg": render_svg(strokes, page_w, page_h),
            "uno_gcode": render_uno_gcode(strokes, options),
            "stroke_count": len(strokes), "point_count": sum(len(s) for s in strokes),
            "match": round(result["match"], 1), "settings": result["settings"], "tuned": tune,
            "compare_png": "data:image/png;base64," + base64.b64encode(png.tobytes()).decode("ascii") if ok else None,
            "machine_ready": False}


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


BAUD = 115200
RUN_STATES = ("running", "paused", "stopping")
PYSERIAL_HINT = "pyserial is not installed: run  pip install pyserial"
M115_RE = re.compile(r"ok CAL=([01]) ORIGIN=([01]) ARMED=([01]) MAX X(-?[\d.]+) Y(-?[\d.]+) Z(-?[\d.]+) "
                     r"STEPS X(-?[\d.]+) Y(-?[\d.]+) Z(-?[\d.]+)")
M114_RE = re.compile(r"ok X(-?[\d.]+) Y(-?[\d.]+) Z(-?[\d.]+) (known|unknown)")
LIMITS_RE = re.compile(r"ok X(-?[\d.]+) Y(-?[\d.]+) F(-?[\d.]+)")


class MachineError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def parse_status(reply):
    """M115: calibration flags, travel and steps/mm. Returns None if the reply does not match."""
    m = M115_RE.fullmatch(reply)
    if not m:
        return None
    n = [float(m[i]) for i in range(4, 10)]
    return {"cal": m[1] == "1", "origin": m[2] == "1", "armed": m[3] == "1",
            "maxX": n[0], "maxY": n[1], "maxZ": n[2], "stepsX": n[3], "stepsY": n[4], "stepsZ": n[5]}


def parse_position(reply):
    m = M114_RE.fullmatch(reply)
    if not m:
        return None
    return {"x": float(m[1]), "y": float(m[2]), "z": float(m[3]), "known": m[4] == "known"}


def open_serial(port):
    try:
        import serial
    except ImportError as exc:
        raise MachineError(PYSERIAL_HINT, 503) from exc
    try:
        return serial.Serial(port, BAUD, timeout=.25, write_timeout=2)
    except OSError as exc:
        raise MachineError(f"cannot open {port}: {exc}") from exc


def list_ports():
    try:
        from serial.tools import list_ports as comports
    except ImportError:
        return {"available": False, "ports": [], "error": PYSERIAL_HINT}
    return {"available": True, "error": "",
            "ports": [{"device": p.device, "description": p.description} for p in comports.comports()]}


class MachineLink:
    """Owns the USB port to the Uno. Every command waits for ok/error before the next is sent,
    because the firmware aborts motion on any stray byte. Polling only happens while idle."""

    def __init__(self, opener=None, reset_wait=2.0):
        self.opener = opener or open_serial
        self.reset_wait = reset_wait
        self.io = threading.Lock()          # serialises port access
        self.control = threading.Condition()  # guards pause/stop flags
        self.port = None
        self.port_name = ""
        self.log = deque(maxlen=400)
        self.status = {}
        self.job = {"state": "idle", "index": 0, "total": 0, "error": "", "name": ""}
        self.stop_requested = False
        self.paused = False

    def _active(self):
        return self.job["state"] in RUN_STATES

    def _read_reply(self, line, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            reply = self.port.readline().decode("ascii", errors="replace").strip()
            if not reply:
                continue
            self.log.append("< " + reply)
            if reply == "ok" or reply.startswith("ok "):
                return reply
            if reply.startswith("error:"):
                raise MachineError(reply[6:].strip())
        raise MachineError(f"no reply to {line}")

    def _exchange(self, line, timeout=120):
        with self.io:
            if self.port is None:
                raise MachineError("not connected")
            self.log.append("> " + line)
            self.port.write((line + "\n").encode("ascii"))
            return self._read_reply(line, timeout)

    def connect(self, port):
        with self.io:
            if self.port is not None:
                raise MachineError("already connected; disconnect first")
            self.port = self.opener(port)
            self.port_name = port
            time.sleep(self.reset_wait)  # the Uno resets when the port opens
            self.port.reset_input_buffer()
        self.status = {}
        self.log.append(f"connected to {port} at {BAUD} baud")
        with suppress(MachineError):
            limits = LIMITS_RE.fullmatch(self._exchange("LIMITS"))
            if limits:
                self.status["feed"] = float(limits[3])
        return self.info()

    def disconnect(self):
        if self._active():
            raise MachineError("stop the job before disconnecting")
        with self.io:
            if self.port is not None:
                with suppress(OSError):
                    self.port.close()
                self.port = None
        self.status = {}
        self.log.append("disconnected")
        return self.info()

    def send(self, line):
        line = line.strip()
        if not line or len(line) > 62 or not line.isascii() or line == "!":
            raise MachineError("send one ASCII command up to 62 characters; use Abort for !")
        if self._active():
            raise MachineError("a job is running; pause or stop it first")
        return self._exchange(line)

    def abort(self):
        with self.control:
            if self.port is None:
                raise MachineError("not connected")
            self.stop_requested = True
            self.control.notify_all()
            self.log.append("> !  (abort)")
            try:
                # Twice, then flush: one stray byte must never be the only stop.
                self.port.write(b"!\n!\n")  # firmware disarms; the in-flight line reports the error
                self.port.flush()
            except OSError as exc:
                raise MachineError(f"abort write failed: {exc}", 503) from exc
        return self.info()

    def refresh(self):
        """Poll M115 and M114 while idle. Skipped during a job, where motion is in progress."""
        if self.port is None or self._active():
            return
        status = parse_status(self._exchange("M115"))
        position = parse_position(self._exchange("M114"))
        if status is None or position is None:
            raise MachineError("unexpected status reply")
        self.status = {**self.status, **status, **position}

    def info(self):
        return {"connected": self.port is not None, "port": self.port_name,
                "status": dict(self.status), "job": dict(self.job), "log": list(self.log)[-200:]}

    def snapshot(self):
        error = ""
        try:
            self.refresh()
        except MachineError as exc:
            error = str(exc)
        return {**self.info(), "poll_error": error}

    def start_job(self, text, name=""):
        if self.port is None:
            raise MachineError("not connected")
        if self._active():
            raise MachineError("a job is already running")
        try:
            commands, _extent, _strokes = preflight(text)
        except ValueError as exc:
            raise MachineError(str(exc)) from exc
        self.refresh()
        if not self.status.get("origin"):
            raise MachineError("set the origin (M210) before streaming")
        self._exchange("ARM")
        with self.control:
            if self._active():
                raise MachineError("a job is already running")
            self.stop_requested = False
            self.paused = False
            self.job = {"state": "running", "index": 0, "total": len(commands), "error": "", "name": name[:80]}
        threading.Thread(target=self._run_job, args=(commands,), daemon=True).start()
        return self.info()

    def _run_job(self, commands):
        stopped = False
        try:
            for index, line in enumerate(commands, 1):
                with self.control:
                    self.control.wait_for(lambda: not self.paused or self.stop_requested)
                    stopped = self.stop_requested
                if stopped:
                    break
                self._exchange(line)
                self.job["index"] = index
            if stopped:
                self._exchange("M5")  # pen up after the current line has finished
                self.job["state"] = "stopped"
            else:
                self.job["state"] = "done"
        except Exception as exc:
            if self.stop_requested:
                # Stopping disarms the drivers, so M5 cannot run: report a clean stop.
                self.job["state"] = "stopped"
                self.job["error"] = ""
            else:
                self.job["state"] = "error"
                self.job["error"] = str(exc)
                with suppress(Exception):
                    self._exchange("M5")

    def pause(self):
        with self.control:
            if self.job["state"] != "running":
                raise MachineError("no running job to pause")
            self.paused = True
            self.job = {**self.job, "state": "paused"}
        return self.info()

    def resume(self):
        with self.control:
            if self.job["state"] != "paused":
                raise MachineError("job is not paused")
            self.paused = False
            self.job = {**self.job, "state": "running"}
            self.control.notify_all()
        return self.info()

    def stop(self):
        with self.control:
            if not self._active():
                raise MachineError("no running job")
            self.stop_requested = True
            self.paused = False
            self.job = {**self.job, "state": "stopping"}
            self.control.notify_all()
        return self.info()


def make_handler(store, link=None, hand=None):
    from tools.handwriting import Handwriting, OcrUnavailable
    link = link or MachineLink()
    hand = hand or Handwriting(ROOT / "data" / "handwriting")

    class Handler(BaseHTTPRequestHandler):
        def _json(self, obj, status=200):
            encoded = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def _body(self, limit=MAX_BODY):
            length = self.headers.get("Content-Length")
            if length is None or not length.isdecimal() or int(length) > limit:
                raise ValueError("Invalid request body size")
            raw = self.rfile.read(int(length))
            try:
                return json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Malformed JSON") from exc

        def _serial_post(self, action):
            body = {}
            if self.headers.get("Content-Length") not in (None, "0"):
                body = self._body(MAX_JOB_BODY)
            if not isinstance(body, dict):
                raise ValueError("Expected an object")
            if action == "connect":
                return self._json(link.connect(str(body.get("port", ""))))
            if action == "disconnect":
                return self._json(link.disconnect())
            if action == "send":
                reply = link.send(str(body.get("line", "")))
                return self._json({**link.info(), "reply": reply})
            if action == "abort":
                return self._json(link.abort())
            if action == "job":
                return self._json(link.start_job(str(body.get("text", "")), str(body.get("name", ""))))
            if action == "job/pause":
                return self._json(link.pause())
            if action == "job/resume":
                return self._json(link.resume())
            if action == "job/stop":
                return self._json(link.stop())
            return self._json({"error": "Not found"}, 404)

        def _hand_get(self, url):
            if url == "/api/handwriting/samples":
                return self._json({"samples": hand.samples()})
            m = re.fullmatch(r"/api/handwriting/sample/(\d+)(/page\.png)?", url)
            if not m:
                return self._json({"error": "Not found"}, 404)
            sid = int(m[1])
            if m[2]:
                raw = hand.page_png(sid)
                if raw is None:
                    return self._json({"error": "Sample not found"}, 404)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(raw)
            info = hand.detail(sid)
            return self._json(info) if info else self._json({"error": "Sample not found"}, 404)

        def do_GET(self):
            url = urlparse(self.path).path
            if url.startswith("/api/handwriting/"):
                return self._hand_get(url)
            if url == "/api/samples":
                return self._json({"samples": store.all()})
            if url == "/api/serial/ports":
                return self._json(list_ports())
            if url == "/api/serial/status":
                return self._json(link.snapshot())
            path = {"/": WEB / "index.html", "/app.js": WEB / "app.js", "/machine.js": WEB / "machine.js",
                    "/slicer.html": WEB / "slicer.html", "/slicer.js": WEB / "slicer.js", "/slicer.css": WEB / "slicer.css",
                    "/style.css": WEB / "style.css", "/photo.js": WEB / "photo.js",
                    "/handwriting.html": WEB / "handwriting.html", "/handwriting.js": WEB / "handwriting.js",
                    **CALIBRATION_FILES}.get(url)
            if path is None or not path.is_file():
                return self._json({"error": "Not found"}, 404)
            raw = path.read_bytes()
            mime = MIME.get(path.suffix, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            try:
                if self.path.startswith("/api/serial/"):
                    return self._serial_post(self.path.removeprefix("/api/serial/"))
                if self.path.startswith("/api/handwriting/"):
                    action = self.path.removeprefix("/api/handwriting/")
                    if action == "upload":  # phone photos run to several MB
                        return self._json(hand.upload(self._body(MAX_UPLOAD)), 201)
                    handlers = {"transcribe": hand.transcribe, "label": hand.label,
                                "read": hand.read, "render": hand.render, "layout": hand.layout}
                    if action not in handlers:
                        return self._json({"error": "Not found"}, 404)
                    return self._json(handlers[action](self._body()))
                data = self._body()
                if self.path == "/api/samples":
                    return self._json({"id": store.add(data)}, 201)
                if self.path == "/api/photo":
                    from photo_slicer import slice_photo
                    return self._json(slice_photo(data))
                if self.path == "/api/sketch":
                    return self._json(slice_sketch(data))
                if self.path == "/api/compose":
                    return self._json(compose(data, store.all()))
                return self._json({"error": "Not found"}, 404)
            except MachineError as exc:
                return self._json({"error": str(exc)}, exc.status)
            except OcrUnavailable as exc:
                return self._json({"error": str(exc)}, 503)
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


def lan_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))  # routing lookup only; nothing is sent
            return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"


class LocalHTTPServer(ThreadingHTTPServer):
    # Windows honours SO_REUSEADDR by letting a second process bind a port that is
    # already serving, so the new UI silently loses every request to the old one.
    # Refuse the bind instead: a busy port must be an error, not a shared socket.
    allow_reuse_address = False


def serve():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("DAVINCHI_HOST", "127.0.0.1"))
    parser.add_argument("--lan", action="store_true",
                        help="listen on 0.0.0.0 so a phone on this Wi-Fi can reach the UI")
    parser.add_argument("--port", type=int, default=int(os.environ.get("DAVINCHI_PORT", "8775")))
    args = parser.parse_args()
    host = "0.0.0.0" if args.lan else args.host
    try:
        server = LocalHTTPServer((host, args.port), make_handler(Store(), MachineLink()))
    except OSError as exc:
        raise SystemExit(
            f"Cannot listen on {host}:{args.port} - {exc}.\n"
            "Another program (for example the Carl app on 8765) may hold that port.\n"
            "Pick a free one:  python app.py --port 8780   (or set DAVINCHI_PORT)") from exc
    print(f"Open http://127.0.0.1:{args.port} (Ctrl+C to stop)")
    if host == "0.0.0.0":
        print(f"LAN URL: http://{lan_address()}:{args.port}  (no login: anyone on this network can drive the plotter)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()

