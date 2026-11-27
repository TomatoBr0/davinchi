"""Handwriting: synthetic notebook photos (cv2.putText on white). No camera, no API calls.

Run: python -m pytest tests/test_handwriting.py -q
"""
import base64
import importlib.machinery
import json
import os
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from tools import handwriting as hw  # noqa: E402  same module object app.py uses (OcrUnavailable identity)
import app  # noqa: E402
from davinci_draw import parse_svg  # noqa: E402


def notebook_png(lines=(("hello", 150), ("world", 330)), ruled=True):
    """White page with black Hershey text and an optional ruled line (like notebook paper)."""
    img = np.full((460, 900, 3), 255, np.uint8)
    for text, y in lines:
        cv2.putText(img, text, (60, y), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 4, cv2.LINE_AA)
    if ruled:
        cv2.line(img, (0, 200), (899, 200), (180, 60, 60), 2)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


class HarvestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hand = hw.Handwriting(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def upload(self, raw=None, name="page.png"):
        raw = raw or notebook_png()
        return self.hand.upload({"filename": name, "data": base64.b64encode(raw).decode()})

    def test_upload_finds_two_lines_and_glyph_candidates(self):
        r = self.upload()
        self.assertEqual(r["lines"], 2)
        self.assertGreaterEqual(r["glyphs"], 8)  # 5 + 5 letters, a little slack for merges
        detail = self.hand.detail(r["id"])
        self.assertEqual(len(detail["lines"]), 2)
        for g in self.hand.detail(r["id"])["glyphs"]:
            self.assertEqual(g["char"], "")

    def test_original_is_kept_and_index_lists_it(self):
        raw = notebook_png()
        r = self.upload(raw)
        self.assertEqual((self.hand.samples_dir / f"{r['id']}.png").read_bytes(), raw)
        self.assertEqual(self.hand.samples()[0]["id"], r["id"])
        self.assertTrue(self.hand.page_png(r["id"]).startswith(b"\x89PNG"))

    def test_skeleton_is_thin_and_polylines_cover_a_bar(self):
        mask = np.zeros((20, 40), np.uint8)
        mask[8:12, 5:35] = 1  # 4px thick bar
        sk = hw.zhang_suen(mask)
        self.assertLessEqual(sk.sum(), 40)  # collapses toward one pixel row
        paths = hw.skeleton_polylines(sk)
        self.assertEqual(len(paths), 1)
        cols = [c for _, c in paths[0]]
        self.assertGreaterEqual(max(cols) - min(cols), 25)

    def test_deskew_recovers_a_tilted_page(self):
        upright = notebook_png(ruled=False)
        img = cv2.imdecode(np.frombuffer(upright, np.uint8), cv2.IMREAD_GRAYSCALE)
        h, w = img.shape
        tilted = cv2.warpAffine(img, cv2.getRotationMatrix2D((w / 2, h / 2), 4, 1), (w, h), borderValue=255)
        ink = hw.ink_mask(tilted)
        angle = hw.estimate_skew(cv2.resize(ink, None, fx=.9, fy=.9, interpolation=cv2.INTER_AREA))
        self.assertAlmostEqual(abs(angle), 4, delta=1.0)

    def test_ruled_line_is_not_a_text_line(self):
        gray = cv2.imdecode(np.frombuffer(notebook_png(lines=(), ruled=True), np.uint8), cv2.IMREAD_GRAYSCALE)
        self.assertEqual(hw._line_runs(hw.ink_mask(gray)), [])


class LabelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hand = hw.Handwriting(Path(self.tmp.name))
        self.sid = self.hand.upload({"filename": "p.png", "data": base64.b64encode(notebook_png()).decode()})["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def line_glyphs(self, line_id):
        return sorted((g for g in self.hand.detail(self.sid)["glyphs"] if g["line_id"] == line_id),
                      key=lambda g: g["bbox"][0])

    def test_transcription_labels_the_line_left_to_right(self):
        line = self.hand.detail(self.sid)["lines"][0]["id"]
        n = len(self.line_glyphs(line))
        self.assertEqual(n, 5)  # h e l l o
        self.hand.transcribe({"line": line, "text": "hello"})
        self.assertEqual("".join(g["char"] for g in self.line_glyphs(line)), "hello")
        self.assertTrue(all(g["char"] for g in self.line_glyphs(line)))

    def test_mismatched_count_is_a_guess_and_manual_fix_sticks(self):
        line = self.hand.detail(self.sid)["lines"][1]["id"]
        self.hand.transcribe({"line": line, "text": "wo r l d s"})  # 6 letters for 5 boxes
        gs = self.line_glyphs(line)
        self.assertTrue(all(g["char"] for g in gs))
        self.assertTrue(all(g["source"] == "guess" for g in gs))
        self.hand.label({"glyph": gs[0]["id"], "char": "Q"})
        first = self.line_glyphs(line)[0]
        self.assertEqual((first["char"], first["source"]), ("Q", "manual"))
        self.hand.label({"glyph": gs[0]["id"], "char": ""})
        self.assertEqual(self.line_glyphs(line)[0]["char"], "")

    def test_bad_label_input_is_rejected(self):
        with self.assertRaises(ValueError):
            self.hand.label({"glyph": "nope", "char": "a"})
        with self.assertRaises(ValueError):
            self.hand.label({"glyph": "x", "char": "ab"})


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hand = hw.Handwriting(Path(self.tmp.name))
        self.sid = self.hand.upload({"filename": "p.png", "data": base64.b64encode(notebook_png()).decode()})["id"]
        line = self.hand.detail(self.sid)["lines"][0]["id"]
        self.hand.transcribe({"line": line, "text": "hello"})
        self.glyphs = self.hand._glyphs()["glyphs"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_labeled_glyphs_are_used_and_seeded(self):
        a = hw.render_text("hello", 8, self.glyphs, seed=1)
        b = hw.render_text("hello", 8, self.glyphs, seed=1)
        self.assertEqual(a, b)
        self.assertTrue(a and all(len(pl) >= 2 for pl in a))
        xs = [x for pl in a for x, _ in pl]
        self.assertGreater(max(xs) - min(xs), 8)  # wider than one letter

    def test_size_scales_output(self):
        small = [p for pl in hw.render_text("hello", 4, self.glyphs, seed=2) for p in pl]
        big = [p for pl in hw.render_text("hello", 12, self.glyphs, seed=2) for p in pl]
        self.assertGreater(max(y for _, y in big) - min(y for _, y in big),
                           2 * (max(y for _, y in small) - min(y for _, y in small)))

    def test_unlabeled_letters_fall_back_to_builtin_font(self):
        paths = hw.render_text("XYZ 123\nab", 8, glyphs=[])
        self.assertGreater(len(paths), 10)

    def test_unknown_character_is_an_error(self):
        with self.assertRaises(ValueError):
            hw.render_text("é", 8, glyphs=[])

    def test_svg_is_parseable_by_davinci_draw(self):
        svg = hw.to_svg(hw.render_text("hi", 8, self.glyphs, seed=3))
        self.assertIn("<path", svg)
        strokes = parse_svg(svg)
        self.assertGreater(len(strokes), 0)
        self.assertGreater(len(strokes[0][0]), 1)


class OcrTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hand = hw.Handwriting(Path(self.tmp.name))
        self.sid = self.hand.upload({"filename": "p.png", "data": base64.b64encode(notebook_png()).decode()})["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_backend_says_so(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(hw.shutil, "which", return_value=None):
            with self.assertRaisesRegex(hw.OcrUnavailable, "No OCR backend configured"):
                self.hand.read({"id": self.sid})

    def test_anthropic_backend_sends_image_and_returns_text(self):
        seen = {}

        class FakeMessages:
            def create(self, **kw):
                seen.update(kw)
                block = types.SimpleNamespace(type="text", text="hello\nworld")
                return types.SimpleNamespace(stop_reason="end_turn", content=[block])

        fake = types.ModuleType("anthropic")
        fake.__spec__ = importlib.machinery.ModuleSpec("anthropic", None)
        fake.Anthropic = lambda: types.SimpleNamespace(messages=FakeMessages())
        env = {"ANTHROPIC_API_KEY": "test-not-real"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.dict(sys.modules, {"anthropic": fake}), \
                mock.patch.object(hw.shutil, "which", return_value=None):
            out = self.hand.read({"id": self.sid})
        self.assertEqual(out, {"backend": "anthropic", "text": "hello\nworld"})
        self.assertEqual(seen["model"], "claude-sonnet-5-5")
        image = seen["messages"][0]["content"][0]
        self.assertEqual(image["type"], "image")
        self.assertEqual(image["source"]["media_type"], "image/png")
        self.assertNotIn("test-not-real", json.dumps(seen))  # key never goes into the request body


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        hand = hw.Handwriting(Path(cls.tmp.name) / "hw")
        store = app.Store(Path(cls.tmp.name) / "s.sqlite3")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.make_handler(store, None, hand))
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def call(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method="POST" if body is not None else "GET",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.headers.get("Content-Type", ""), r.read()
        except urllib.error.HTTPError as e:
            return e.code, "", e.read()

    def test_upload_list_detail_page_transcribe_render(self):
        raw = notebook_png()
        status, _, body = self.call("/api/handwriting/upload", {"filename": "p.png", "data": base64.b64encode(raw).decode()})
        self.assertEqual(status, 201)
        sid = json.loads(body)["id"]
        status, _, body = self.call("/api/handwriting/samples")
        self.assertEqual(json.loads(body)["samples"][-1]["id"], sid)
        status, ctype, png = self.call(f"/api/handwriting/sample/{sid}/page.png")
        self.assertEqual((status, ctype), (200, "image/png"))
        self.assertTrue(png.startswith(b"\x89PNG"))
        detail = json.loads(self.call(f"/api/handwriting/sample/{sid}")[2])
        line = detail["lines"][0]["id"]
        status, _, body = self.call("/api/handwriting/transcribe", {"line": line, "text": "hello"})
        self.assertEqual(status, 200)
        status, _, body = self.call("/api/handwriting/render", {"text": "hello", "size_mm": 8, "seed": 4})
        self.assertEqual(status, 200)
        self.assertIn("<svg", json.loads(body)["svg"])
        status, _, _ = self.call(f"/api/handwriting/sample/999")
        self.assertEqual(status, 404)

    def test_read_without_backend_is_503(self):
        _, _, body = self.call("/api/handwriting/upload", {"filename": "p.png", "data": base64.b64encode(notebook_png()).decode()})
        sid = json.loads(body)["id"]
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(hw.shutil, "which", return_value=None):
            status, _, body = self.call("/api/handwriting/read", {"id": sid})
        self.assertEqual(status, 503)
        self.assertIn("No OCR backend configured", json.loads(body)["error"])

    def test_bad_upload_is_400(self):
        status, _, body = self.call("/api/handwriting/upload", {"filename": "p.heic", "data": "AAAA"})
        self.assertEqual(status, 400)
        status, _, _ = self.call("/api/handwriting/upload", {"filename": "p.png", "data": base64.b64encode(b"nope").decode()})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
