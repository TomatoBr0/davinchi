"""Pencil odometer: pen-down distance tracking, tip-wear Z compensation and sharpen planning.

Distances are millimetres of pen-down travel in page coordinates (travel moves with the
pen lifted are not counted). Wear compensation moves pen-down Z further toward the
paper as the graphite cone wears, which in this project's convention means *lower* Z
(pen-up is the higher Z value). It is a linear estimate: measure your own pencil.
"""
from __future__ import annotations

import json
import math
import os
import threading
from pathlib import Path

SHARPEN_MODES = ("none", "start", "interval")


def pen_down_mm(strokes):
    """Total drawn length of placed strokes [(x, y, pressure), ...] in mm."""
    total = 0.0
    for stroke in strokes:
        for a, b in zip(stroke, stroke[1:]):
            total += math.hypot(b[0] - a[0], b[1] - a[1])
    return total


def sharpen_mode_from(options):
    mode = options.get("sharpen_mode", "none") if isinstance(options, dict) else "none"
    if mode not in SHARPEN_MODES:
        raise ValueError("sharpen_mode must be one of: " + ", ".join(SHARPEN_MODES))
    return mode


def sharpen_block(reason):
    """GRBL-compatible pause. Uno GRBL has no E axis, so a motorised sharpener cannot be
    driven from this program; the operator (or later FluidNC macro) sharpens and re-zeroes."""
    return [
        f"; SHARPEN ({reason})",
        "M0 ; PAUSE: sharpen pencil, re-touch-off pen-down Z, then cycle start (~)",
    ]


class PencilState:
    """Persists cumulative pen-down distance across jobs in a small JSON file."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _default(self):
        return {"mm_since_sharpen": 0.0, "lifetime_mm": 0.0, "sharpen_count": 0}

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            return self._default()
        state = self._default()
        for key in state:
            value = data.get(key) if isinstance(data, dict) else None
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                state[key] = type(state[key])(value)
        return state

    def _save(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, self.path)

    def record_plot(self, pen_down, mm_since_sharpen, sharpens):
        """Record a job that was physically plotted (previews are never counted)."""
        with self._lock:
            state = self.load()
            state["lifetime_mm"] += pen_down
            state["mm_since_sharpen"] = mm_since_sharpen
            state["sharpen_count"] += sharpens
            self._save(state)
            return state

    def mark_sharpened(self):
        with self._lock:
            state = self.load()
            state["mm_since_sharpen"] = 0.0
            state["sharpen_count"] += 1
            self._save(state)
            return state
