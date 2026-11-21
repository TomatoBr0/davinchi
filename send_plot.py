"""Check and stream a Da Vinci stroke job. Install pyserial only for USB use."""
import argparse
import json
import math
import re
import sys
import time
from pathlib import Path


def preflight(source):
    commands = []
    xmax = ymax = feed = 0.0
    down = positioned = False
    strokes = 0
    for number, raw in enumerate(source.splitlines(), 1):
        line = raw.partition(";")[0].strip()
        if not line:
            continue
        fields = line.split()
        op = fields[0]
        try:
            if len(line) > 62 or not line.isascii():
                raise ValueError("invalid line length or encoding")
            if len(commands) < 2:
                if line != ("G21", "G90")[len(commands)]:
                    raise ValueError("job must start with G21 then G90")
            elif line == "M5":
                down = False
            elif line == "M3" and positioned and not down:
                down = True
                strokes += 1
            elif op in ("G0", "G1"):
                if (op == "G1") != down:
                    raise ValueError("unexpected pen state for XY move")
                args = {}
                for word in fields[1:]:
                    if not re.fullmatch(r"[XYF][0-9]+(?:\.[0-9]+)?", word) or word[0] in args:
                        raise ValueError("expected unique unsigned X, Y and F values")
                    args[word[0]] = float(word[1:])
                if args.keys() != {"X", "Y", "F"} or not all(map(math.isfinite, args.values())) or args["F"] <= 0:
                    raise ValueError("expected finite X, Y and positive F")
                xmax, ymax, feed = max(xmax, args["X"]), max(ymax, args["Y"]), max(feed, args["F"])
                positioned = True
            elif down and re.fullmatch(r"G4 P[0-9]+", line) and int(fields[1][1:]) <= 1000:
                pass
            else:
                raise ValueError("unsupported command or pen state")
        except ValueError as exc:
            raise ValueError(f"line {number}: {exc}") from exc
        commands.append(line)
    if feed > 600:
        raise ValueError("job exceeds the controller limit of 600 mm/min")
    if not strokes or commands[-1] != "M5":
        raise ValueError("expected at least one stroke and a final M5")
    return commands, (xmax, ymax, feed), strokes


def exchange(port, cmd, timeout=120):
    port.write((cmd + "\n").encode("ascii"))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reply = port.readline().decode("ascii", errors="replace").strip()
        if reply == "ok" or reply.startswith("ok "):
            return reply
        if reply:
            raise ValueError(f"{cmd}: {reply}")
    raise ValueError(f"no acknowledgment for {cmd}")


def calibration(path):
    profile = json.loads(path.read_text(encoding="utf-8"))
    keys = "XMM YMM ZMM XMIN XMAX YMIN YMAX ZMIN ZMAX PENUP PENDOWN".split()
    if not isinstance(profile, dict) or profile.keys() != set(keys):
        raise ValueError("calibration must contain exactly the keys in machine.example.json")
    for key in keys:
        value = profile[key]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"enter a measured number for {key}")
    for axis in "XYZ":
        if profile[axis+"MM"] <= 0 or profile[axis+"MIN"] >= profile[axis+"MAX"]:
            raise ValueError(f"invalid {axis} calibration")
    for axis in "XY":
        if profile[axis+"MIN"] != 0:
            raise ValueError("page origin requires XMIN and YMIN equal to zero")
    if not all(profile["ZMIN"] <= profile[k] <= profile["ZMAX"] for k in ("PENUP", "PENDOWN")) or profile["PENUP"] == profile["PENDOWN"]:
        raise ValueError("pen heights must be distinct and inside Z travel")
    return profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--port", help="USB port, e.g. COM4. Omit for offline validation.")
    parser.add_argument("--at-origin", action="store_true", help="confirm physical XY zero and calibrated pen-up height")
    parser.add_argument("--machine", type=Path, help="measured calibration JSON")
    args = parser.parse_args()
    commands, required, strokes = preflight(args.file.read_text(encoding="utf-8"))
    print(f"{strokes} strokes, max X {required[0]:g} mm, Y {required[1]:g} mm, feed {required[2]:g} mm/min")
    profile = calibration(args.machine) if args.machine else None
    if profile and (required[0] > profile["XMAX"] or required[1] > profile["YMAX"]):
        raise ValueError("job exceeds the measured XY travel")
    if not args.port:
        return
    if profile is None:
        parser.error("USB plotting requires --machine")
    if not args.at_origin:
        parser.error("manually position the machine, then add --at-origin")
    import serial
    with serial.Serial(args.port, 115200, timeout=0.25, write_timeout=2) as port:
        time.sleep(2)
        port.reset_input_buffer()
        exchange(port, "DISARM", 4)
        for key, value in {**profile, "XPOS": 0, "YPOS": 0, "ZPOS": profile["PENUP"]}.items():
            exchange(port, f"${key}={value}", 4)
        limits = exchange(port, "LIMITS", 4)
        match = re.fullmatch(r"ok X([0-9.]+) Y([0-9.]+) F([0-9.]+)", limits)
        if not match or any(need > float(maximum) for need, maximum in zip(required, match.groups())):
            raise ValueError(f"job exceeds controller limits or incompatible firmware: {limits}")
        try:
            exchange(port, "ARM", 4)
            for line in commands:
                exchange(port, line)
            exchange(port, "DISARM")
        except BaseException:
            port.write(b"!\n")
            raise
    print("Plot complete.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, ImportError) as error:
        sys.exit(str(error))
