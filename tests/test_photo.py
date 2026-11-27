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

    def test_pale_sketch_draws_at_default_threshold(self):
        # Paper near 240 with pencil lines near 180: only auto levels make these visible.
        pixels = [180 if x in (3, 4, 9) else 240 for y in range(8) for x in range(12)]
        result = slice_photo({**self.image("outlines", pixels), "threshold": .18})
        self.assertGreater(result["stroke_count"], 0)
        self.assertIs(result["machine_ready"], False)

    def test_auto_levels_stretches_and_skips_flat_images(self):
        from photo_slicer import auto_levels
        levels = auto_levels([200 + (i % 50) for i in range(400)])
        self.assertEqual(min(levels), 0)
        self.assertEqual(max(levels), 255)
        self.assertEqual(auto_levels([100] * 20), [100] * 20)
        self.assertEqual(auto_levels([255] * 20), [255] * 20)

    def test_tidy_strokes_simplifies_merges_drops_and_reorders(self):
        import math
        from photo_slicer import tidy_strokes
        def s(*pts):
            return [(x, y, .5) for x, y in pts]
        strokes = [
            s((0, 0), (5, 0.01), (10, 0), (10, 0.1)),  # jittery line, simplifies
            s((100, 100), (105, 100)),                 # far away
            s((10.1, 0.1), (15, 0.1)),                 # starts 0.1mm from the first
            s((0, 5), (0.1, 5)),                       # 0.1mm sliver, dropped
            s((3, 3)),                                 # stipple dot, kept as a press
        ]
        def travel(ss):
            ends = [(p[-1][:2], q[0][:2]) for p, q in zip(ss, ss[1:])]
            return sum(math.dist(a, b) for a, b in ends)
        out = tidy_strokes(strokes)
        self.assertEqual(len(out), 3)                  # merged pair, far line, dot
        self.assertEqual(sum(1 for p in out if len(p) == 1), 1)
        self.assertNotIn((5, .01), [p[:2] for p in out[0]])  # jitter removed by simplification
        self.assertLess(travel(out), travel(strokes[:3]))    # nearest-endpoint order cuts travel

    def test_centerline_gives_one_path_per_pencil_line(self):
        from photo_sketch import centerline_paths
        # A two-pixel-thick pencil line: both rows must thin to a single centerline.
        tones = [1.0 if y in (10, 11) and x > 3 else 0.0 for y in range(24) for x in range(40)]
        paths = list(centerline_paths(tones, 40, 24, 39, 23, .2, morph=False))
        self.assertEqual(len(paths), 1)

    def test_smoothed_circle_has_low_angular_jitter(self):
        # Default edge tracing of a 0.3 mm/px ring, then cleanup: no staircase turns survive.
        import math
        from photo_sketch import edge_paths
        from photo_slicer import tidy_strokes, CLEANUP
        n, scale = 80, .3
        tones = [1.0 if 24 <= math.hypot(x - 39.5, y - 39.5) <= 26 else 0.0 for y in range(n) for x in range(n)]
        raw = list(edge_paths(tones, n, n, (n - 1) * scale, (n - 1) * scale, .2, min_area=4, morph=True))
        out = max(tidy_strokes([[(x, y, .5) for x, y in p] for p in raw], CLEANUP["med"]), key=len)
        pts = [(x, y) for x, y, _ in out]
        turns = []
        for a, b, c in zip(pts, pts[1:], pts[2:]):
            h1 = math.atan2(b[1] - a[1], b[0] - a[0])
            h2 = math.atan2(c[1] - b[1], c[0] - b[0])
            turns.append(abs((h2 - h1 + math.pi) % (2 * math.pi) - math.pi))
        self.assertGreater(len(pts), 30)
        self.assertLess(max(turns), math.radians(25))

    def test_connects_collinear_gap_but_not_a_corner(self):
        from photo_slicer import tidy_strokes
        def s(*pts):
            return [(x, y, .5) for x, y in pts]
        self.assertEqual(len(tidy_strokes([s((0, 0), (10, 0)), s((11, 0), (20, 0))])), 1)
        self.assertEqual(len(tidy_strokes([s((0, 0), (10, 0)), s((11, 0), (11, 10))])), 2)

    def test_short_spur_is_pruned_and_loops_dropped(self):
        import math
        from photo_slicer import tidy_strokes, CLEANUP
        def s(*pts):
            return [(x, y, .5) for x, y in pts]
        main = s((0, 0), (30, 0))
        self.assertEqual(len(tidy_strokes([main, s((15, .2), (15, 1.5))], CLEANUP["med"])), 1)
        circle = [(20 + 1.5 * math.cos(k * math.pi / 8), 5 + 1.5 * math.sin(k * math.pi / 8)) for k in range(17)]
        self.assertEqual(len(tidy_strokes([main, s(*circle)], CLEANUP["med"])), 1)

    def test_smooth_path_keeps_endpoints_and_resamples(self):
        from photo_slicer import smooth_path
        pts = [(0, 0), (3, 0), (3, 3)]
        smooth = smooth_path(pts, .3)
        self.assertEqual(smooth[0], pts[0])
        self.assertEqual(smooth[-1], pts[-1])
        self.assertGreater(len(smooth), 15)

    def test_cleanup_and_outline_mode_options(self):
        pixels = [0 if x < 6 else 255 for y in range(8) for x in range(12)]
        for mode in ("centerline", "edge"):
            for cleanup in ("off", "low", "med", "high"):
                with self.subTest(mode=mode, cleanup=cleanup):
                    r = slice_photo({**self.image("outlines", pixels), "outline_mode": mode, "cleanup": cleanup})
                    self.assertGreater(r["stroke_count"], 0)
        with self.assertRaises(ValueError):
            slice_photo({**self.image("outlines", pixels), "cleanup": "extreme"})
        with self.assertRaises(ValueError):
            slice_photo({**self.image("outlines", pixels), "outline_mode": "fancy"})

    def test_bad_input(self):
        for patch in ({"width": 1000}, {"pixels": []}, {"style": "bad"},
                      {"seed": True}, {"spacing_mm": 0}, {"contrast": float("nan")}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                slice_photo({**self.image("diagonal"), **patch})


if __name__ == "__main__":
    unittest.main()
