"""Laptop-side poller for the remote plotter relay (cloud/relay/worker.js).

Polls the Worker outbound, runs each command against the local app (app.py),
and posts the result back so the phone can see it.

Env: DAVINCHI_RELAY_URL (Worker origin), DAVINCHI_AGENT_TOKEN (secret, never in code),
     DAVINCHI_LOCAL_URL (default http://127.0.0.1:8775).

Motion (start, jog) is refused unless --allow-motion is passed. --dry-run never calls the
local app at all; it only reports what it would do. Never opens a COM port itself.

Run: python tools/relay_client.py --dry-run --once
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

MOTION = {"start", "jog"}
JOG_LIMIT_MM = 10.0


def http_call(method, url, body=None, headers=None):
    """Return (status, parsed-json-or-bytes). Raises on network error."""
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if data is not None and "Content-Type" not in (headers or {}):
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            return resp.status, (json.loads(raw) if "json" in ctype else raw)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def jog_lines(args):
    dx, dy, dz = (float(args.get(k, 0)) for k in ("dx", "dy", "dz"))
    for v in (dx, dy, dz):
        if abs(v) > JOG_LIMIT_MM:
            raise ValueError(f"jog step over {JOG_LIMIT_MM} mm refused")
    feed = min(max(float(args.get("feed", 600)), 60.0), 1200.0)
    return ["G91", f"G1 X{dx:.3f} Y{dy:.3f} Z{dz:.3f} F{feed:.0f}", "G90"]


def run_command(cmd, cfg, call, allow_motion=False, dry_run=False):
    """Execute one relay command. Returns (ok, summary, result_dict, gcode_or_None)."""
    kind, args = cmd.get("type"), cmd.get("args") or {}
    local = cfg["local_url"].rstrip("/")
    if kind in MOTION and not allow_motion:
        return False, "motion disabled on laptop (start relay_client with --allow-motion)", {}, None
    if dry_run:
        return True, f"dry-run: would handle {kind}", {"dry_run": True}, None

    if kind == "status":
        _, data = call("GET", local + "/api/serial/status")
        return True, "status", data, None

    if kind == "handwriting_upload":
        img = fetch_upload(cfg, args["upload_id"], call)
        _, data = call("POST", local + "/api/handwriting/upload",
                       {"data": base64.b64encode(img).decode()})
        return True, "uploaded to handwriting library", data, None

    if kind in ("preview", "slice"):
        img = fetch_upload(cfg, args["upload_id"], call)
        _, data = call("POST", local + "/api/photo", {"data": base64.b64encode(img).decode()})
        gcode = data.get("gcode") if isinstance(data, dict) else None
        return True, f"{kind} done", data, gcode if isinstance(gcode, str) else None

    if kind == "start":
        gcode = args.get("gcode")
        if not isinstance(gcode, str) or not gcode:
            return False, "no gcode in start command", {}, None
        _, data = call("POST", local + "/api/serial/job", {"text": gcode, "name": "relay"})
        return True, "job started", data, None

    if kind == "stop":
        _, data = call("POST", local + "/api/serial/job/stop", {})
        return True, "stop sent", data, None

    if kind == "jog":
        replies = []
        for line in jog_lines(args):
            _, data = call("POST", local + "/api/serial/send", {"line": line})
            replies.append(data)
        return True, "jog sent", {"replies": replies}, None

    return False, f"unknown command {kind}", {}, None


def fetch_upload(cfg, upload_id, call):
    _, data = call("GET", cfg["relay_url"].rstrip("/") + "/api/agent/upload/" + upload_id)
    if not isinstance(data, (bytes, bytearray)):
        raise RuntimeError("upload missing on relay")
    return bytes(data)


def agent_headers(token):
    return {"Authorization": f"Bearer {token}"}


def poll_once(cfg, call, allow_motion=False, dry_run=False, log=print):
    relay = cfg["relay_url"].rstrip("/")
    headers = agent_headers(cfg["token"])
    _, data = call("GET", relay + "/api/agent/next", None, headers)
    cmd = data.get("command") if isinstance(data, dict) else None
    if not cmd:
        return False
    try:
        ok, summary, result, gcode = run_command(cmd, cfg, call, allow_motion, dry_run)
    except Exception as exc:  # report every failure to the phone
        ok, summary, result, gcode = False, f"error: {exc}", {}, None
    body = {"command_id": cmd["id"], "ok": ok, "summary": summary, "result": result}
    if gcode:
        body["gcode"] = gcode
    call("POST", relay + "/api/agent/result", body, {**headers})
    log(f"{cmd['id']} {cmd.get('type')}: {'ok' if ok else 'FAILED'} - {summary}")
    return True


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--interval", type=float, default=3.0)
    p.add_argument("--once", action="store_true", help="poll one time and exit")
    p.add_argument("--dry-run", action="store_true", help="never call the local app")
    p.add_argument("--allow-motion", action="store_true", help="permit start/jog to run")
    a = p.parse_args(argv)
    token = os.environ.get("DAVINCHI_AGENT_TOKEN", "")
    relay = os.environ.get("DAVINCHI_RELAY_URL", "")
    if not token or not relay:
        print("Set DAVINCHI_RELAY_URL and DAVINCHI_AGENT_TOKEN", file=sys.stderr)
        return 2
    cfg = {"relay_url": relay, "token": token,
           "local_url": os.environ.get("DAVINCHI_LOCAL_URL", "http://127.0.0.1:8775")}
    while True:
        try:
            poll_once(cfg, http_call, a.allow_motion, a.dry_run)
        except (urllib.error.URLError, OSError) as exc:
            print(f"relay unreachable: {exc}", file=sys.stderr)
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
