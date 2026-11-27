"""Level-1 handwriting layout: putText glyph samples and a synthetic ruled page. No camera, no API.

Run: python -m pytest tests/test_hand_layout.py -q
"""
import base64
import math
import random
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from tools import hand_layout as hl  # noqa: E402
from tools import handwriting as hw  # noqa: E402


def manual_glyph(gid, ch, strokes, width=0.6, slant=0.0, height=0.7, bottom=0.0, sample=1, line="L1"):
    return {"id": gid, "sample": sample, "line_id": line, "bbox": [0, 0, int(width * 100), int(height * 100)],
            "char": ch, "source": "manual", "height": height, "width": width, "bottom": bottom,
            "slant": slant, "strokes": strokes}


def hand_glyphs(*chars):
    """A tidy hand: one stroke per letter, a descender for g, an ascender for b."""
    out = []
    for i, ch in enumerate(chars):
        if ch == "g":
            strokes = [[(0, 0), (0.5, -0.3), (0.5, 0.7)]]
        elif ch == "b":
            strokes = [[(0, 0), (0, 1.4)], [(0, 0.7), (0.5, 0.7), (0.5, 0)]]
        else:
            strokes = [[(0, 0), (0.5, 0.7), (1.0, 0)]]
        out.append(manual_glyph(f"g{i}", ch, strokes, width=1.0, height=1.4 if ch == "b" else 0.7,
                                bottom=-0.3 if ch == "g" else 0.0))
    return out


def putext_harvest(tmp, lines):
    """Notebook-like photo of putText lines, harvested and labeled exactly as the app does it."""
    img = np.full((300, 900, 3), 255, np.uint8)
    for text, y in lines:
        cv2.putText(img, text, (40, y), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 3, cv2.LINE_AA)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    hand = hw.Handwriting(Path(tmp))
    sid = hand.upload({"filename": "p.png", "data": base64.b64encode(buf.tobytes()).decode()})["id"]
    ids = [l["id"] for l in hand.detail(sid)["lines"]]
    for lid, (text, _) in zip(ids, lines):
        hand.transcribe({"line": lid, "text": text})
    return hand


def points(paths):
    return np.array([p for pl in paths for p in pl], float)


class StyleAndPickTests(unittest.TestCase):
    def test_style_from_harvested_samples(self):
        with tempfile.TemporaryDirectory() as d:
            hand = putext_harvest(d, [("hello world", 150), ("slow dog", 260)])
            style = hl.learn_style(hand._glyphs()["glyphs"])
            self.assertGreater(style["x_height"], 0.2)
            self.assertLess(abs(style["slant"]), 0.6)
            self.assertGreaterEqual(style["letter_gap"], 0.0)
            self.assertGreater(style["samples"], 0)
            saved = hl.refresh_style(d)
            self.assertTrue((Path(d) / "style.json").exists())
            self.assertEqual(saved["samples"], style["samples"])

    def test_defaults_without_samples(self):
        style = hl.learn_style([])
        self.assertEqual(style["x_height"], hl.DEFAULT_STYLE["x_height"])
        self.assertEqual(style["joins"], [])

    def test_same_sample_never_twice_in_a_row(self):
        glyphs = [manual_glyph("a1", "a", [[(0, 0), (0, 1)]]), manual_glyph("a2", "a", [[(0, 0), (1, 1)]]),
                  manual_glyph("a3", "a", [[(0, 0), (1, 0)]])]
        pick = hl._Picker(glyphs, hl.DEFAULT_STYLE, random.Random(3))
        last = None
        seen = set()
        for _ in range(60):
            strokes, _, _, _ = pick.pick("a")
            key = tuple(map(tuple, strokes[0]))
            self.assertNotEqual(key, last)
            last = key
            seen.add(key)
        self.assertEqual(len(seen), 3)


class LayoutTests(unittest.TestCase):
    def test_long_sentence_shrinks_and_wraps_inside_box(self):
        text = "the quick brown fox jumps over the lazy dog again and again"
        res = hl.layout_text(text, {"x": 10, "y": 10, "w": 60, "h": 40}, size_mm=10, glyphs=(), seed=1)
        self.assertFalse(res["overflow"])
        self.assertLess(res["size_mm"], 10)
        self.assertGreaterEqual(res["row_count"], 2)
        p = points(res["paths"])
        self.assertTrue(np.all(p[:, 0] >= 10 - .05) and np.all(p[:, 0] <= 70 + .05))
        self.assertTrue(np.all(p[:, 1] >= 10 - .05) and np.all(p[:, 1] <= 50 + .05))

    def test_too_small_box_reports_overflow_at_floor(self):
        res = hl.layout_text("this will never fit in here", {"x": 0, "y": 0, "w": 20, "h": 5}, size_mm=10, glyphs=())
        self.assertTrue(res["overflow"])
        self.assertEqual(res["size_mm"], 3.0)

    def test_slanted_line_follows_its_angle(self):
        region = {"x0": 20, "y0": 60, "x1": 120, "y1": 100}  # 21.8 degrees
        res = hl.layout_text("hello world", region, size_mm=8, glyphs=(), seed=2)
        self.assertFalse(res["overflow"])
        p = points(res["paths"])
        c = p - p.mean(axis=0)
        vals, vecs = np.linalg.eigh(c.T @ c)
        ang = math.degrees(math.atan2(vecs[1, 1], vecs[0, 1]))
        ang = (ang + 90) % 180 - 90  # an axis, not a direction
        self.assertAlmostEqual(ang, math.degrees(math.atan2(40, 100)), delta=3)
        ux, uy = 100 / math.hypot(100, 40), 40 / math.hypot(100, 40)
        along = (p[:, 0] - 20) * ux + (p[:, 1] - 60) * uy
        up = (p[:, 0] - 20) * uy - (p[:, 1] - 60) * ux  # positive = above the line
        self.assertTrue(np.all(along > -.5) and np.all(along < 100 + .5))
        self.assertTrue(np.all(up > -3) and np.all(up < 9))

    def test_rows_do_not_overlap(self):
        glyphs = hand_glyphs(*"abcdefghijklmnopqrstuvwxyz" + "gb")  # descender and ascender letters
        text = "big gab bag grab " * 4
        style = {**hl.DEFAULT_STYLE, "x_height": 0.7, "ascender_ratio": 2.0, "descender_ratio": 0.43}
        res = hl.layout_text(text, {"x": 5, "y": 5, "w": 50, "h": 80}, size_mm=6, glyphs=glyphs, style=style, seed=5)
        self.assertGreaterEqual(res["row_count"], 3)
        spans = [(min(p[1] for pl in r for p in pl), max(p[1] for pl in r for p in pl)) for r in res["rows"]]
        for (_, bottom_prev), (top_next, _) in zip(spans, spans[1:]):
            self.assertLess(bottom_prev, top_next)

    def test_same_seed_same_layout_and_other_seed_differs(self):
        glyphs = hand_glyphs(*"thequickbrownfox")
        a = hl.layout_text("the quick fox", {"x": 0, "y": 0, "w": 80, "h": 30}, 6, glyphs, seed=7)
        b = hl.layout_text("the quick fox", {"x": 0, "y": 0, "w": 80, "h": 30}, 6, glyphs, seed=7)
        c = hl.layout_text("the quick fox", {"x": 0, "y": 0, "w": 80, "h": 30}, 6, glyphs, seed=8)
        self.assertEqual(a["paths"], b["paths"])
        self.assertNotEqual(a["paths"], c["paths"])

    def test_svg_is_parseable_by_davinci_draw(self):
        import davinci_draw
        res = hl.layout_text("ok", {"x": 0, "y": 0, "w": 30, "h": 10}, 5, glyphs=())
        parsed = davinci_draw.parse_svg(hl.to_svg(res["paths"], data_p=0.4))
        self.assertEqual(len(parsed), len(res["paths"]))
        self.assertAlmostEqual(parsed[0][1], 0.4)

    def test_handwriting_layout_route_writes_svg_and_style(self):
        with tempfile.TemporaryDirectory() as d:
            hand = hw.Handwriting(Path(d))
            out = hand.layout({"text": "hi there", "region": {"x0": 10, "y0": 80, "x1": 150, "y1": 80},
                               "size_mm": 6, "seed": 3})
            self.assertFalse(out["overflow"])
            self.assertTrue(out["svg"].startswith("<svg"))
            self.assertTrue((Path(d) / "style.json").exists())
            with self.assertRaises(ValueError):
                hand.layout({"text": "x", "region": {"x": 1}})


class DetectRegionsTests(unittest.TestCase):
    def synthetic_page(self):
        px = 4
        img = np.full((279 * px, 216 * px, 3), 255, np.uint8)
        for y in (60, 90, 120):  # horizontal ruled lines, mm
            cv2.line(img, (20 * px, y * px), (190 * px, y * px), (150, 150, 150), 2)
        cv2.line(img, (20 * px, 160 * px), (190 * px, 170 * px), (150, 150, 150), 2)  # slanted rule
        cv2.putText(img, "NAME: ALEX", (20 * px, 45 * px), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 3)
        return img

    def test_finds_ruled_lines_and_blank_boxes(self):
        regions = hl.detect_regions(self.synthetic_page())
        lines = [r for r in regions if r["kind"] == "line"]
        boxes = [r for r in regions if r["kind"] == "box"]
        ys = sorted(round((r["y0"] + r["y1"]) / 2) for r in lines)
        for want in (60, 90, 120):
            self.assertTrue(any(abs(y - want) <= 1 for y in ys), ys)
        slanted = [r for r in lines if abs(r["y1"] - r["y0"]) > 5]
        self.assertTrue(slanted)
        self.assertAlmostEqual(math.degrees(math.atan2(slanted[0]["y1"] - slanted[0]["y0"],
                                                      slanted[0]["x1"] - slanted[0]["x0"])), 3.4, delta=1.5)
        # the blank band between the first two rules is one box
        self.assertTrue(any(b["y"] > 61 and b["y"] + b["h"] < 89.5 and b["w"] > 100 for b in boxes), boxes)
        self.assertEqual(len({r["id"] for r in regions}), len(regions))


if __name__ == "__main__":
    unittest.main()
