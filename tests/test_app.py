"""Functional tests of actual persistence, HTTP endpoints, composition and G-code.

Run: python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import app


def stroke(points):
    return [
        {"x": x, "y": y, "t": i * 8, "pressure": pressure}
        for i, (x, y, pressure) in enumerate(points)
    ]


def sample(label="a", before="", after=""):
    return {"text": label, "before": before, "after": after,
            "strokes": [
                stroke([(0, 3, .3), (2, 0, .5), (5, 5, .8)]),
                stroke([(5, 0, .5), (5, 6, .5)])
            ]}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "nested" / "samples.sqlite3"
        self.store = app.Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_real_sqlite_persistence_after_reopening(self):
        saved = sample("th", "a", "e")
        entry_id = self.store.add(saved)
        self.assertTrue(self.path.is_file())
        reopened = app.Store(self.path)
        rows = reopened.all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], entry_id)
        self.assertEqual(rows[0]["text"], "th")
        self.assertEqual(rows[0]["before"], "a")
        self.assertEqual(rows[0]["after"], "e")
        self.assertEqual(rows[0]["strokes"][0][1]["x"], 2.0)
        self.assertEqual(rows[0]["strokes"][0][2]["pressure"], 0.8)
        self.assertEqual(rows[0]["strokes"][1][0]["t"], 0.0)

    def test_preserves_multiple_variants_and_deletes_one(self):
        first = self.store.add(sample("a"))
        second = self.store.add(sample("a"))
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.store.all()), 2)
        self.assertTrue(self.store.delete(first))
        self.assertFalse(self.store.delete(first))
        self.assertEqual(self.store.all()[0]["id"], second)

    def test_rejects_nonfinite_injection_and_huge_samples(self):
        bad = sample()
        bad["strokes"][0][0]["x"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            self.store.add(bad)
        bad = sample()
        bad["strokes"] = [stroke([(1, 2, .5)] * 12001)]
        with self.assertRaisesRegex(ValueError, "12000"):
            self.store.add(bad)
        self.assertEqual(self.store.all(), [])

    def test_rejects_unordered_times_and_negative_pressure(self):
        bad = sample()
        bad["strokes"][0][2]["t"] = -1
        with self.assertRaises(ValueError):
            self.store.add(bad)
        bad = sample()
        bad["strokes"][0][0]["pressure"] = -0.1
        with self.assertRaises(ValueError):
            self.store.add(bad)


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = app.Store(Path(self.tmp.name) / "test.sqlite3")
        self.store.add(sample("t"))
        self.store.add(sample("h"))
        self.store.add(sample("th", after="e"))
        self.store.add(sample("e"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_composes_real_sequences_into_svg_and_gcode(self):
        result = app.compose({"text": "the", "seed": 2}, self.store.all())
        self.assertTrue(result["selected"])
        self.assertFalse(result["missing"])
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', result["svg"])
        self.assertIn("<path d=", result["svg"])
        self.assertIn("G21", result["gcode"])
        self.assertIn("G90", result["gcode"])
        self.assertIn("G0 Z2.000", result["gcode"])
        self.assertIn("G1 Z0.000", result["gcode"])
        self.assertIn("G1 X", result["gcode"])
        self.assertEqual(result["machine_ready"], False)

    def test_word_ligature_when_only_long_sample_exists(self):
        entries = [entry for entry in self.store.all() if entry["text"] in ("th", "e")]
        result = app.compose({"text": "the"}, entries)
        self.assertEqual([x["text"] for x in result["selected"]], ["th", "e"])

    def test_repeatable_seed_and_actual_variation(self):
        payload = {"text": "th th", "seed": 11, "options": {"variation_mm": .7}}
        a = app.compose(payload, self.store.all())
        b = app.compose(payload, self.store.all())
        c = app.compose({**payload, "seed": 12}, self.store.all())
        self.assertEqual(a["svg"], b["svg"])
        self.assertNotEqual(a["svg"], c["svg"])

    def test_missing_characters_reported_without_fake_shapes(self):
        result = app.compose({"text": "th?"}, self.store.all())
        self.assertEqual(result["missing"], [{"offset": 2, "character": "?"}])
        self.assertEqual(len(result["selected"]) >= 1, True)

    def test_pressure_to_z_optional_and_bounded(self):
        entry = sample("a")
        entry["strokes"] = [stroke([(0, 0, 0), (5, 4, 1)])]
        only = [{"id": 1, **entry}]
        off = app.compose({"text": "a", "options": {"z_variation_mm": 0}}, only)
        on = app.compose({"text": "a", "options": {"z_variation_mm": .1}}, only)
        self.assertNotIn(" Z-0.100", off["gcode"])
        self.assertIn(" Z-0.100", on["gcode"])
        self.assertIn("G0 Z2.000", on["gcode"])

    def test_invalid_z_up_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Pen-up Z"):
            app.compose({"text": "a", "options": {"pen_up_z_mm": 0, "pen_down_z_mm": 1}}, self.store.all())

    def test_page_overflow_raises_instead_of_running_off_page(self):
        with self.assertRaisesRegex(ValueError, "page height"):
            app.compose({"text": "e\n" * 80, "options": {"page_height_mm": 45}}, self.store.all())


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = app.Store(Path(self.tmp.name) / "live.sqlite3")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.make_handler(self.store))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def req(self, path, method="GET", data=None):
        raw = None if data is None else json.dumps(data).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=raw, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.load(response)

    def test_http_save_list_compose_delete(self):
        code, saved = self.req("/api/samples", "POST", sample("hello"))
        self.assertEqual(code, 201)
        sample_id = saved["id"]
        code, listing = self.req("/api/samples")
        self.assertEqual(listing["samples"][0]["id"], sample_id)
        code, generated = self.req("/api/compose", "POST", {"text": "hello", "seed": 9})
        self.assertEqual(code, 200)
        self.assertIn("G1 X", generated["gcode"])
        code, removed = self.req("/api/samples/" + str(sample_id), "DELETE")
        self.assertTrue(removed["deleted"])
        self.assertEqual(self.req("/api/samples")[1]["samples"], [])

    def test_http_bad_input_returns_400_without_database_changes(self):
        bad = sample()
        bad["strokes"] = "not strokes"
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.req("/api/samples", "POST", bad)
        self.assertEqual(error.exception.code, 400)
        self.assertEqual(self.req("/api/samples")[1]["samples"], [])

    def test_http_static_page_and_unknown_route(self):
        with urllib.request.urlopen(self.base + "/", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"Handwriting Lab", response.read())
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.req("/api/unknown")
        self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
