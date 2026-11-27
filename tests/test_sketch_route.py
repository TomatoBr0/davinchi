"""/api/sketch: sketch style returns Uno G-code, a match score and the compare image.

Run: python -m pytest tests/test_sketch_route.py
"""
import base64
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import app
from test_sketch_style import leaves


def raster_payload(gray, **extra):
    h, w = gray.shape
    return {"width": w, "height": h, "pixels": [int(v) for v in gray.ravel()], **extra}


class SketchRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gray = leaves(h=80, w=100)

    def test_slice_sketch_returns_gcode_inside_page_and_compare_png(self):
        result = app.slice_sketch(raster_payload(self.gray, page_width_mm=120, page_height_mm=100, seed=3))
        self.assertTrue(result["uno_gcode"].startswith("G21"))
        self.assertGreater(result["stroke_count"], 10)
        self.assertTrue(0 <= result["match"] <= 100)
        self.assertEqual(result["settings"]["size"], 90.0)   # min(page) - 10
        self.assertTrue(result["compare_png"].startswith("data:image/png;base64,"))
        png = base64.b64decode(result["compare_png"].split(",", 1)[1])
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        words = result["uno_gcode"].split()
        xs = [float(w[1:]) for w in words if w.startswith("X")]
        ys = [float(w[1:]) for w in words if w.startswith("Y")]
        self.assertTrue(all(0 <= x <= 120 for x in xs))
        self.assertTrue(all(0 <= y <= 100 for y in ys))

    def test_slice_sketch_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            app.slice_sketch(raster_payload(self.gray, tune="yes"))
        with self.assertRaises(ValueError):
            app.slice_sketch({"width": 3, "height": 3, "pixels": [0] * 4})
        with self.assertRaises(ValueError):
            app.slice_sketch(raster_payload(self.gray, seed=-1))


class SketchHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = app.Store(Path(self.tmp.name) / "s.sqlite3")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.make_handler(self.store))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def post(self, data):
        req = urllib.request.Request(self.base + "/api/sketch", data=json.dumps(data).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def test_http_sketch_ok_and_bad_request(self):
        code, body = self.post(raster_payload(leaves(h=60, w=80), page_width_mm=100, page_height_mm=100))
        self.assertEqual(code, 200)
        self.assertIn("match", body)
        self.assertIn("compare_png", body)
        code, body = self.post(raster_payload(leaves(h=60, w=80), tune=1))
        self.assertEqual(code, 400)
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main()
