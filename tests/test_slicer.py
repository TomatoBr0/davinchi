import re
import unittest

import app


def sample(label="a"):
    return {"id": 1, "text": label, "before": "", "after": "",
            "strokes": [[
                {"x": 0, "y": 0, "t": 0, "pressure": .5},
                {"x": 5, "y": 5, "t": 1, "pressure": .5},
            ], [{"x": 8, "y": 2, "t": 2, "pressure": .5}]]}


class UnoGcodeTests(unittest.TestCase):
    def test_composes_actual_strokes_with_firmware_protocol(self):
        result = app.compose({"text": "a"}, [sample()])
        lines = result["uno_gcode"].splitlines()
        self.assertEqual(lines[:3], ["G21", "G90", "M5"])
        self.assertEqual(lines[-1], "M5")
        self.assertIn("M3", lines)
        self.assertIn("G4 P80", lines)
        self.assertNotIn("Z", result["uno_gcode"])
        for line in lines:
            if line.startswith(("G0", "G1")):
                self.assertRegex(line, r"^G[01] X-?\d+\.\d{3} Y-?\d+\.\d{3} F\d+$")
        self.assertTrue(all(int(m.group(1)) <= 600 for m in
                            re.finditer(r" F(\d+)$", result["uno_gcode"], re.M)))
        self.assertFalse(result["machine_ready"])

    def test_missing_glyph_suppresses_uno_output(self):
        result = app.compose({"text": "a?"}, [sample()])
        self.assertIsNone(result["uno_gcode"])
        self.assertEqual(result["missing"][0]["character"], "?")

    def test_nonzero_z_settings_do_not_change_xy_pen_mapping(self):
        result = app.compose({"text": "a", "options": {
            "pen_up_z_mm": 5, "pen_down_z_mm": 4, "z_variation_mm": .1}}, [sample()])
        self.assertNotIn("Z", result["uno_gcode"])
        self.assertEqual(result["uno_gcode"].splitlines()[-1], "M5")


if __name__ == "__main__":
    unittest.main()
