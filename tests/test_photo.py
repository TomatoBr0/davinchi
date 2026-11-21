import unittest
from photo_slicer import slice_photo
from send_plot import preflight


class PhotoTests(unittest.TestCase):
    def image(self, style, pixels=None):
        return {"width": 12, "height": 8, "pixels": pixels or [0] * 96,
                "style": style, "page_width_mm": 40, "page_height_mm": 30,
                "spacing_mm": 2}

    def test_all_styles_make_valid_bounded_jobs(self):
        for style in ("diagonal", "crosshatch", "scribble", "outlines", "stipple", "squiggle", "spiral", "tour", "springs", "halftone", "boxes"):
            pixels = [0 if x < 6 else 255 for y in range(8) for x in range(12)]
            with self.subTest(style=style):
                result = slice_photo(self.image(style, pixels))
                _, bounds, strokes = preflight(result["uno_gcode"])
                self.assertGreater(strokes, 0)
                self.assertLessEqual(bounds[0], 35)
                self.assertLessEqual(bounds[1], 25)
                self.assertIn("<svg", result["svg"])

    def test_deterministic_and_white_is_blank(self):
        for style in ("diagonal", "crosshatch", "scribble", "outlines", "stipple", "squiggle", "spiral", "tour", "springs", "halftone", "boxes"):
            with self.subTest(style=style), self.assertRaises(ValueError):
                slice_photo(self.image(style, [255] * 96))
        self.assertEqual(slice_photo(self.image("scribble")), slice_photo(self.image("scribble")))

    def test_dark_areas_get_more_ink(self):
        for style in ("diagonal", "crosshatch", "scribble", "stipple", "tour"):
            dark = slice_photo(self.image(style))
            gray = slice_photo(self.image(style, [100] * 96))
            self.assertGreater(dark["point_count"], gray["point_count"])

    def test_continuous_styles_have_one_pen_down(self):
        for style in ("spiral", "tour"):
            result = slice_photo(self.image(style))
            self.assertEqual(result["stroke_count"], 1)
            self.assertEqual(result["uno_gcode"].splitlines().count("M3"), 1)

    def test_scribbles_wander_across_former_cell_boundaries(self):
        import re
        result = slice_photo(self.image("scribble"))
        paths = re.findall(r'<path d="([^"]+)"', result["svg"])
        spans = []
        for path in paths:
            coords = [(float(x), float(y)) for x, y in re.findall(r"[ML]([0-9.]+),([0-9.]+)", path)]
            spans.append(max(x for x, _ in coords) - min(x for x, _ in coords))
        self.assertGreater(max(spans), 10)

    def test_blank_gap_is_not_crossed_by_scribble(self):
        import re
        pixels = [0 if x < 3 or x > 8 else 255 for y in range(8) for x in range(12)]
        result = slice_photo(self.image("scribble", pixels))
        for path in re.findall(r'<path d="([^"]+)"', result["svg"]):
            coords = [float(x) for x, _ in re.findall(r"[ML]([0-9.]+),([0-9.]+)", path)]
            self.assertFalse(min(coords) < 12 and max(coords) > 28)

    def test_imported_styles_are_distinct_and_repeatable(self):
        images = [slice_photo(self.image(style))["uno_gcode"] for style in ("springs", "halftone", "boxes")]
        self.assertEqual(len(set(images)), 3)
        self.assertEqual(images[0], slice_photo(self.image("springs"))["uno_gcode"])

    def test_bad_input(self):
        for patch in ({"width": 1000}, {"pixels": []}, {"style": "bad"},
                      {"seed": True}, {"spacing_mm": 0}, {"contrast": float("nan")}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                slice_photo({**self.image("diagonal"), **patch})


if __name__ == "__main__":
    unittest.main()
