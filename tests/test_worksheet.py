"""Synthetic-image tests for tools/worksheet.py. No camera, no hardware.

Run: python -m pytest tests/test_worksheet.py -q
"""
import os
import sys
import tempfile
import unittest

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import worksheet as ws  # noqa: E402

# worksheet mm -> photo px: 2.2 px/mm with a slight perspective tilt
HPP = np.array([[2.2, 0.15, 150.0], [0.1, 2.3, 120.0], [0.0002, 0.0001, 1.0]])


def make_photo(start=(60.0, 80.0), extra_dots=()):
    img = np.full((900, 900, 3), 60, np.uint8)  # dark bed
    corners = [(0, 0), (ws.PAGE_W, 0), (ws.PAGE_W, ws.PAGE_H), (0, ws.PAGE_H)]
    poly = [proj(c) for c in corners]
    cv2.fillPoly(img, [np.int32(poly)], (255, 255, 255))
    a, b = proj((2, 2)), proj((ws.PAGE_W - 2, ws.PAGE_H - 2))
    cv2.rectangle(img, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), (0, 0, 0), 1)  # printed frame
    for d in (start, *extra_dots):
        cv2.circle(img, tuple(int(v) for v in proj(d)), 5, (20, 20, 20), -1)
    return img


def proj(p):
    x, y, w = HPP @ np.array([p[0], p[1], 1.0])
    return (x / w, y / w)


def replay(cmds):
    """Return (pen-down segments in absolute machine mm) from a J command list."""
    pos, down, segs = (0.0, 0.0), False, []
    for c in cmds:
        parts = c.split()
        if parts[0] != "J":
            continue
        vals = {p[0]: float(p[1:]) for p in parts[1:] if p[0] in "XYZ"}
        if "Z" in vals:  # pen down = Z-LIFT, pen up = Z+LIFT; the travel Z moves happen with the pen up
            down = vals["Z"] == -ws.LIFT
        if "X" in vals or "Y" in vals:
            new = (pos[0] + vals.get("X", 0.0), pos[1] + vals.get("Y", 0.0))
            if down:
                segs.append((pos, new))
            pos = new
    return segs


class WorksheetTests(unittest.TestCase):
    def test_start_dot_found_within_half_mm(self):
        res = ws.plan(make_photo(start=(60.0, 80.0)), [])
        sx, sy = res["start"]
        self.assertLess(abs(sx - 60.0), 0.5)
        self.assertLess(abs(sy - 80.0), 0.5)

    def test_two_dots_need_explicit_start(self):
        with self.assertRaisesRegex(ValueError, "--start-mm"):
            ws.plan(make_photo(extra_dots=[(120.0, 200.0)]), [])

    def test_start_override_skips_detection(self):
        res = ws.plan(make_photo(extra_dots=[(120.0, 200.0)]), [], start_mm=(60.0, 80.0))
        self.assertEqual(res["start"], (60.0, 80.0))

    def test_commands_replay_to_expected_machine_path(self):
        els = [{"x": 100, "y": 150, "text": "HI 42", "size_mm": 8}]
        res = ws.plan(make_photo(), els, start_mm=(60.0, 80.0))  # pinned so expected values are exact
        self.assertEqual(res["skipped"], [])
        cmds = res["cmds"]
        self.assertEqual(cmds[0], f"J Z{ws.TRAVEL_Z:.3f} F100")
        self.assertEqual(cmds[-1], "J Z3.000 F100")
        # every absolute position stays inside the travel box
        pos = (0.0, 0.0)
        for c in cmds:
            for p in c.split()[1:]:
                if p[0] == "X":
                    pos = (pos[0] + float(p[1:]), pos[1])
                if p[0] == "Y":
                    pos = (pos[0], pos[1] + float(p[1:]))
            self.assertLessEqual(abs(pos[0]), ws.LIMIT + 1e-6)
            self.assertLessEqual(abs(pos[1]), ws.LIMIT + 1e-6)
        # pen-down segments equal the expected strokes mapped to machine coordinates
        expect = set()
        for s in ws.text_strokes("HI 42", 100, 150, 8):
            m = [ws.to_machine(p, (60.0, 80.0)) for p in s]
            for a, b in zip(m, m[1:]):
                expect.add(frozenset([(round(a[0], 2), round(a[1], 2)), (round(b[0], 2), round(b[1], 2))]))
        got = set()
        for a, b in replay(cmds):
            if a != b:
                got.add(frozenset([(round(a[0], 2), round(a[1], 2)), (round(b[0], 2), round(b[1], 2))]))
        self.assertEqual(got, expect)

    def test_page_right_is_machine_minus_x(self):
        self.assertLess(ws.to_machine((100.0, 80.0), (60.0, 80.0))[0], 0)
        self.assertGreater(ws.to_machine((60.0, 20.0), (60.0, 80.0))[1], 0)  # page up (smaller y) = +Y

    def test_out_of_reach_and_off_page_are_skipped(self):
        els = [{"x": 200, "y": 80, "text": "FAR", "size_mm": 5},
               {"x": 210, "y": 20, "text": "EDGE", "size_mm": 20},
               {"x": 100, "y": 100, "text": "OK", "size_mm": 5}]
        res = ws.plan(make_photo(), els)
        reasons = {i: why for i, why in res["skipped"]}
        self.assertEqual(reasons[0], "out of reach from this placement")
        self.assertEqual(reasons[1], "off the page")
        self.assertNotIn(2, reasons)

    def test_unknown_character_rejected(self):
        with self.assertRaisesRegex(ValueError, "no glyph"):
            ws.text_strokes("a@b", 0, 0, 5)

    def test_all_supported_glyphs_render(self):
        for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,-_:/?+=()":
            with self.subTest(ch=ch):
                self.assertTrue(ws.text_strokes(ch, 0, 0, 5))

    def test_cli_writes_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            photo = os.path.join(d, "p.png")
            cv2.imwrite(photo, make_photo())
            ans = os.path.join(d, "a.json")
            with open(ans, "w") as f:
                f.write('[{"x": 20, "y": 30, "text": "NAME: ALEX", "size_mm": 6}]')
            out = os.path.join(d, "out")
            self.assertEqual(ws.main([photo, ans, "--out-dir", out]), 0)
            for name in ("rectified.png", "preview.png", "cmds.txt"):
                self.assertTrue(os.path.exists(os.path.join(out, name)), name)
            with open(os.path.join(out, "cmds.txt")) as f:
                self.assertTrue(all(line.startswith("J ") for line in f.read().splitlines()))


if __name__ == "__main__":
    unittest.main()
