import unittest
from photo_slicer import slice_photo
from send_plot import preflight


class PhotoTests(unittest.TestCase):
    def image(self, style, pixels=None):
        return {"width": 12, "height": 8, "pixels": pixels or [0] * 96,
                "style": style, "page_width_mm": 40, "page_height_mm": 30,
                "spacing_mm": 2}

    def test_all_styles_make_valid_bounded_jobs(self):
        for style in ("diagonal", "crosshatch", "scribble", "outlines", "stipple"):
            pixels = [0 if x < 6 else 255 for y in range(8) for x in range(12)]
            with self.subTest(style=style):
                result = slice_photo(self.image(style, pixels))
                _, bounds, strokes = preflight(result["uno_gcode"])
                self.assertGreater(strokes, 0)
                self.assertLessEqual(bounds[0], 35)
                self.assertLessEqual(bounds[1], 25)
                self.assertIn("<svg", result["svg"])

    def test_deterministic_and_white_is_blank(self):
        for style in ("diagonal", "crosshatch", "scribble", "outlines", "stipple"):
            with self.subTest(style=style), self.assertRaises(ValueError):
                slice_photo(self.image(style, [255] * 96))
        self.assertEqual(slice_photo(self.image("scribble")), slice_photo(self.image("scribble")))

    def test_dark_areas_get_more_ink(self):
        for style in ("diagonal", "crosshatch", "scribble", "stipple"):
            dark = slice_photo(self.image(style))
            gray = slice_photo(self.image(style, [100] * 96))
            self.assertGreater(dark["point_count"], gray["point_count"])

    def test_bad_input(self):
        for patch in ({"width": 1000}, {"pixels": []}, {"style": "bad"},
                      {"seed": True}, {"spacing_mm": 0}, {"contrast": float("nan")}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                slice_photo({**self.image("diagonal"), **patch})


if __name__ == "__main__":
    unittest.main()
