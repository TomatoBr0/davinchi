"""Serial link tests against a fake port that answers like the firmware.

Run: python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from collections import deque
from http.server import ThreadingHTTPServer
from pathlib import Path

import app

JOB = "G21\nG90\nM5\nG0 X1 Y1 F600\nM3\n" + "G1 X2 Y2 F300\n" * 30 + "M5\n"


class FakeSerial:
    """Mimics pyserial: one reply line per written command, as the firmware does."""

    def __init__(self, origin=1, fail_on=(), slow_g1=0.0):
        self.origin, self.fail_on, self.slow_g1 = origin, set(fail_on), slow_g1
        self.written, self.replies, self.closed = [], deque(), False

    def reset_input_buffer(self):
        self.replies.clear()

    def write(self, data):
        line = data.decode("ascii").strip()
        self.written.append(line)
        if line == "!":
            self.replies.append(b"error: aborted; position invalid\n")
        elif line in self.fail_on:
            self.replies.append(b"error: travel limit\n")
        elif line == "M115":
            self.replies.append(f"ok CAL=1 ORIGIN={self.origin} ARMED=1 MAX X160.000 Y190.000 Z0.000 "
                                "STEPS X80.000 Y80.000 Z80.000\n".encode())
        elif line == "M114":
            self.replies.append(b"ok X1.000 Y2.000 Z0.000 known\n")
        elif line == "LIMITS":
            self.replies.append(b"ok X160.000 Y190.000 F600\n")
        else:
            if line.startswith("G1") and self.slow_g1:
                time.sleep(self.slow_g1)
            self.replies.append(b"ok\n")
        return len(data)

    def readline(self):
        return self.replies.popleft() if self.replies else b""

    def flush(self):  # pyserial has it; nothing is buffered here
        pass

    def close(self):
        self.closed = True


def wait_for_state(test, link, state, timeout=10):
    deadline = time.monotonic() + timeout
    while link.job["state"] != state and time.monotonic() < deadline:
        time.sleep(.01)
    test.assertEqual(link.job["state"], state, link.job)


class MachineLinkTests(unittest.TestCase):
    def link(self, fake):
        return app.MachineLink(opener=lambda port: fake, reset_wait=0)

    def test_status_parsing_matches_firmware_replies(self):
        status = app.parse_status("ok CAL=1 ORIGIN=0 ARMED=1 MAX X160.000 Y190.000 Z0.000 STEPS X80.000 Y81.500 Z80.000")
        self.assertEqual((status["cal"], status["origin"], status["armed"]), (True, False, True))
        self.assertEqual(status["stepsY"], 81.5)
        self.assertEqual(app.parse_position("ok X1.000 Y2.000 Z-0.500 unknown")["known"], False)
        self.assertIsNone(app.parse_status("ok nonsense"))

    def test_errors_surface_and_job_streams_to_done(self):
        fake = FakeSerial(fail_on={"M92 X0"})
        link = self.link(fake)
        link.connect("COM4")
        self.assertEqual(link.send("M17"), "ok")
        with self.assertRaisesRegex(app.MachineError, "travel limit"):
            link.send("M92 X0")
        link.start_job(JOB, "square")
        wait_for_state(self, link, "done")
        self.assertIn("ARM", fake.written)
        self.assertEqual(fake.written.count("G1 X2 Y2 F300"), 30)
        self.assertEqual(fake.written[-1], "M5")
        self.assertFalse(any(cmd.startswith("DISARM") for cmd in fake.written))

    def test_job_refused_without_origin_or_valid_program(self):
        link = self.link(FakeSerial(origin=0))
        link.connect("COM4")
        with self.assertRaisesRegex(app.MachineError, "origin"):
            link.start_job(JOB)
        bad = app.MachineLink(opener=lambda port: FakeSerial(), reset_wait=0)
        bad.connect("COM4")
        with self.assertRaisesRegex(app.MachineError, "G21"):
            bad.start_job("G1 X1 Y1 F60\n")

    def test_pause_then_stop_lifts_pen_and_writes_nothing_after(self):
        fake = FakeSerial(slow_g1=.002)
        link = self.link(fake)
        link.connect("COM4")
        link.start_job(JOB)
        link.pause()
        wait_for_state(self, link, "paused")
        link.stop()
        wait_for_state(self, link, "stopped")
        self.assertEqual(fake.written[-1], "M5")
        self.assertLess(fake.written.count("G1 X2 Y2 F300"), 30)

    def test_error_reply_stops_job_and_lifts_pen(self):
        fake = FakeSerial(fail_on={"G1 X2 Y2 F300"})
        link = self.link(fake)
        link.connect("COM4")
        link.start_job(JOB)
        wait_for_state(self, link, "error")
        self.assertIn("travel limit", link.job["error"])
        self.assertEqual(fake.written[-1], "M5")
        self.assertEqual(fake.written.count("G1 X2 Y2 F300"), 1)


class MachineHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeSerial()
        self.link = app.MachineLink(opener=lambda port: self.fake, reset_wait=0)
        store = app.Store(Path(self.tmp.name) / "machine.sqlite3")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.make_handler(store, self.link))
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
            return response.status, response.read()

    def test_connect_send_status_over_http(self):
        self.req("/api/serial/connect", "POST", {"port": "COM4"})
        _, raw = self.req("/api/serial/send", "POST", {"line": "M114"})
        self.assertEqual(json.loads(raw)["reply"], "ok X1.000 Y2.000 Z0.000 known")
        _, raw = self.req("/api/serial/status")
        snapshot = json.loads(raw)
        self.assertTrue(snapshot["connected"])
        self.assertEqual(snapshot["status"]["stepsX"], 80.0)
        self.assertTrue(snapshot["status"]["origin"])

    def test_job_refused_without_origin_returns_400(self):
        self.fake.origin = 0
        self.req("/api/serial/connect", "POST", {"port": "COM4"})
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.req("/api/serial/job", "POST", {"text": JOB, "name": "t"})
        self.assertEqual(error.exception.code, 400)
        self.assertIn(b"origin", error.exception.read())

    def test_calibration_file_served_and_send_requires_connection(self):
        _, raw = self.req("/calibration_test.nc")
        self.assertTrue(raw.startswith(b"G21"))
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.req("/api/serial/send", "POST", {"line": "M114"})
        self.assertEqual(error.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
