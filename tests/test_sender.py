import unittest
from pathlib import Path

from send_plot import preflight


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.job = (Path(__file__).resolve().parents[1] / "examples/first-square.dvc").read_text()

    def test_square_bounds(self):
        _, extent, strokes = preflight(self.job)
        self.assertEqual(extent, (6, 6, 60))
        self.assertEqual(strokes, 1)

    def test_malformed_or_unsafe_jobs(self):
        for old, new in [("G90", "G91"), ("X6", "X-6"), (" Y1 F60", " Y1 Z1 F60"),
                         ("G1 X6", "G0 X6"), ("M3", "M5"), ("F60", "Fnan")]:
            with self.subTest(new=new), self.assertRaises(ValueError):
                preflight(self.job.replace(old, new))
        with self.assertRaises(ValueError):
            preflight(self.job + "ARM\n")

    def test_dot(self):
        cmds, _, n = preflight("G21\nG90\nM5\nG0 X1 Y2 F60\nM3\nG4 P80\nM5")
        self.assertEqual(n, 1)
        self.assertIn("G4 P80", cmds)
