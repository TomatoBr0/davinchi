"""Relay client tests with a fake HTTP layer. No local app, no serial port, no motion.

Run: python -m unittest discover -s tests -v
"""
import unittest

from tools import relay_client as rc

CFG = {"relay_url": "https://relay.example", "token": "t", "local_url": "http://127.0.0.1:9"}


class Fake:
    def __init__(self, queue, upload=b"\xff\xd8jpeg"):
        self.queue = list(queue)
        self.upload = upload
        self.calls = []

    def __call__(self, method, url, body=None, headers=None):
        self.calls.append((method, url, body))
        if url.endswith("/api/agent/next"):
            return 200, {"command": self.queue.pop(0) if self.queue else None}
        if "/api/agent/upload/" in url:
            return 200, self.upload
        return 200, {"ok": True, "gcode": "G1 X1"} if "photo" in url else {"ok": True}


def cmd(kind, **args):
    return {"id": "c1", "type": kind, "args": args}


class RelayClientTests(unittest.TestCase):
    def test_motion_refused_without_flag_and_no_local_call(self):
        fake = Fake([cmd("jog", dx=1)])
        self.assertTrue(rc.poll_once(CFG, fake, allow_motion=False, log=lambda *_: None))
        posted = [c for c in fake.calls if c[0] == "POST" and c[1].endswith("/result")][0][2]
        self.assertFalse(posted["ok"])
        self.assertFalse(any("/api/serial" in c[1] for c in fake.calls))

    def test_dry_run_never_calls_local_app(self):
        fake = Fake([cmd("start", gcode="G1 X1")])
        rc.poll_once(CFG, fake, allow_motion=True, dry_run=True, log=lambda *_: None)
        self.assertFalse(any(c[1].startswith(CFG["local_url"]) for c in fake.calls))

    def test_jog_over_limit_is_refused(self):
        with self.assertRaises(ValueError):
            rc.jog_lines({"dx": 50})

    def test_jog_builds_relative_moves(self):
        self.assertEqual(rc.jog_lines({"dx": 1})[0:1], ["G91"])

    def test_preview_forwards_gcode_for_start(self):
        fake = Fake([cmd("preview", upload_id="u1")])
        rc.poll_once(CFG, fake, log=lambda *_: None)
        posted = [c for c in fake.calls if c[1].endswith("/result")][0][2]
        self.assertEqual(posted["gcode"], "G1 X1")
        self.assertTrue(posted["ok"])


if __name__ == "__main__":
    unittest.main()
