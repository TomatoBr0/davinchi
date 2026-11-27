"""Sketch style: pressure data, tone tracking, auto-tune, and the lily pressure build.

Run: python -m pytest tests/test_sketch_style.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import lily_run  # noqa: E402
from tools import sketch_style  # noqa: E402


def leaves(h=160, w=200, base=(120, 140)):
    """Two mid-tone ellipses with a little grain on a light paper background."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.full((h, w), 235, np.float32)
    rng = np.random.default_rng(0)
    for (cx, cy, ax, ay, ang), b in zip([(60, 80, 50, 26, .5), (130, 76, 46, 24, -.6)], base):
        c, s = np.cos(ang), np.sin(ang)
        u, v = (x - cx) * c + (y - cy) * s, -(x - cx) * s + (y - cy) * c
        r = np.sqrt((u / ax) ** 2 + (v / ay) ** 2)
        img = np.where(r < 1, b + 30 * r + rng.normal(0, 6, (h, w)), img)
    return np.clip(img, 0, 255).astype(np.uint8)


class SketchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gray = leaves()
        cls.plain = sketch_style.sketch(cls.gray, size=100)

    def test_paths_carry_pressure_and_svg_matches(self):
        pressures = [p for _, p in self.plain["paths"]]
        self.assertGreater(len(pressures), 20)
        self.assertTrue(all(0 <= p <= 1 for p in pressures))
        self.assertEqual(self.plain["svg"].count("data-p="), len(pressures))
        self.assertIn('data-p="', self.plain["svg"])

    def test_tone_tracks_source_darkness(self):
        # The mean darkness drawn over the leaves should sit close to the source, not overshoot it.
        half = self.plain["compare"].shape[1] // 2
        target = (255 - self.plain["compare"][:, :half].astype(float)).mean()
        drawn = (255 - self.plain["compare"][:, half:].astype(float)).mean()
        self.assertLess(abs(drawn - target) / target, .35)
        self.assertGreater(self.plain["match"], 60)

    def test_tune_keeps_best_of_grid_and_includes_default(self):
        tuned = sketch_style.sketch(self.gray, size=100, tune=True)
        self.assertEqual(tuned["tried"], 27)
        self.assertGreaterEqual(tuned["match"], self.plain["match"] - 1e-9)
        self.assertIn(tuned["settings"]["hatch"], sketch_style.TUNE_GRID["hatch"])
        self.assertIn(tuned["settings"]["loose"], sketch_style.TUNE_GRID["loose"])
        self.assertIn(tuned["settings"]["thr"], sketch_style.TUNE_GRID["thr"])

    def test_blank_picture_gives_no_ink_and_does_not_crash(self):
        blank = sketch_style.sketch(np.full((40, 40), 240, np.uint8), size=50)
        self.assertIsInstance(blank["paths"], list)
        self.assertTrue(0 <= blank["match"] <= 100)


class LilyPressureTests(unittest.TestCase):
    def svg(self, *paths):
        body = "".join(f'<path data-p="{p:.2f}" d="M' + " L".join(f"{x},{y}" for x, y in pts) + '"/>' for pts, p in paths)
        return f'<svg viewBox="0 0 100 100"><g fill="none">{body}</g></svg>'

    def test_z_moves_pair_up_and_down_back_to_travel_height(self):
        line = [(0, 0), (10, 0), (10, 10)]
        cmds, info = lily_run.build(self.svg((line, 0.0), ([(50, 50), (60, 50)], 1.0)), fit=50, press=1.0)
        z, levels = 0.0, []
        for c in cmds:
            for w in c.split()[1:]:
                if w[0] == "Z":
                    z += float(w[1:]); levels.append(round(z, 3))
        self.assertAlmostEqual(z, 0.0, places=3)
        self.assertEqual(info["strokes"], 2)
        self.assertIn(round(z, 3), levels)

    def test_pressure_sets_pen_down_height(self):
        light, _ = lily_run.build(self.svg(([(0, 0), (5, 0)], 0.0)), fit=50, press=1.5)
        heavy, _ = lily_run.build(self.svg(([(0, 0), (5, 0)], 1.0)), fit=50, press=1.5)
        def first_down(cmds):
            return [float(c.split("Z-")[1].split()[0]) for c in cmds if c.startswith("J Z-")][1]
        self.assertAlmostEqual(first_down(heavy) - first_down(light), 1.5, places=3)

    def test_chain_joins_only_similar_pressure(self):
        a, b = ([(0, 0), (5, 0)], 0.5), ([(5.5, 0), (9, 0)], 0.5)
        c = ([(5.2, 0), (9, 0)], 0.9)                 # same gap as b, but pressure differs by 0.4
        self.assertEqual(len(lily_run.chain([a, b])), 1)
        self.assertEqual(len(lily_run.chain([a, c])), 2)

    def test_svg_resolves_from_script_dir_and_writes_to_cwd(self):
        old = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                script_svg = Path(lily_run.HERE) / "__lily_test.svg"
                script_svg.write_text(self.svg(([(0, 0), (4, 4)], .5)), encoding="utf-8")
                try:
                    self.assertEqual(lily_run.resolve("__lily_test.svg"), str(script_svg))
                    lily_run.main(["lily_run.py", "__lily_test.svg", "fit=20"])
                    self.assertTrue(Path(tmp, "lily_cmds.txt").is_file())
                finally:
                    script_svg.unlink()
            finally:
                os.chdir(old)

    def test_rejects_negative_press_and_empty_svg(self):
        with self.assertRaises(ValueError):
            lily_run.build(self.svg(([(0, 0), (1, 1)], 0)), press=-1)
        with self.assertRaises(ValueError):
            lily_run.build("<svg></svg>")


if __name__ == "__main__":
    unittest.main()
