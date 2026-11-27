#!/usr/bin/env python3
"""First-contact self test and ruler calibration for the plotter firmware.

    python tools/bringup.py --port COM6                  # self test: config, one tiny jog, abort
    python tools/bringup.py --port COM6 --flash          # same, after arduino-cli upload
    python tools/bringup.py --port COM6 --calibrate      # interactive: identify axes, ruler-calibrate

The self test sends only configuration, one tiny jog and an abort. It does NOT
home, does not trust steps/mm and does not move far: at the default 1 step/mm a
20 "mm" jog is 20 steps, which is a fraction of a millimetre on any real gearing.

--calibrate walks each axis once: it moves a set distance, asks which part of the
machine actually moved and how far it went, then writes the corrected steps/mm
to EEPROM. The "which part moved" answers are what catch a motor plugged into
the wrong driver slot.

Every reply is printed with PASS/FAIL so a failure names the stage.
"""
from __future__ import annotations

import argparse
import sys
import time

try:
    import serial
except ImportError:  # pragma: no cover - documented fallback
    sys.exit("pyserial is not installed: run  pip install pyserial")

BAUD = 115200

# axis -> (commanded mm for the measuring move, feed mm/min)
# Z is the pen lift and the firmware caps its feed at 120 mm/min.
AXIS_TEST = {"X": (40.0, 600), "Y": (40.0, 600), "Z": (10.0, 100)}


class Board:
    def __init__(self, port, boot_wait=2.5):
        self.port = serial.Serial(port, BAUD, timeout=1.0, write_timeout=2.0)
        time.sleep(boot_wait)  # the Uno resets when the port opens
        self.boot = self.port.read(600).decode("ascii", errors="replace")
        self.port.reset_input_buffer()

    def close(self):
        try:
            self.port.close()
        except OSError:
            pass

    def read_reply(self, timeout=5.0):
        """Return the first ok/error line, ignoring the boot banner."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            raw = self.port.readline()
            if not raw:
                continue
            line = raw.decode("ascii", errors="replace").strip()
            if not line:
                continue
            print("   <", line, flush=True)
            if line == "ok" or line.startswith("ok ") or line.startswith("error:"):
                return line
        return ""

    def send(self, line, timeout=5.0):
        print("   >", line, flush=True)
        self.port.write((line + "\n").encode("ascii"))
        return self.read_reply(timeout)

    def abort(self):
        print("   > !  (abort)", flush=True)
        self.port.write(b"!\n")
        self.port.flush()
        return self.read_reply(3.0)


def _ask(prompt, default=""):
    try:
        raw = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit("stopped; the motors were left disabled")
    return raw if raw else default


def _steps_per_mm(reply, axis):
    """Pull one axis' steps/mm out of an M115 line."""
    if "STEPS" not in reply:
        return 0.0
    for token in reply.split("STEPS")[1].split():
        if token.startswith(axis):
            try:
                return float(token[1:])
            except ValueError:
                return 0.0
    return 0.0


def _setup_for_motion(board, travel=500.0, z_max=60.0, pen_up=5.0, pen_down=0.0):
    """RAM-only travel and pen endpoints, so ARM is allowed."""
    for line in ("$XMIN=0", "$XMAX={:.0f}".format(travel),
                 "$YMIN=0", "$YMAX={:.0f}".format(travel),
                 "$ZMIN=0", "$ZMAX={:.0f}".format(z_max),
                 "$PENUP={:g}".format(pen_up), "$PENDOWN={:g}".format(pen_down)):
        if board.send(line) != "ok":
            return False
    return True


def calibrate(board):
    """Interactive axis identification plus ruler calibration, one pass per axis."""
    print()
    print("Interactive calibration. For each axis the plotter makes one slow move.")
    print("Say which part physically moved, then how far it went. The corrected")
    print("steps/mm is written to EEPROM, so it survives a replug.")
    print()
    if not _setup_for_motion(board):
        print("could not set the RAM travel limits; nothing was moved")
        return 1

    results = {}
    observed = {}
    for axis, (distance, feed) in AXIS_TEST.items():
        placed = _steps_per_mm(board.send("M115"), axis)
        if placed <= 0:
            print("no steps/mm reported for {}; skipping".format(axis))
            continue
        label = "pen lift" if axis == "Z" else "{} carriage".format(axis)
        print("\n--- {} ({}): {:.0f} mm commanded at {:.3f} steps/mm "
              "= {:.0f} steps, feed {} ---".format(axis, label, distance, placed,
                                                   distance * placed, feed))
        print("    Make sure it has clearance. Enter = run, s = skip, q = stop.")
        choice = _ask("    run? ", "y").lower()
        if choice.startswith("q"):
            break
        if choice.startswith("s"):
            print("    skipped")
            continue

        if board.send("M210") != "ok" or board.send("ARM") != "ok":
            print("    could not arm; skipping")
            continue
        reply = board.send("J {}{:.0f} F{}".format(axis, distance, feed), timeout=180.0)
        board.send("M114")
        board.send("M18", 5.0)
        if reply != "ok":
            print("    move did not finish ({}); not using it".format(reply or "no reply"))
            continue

        part = _ask("    which part physically moved? [x/y/z, n = nothing] ").lower()
        if part:
            observed[axis] = part
        if part.startswith("n"):
            print("    nothing moved: check power, that axis' cable and driver")
            continue
        raw = _ask("    how far did it travel, in mm? ")
        if not raw:
            print("    no measurement, keeping the current value")
            continue
        try:
            measured = float(raw.replace(",", "."))
        except ValueError:
            print("    not a number, keeping the current value")
            continue
        if measured < 0.2:
            print("    that is too small to divide by, keeping the current value")
            continue

        steps = round(distance * placed)
        corrected = steps / measured
        if board.send("M92 {}{:.4f}".format(axis, corrected)) != "ok":
            print("    M92 was refused; keeping the current value")
            continue
        results[axis] = (placed, measured, corrected, steps)
        print("    {} steps over {:.1f} mm -> {:.3f} steps/mm (was {:.3f}), "
              "saved to EEPROM".format(steps, measured, corrected, placed))

    print("\n=== results ===")
    if not results:
        print("no axis was measured")
    for axis, (old, measured, new, steps) in results.items():
        print("  {}: {} steps -> {:.1f} mm  =  {:.3f} steps/mm (was {:.3f})"
              .format(axis, steps, measured, new, old))

    swapped = {a: p for a, p in observed.items() if p and not p.startswith(a)}
    if swapped:
        print("\n!! a commanded axis moved a different part of the machine:")
        for axis, part in swapped.items():
            print("!!   J {} moved the {} mechanism".format(axis, part.upper()))
        print("!! check which motor cable sits in which driver slot on the shield,")
        print("!! and which STEP/DIR pair that slot is wired to, before any drawing")
    else:
        print("\nEvery axis that moved, moved the part it should have.")

    print("\nNext, teach the travel: jog to the near corner, M210, jog to the far")
    print("corner, M211. Then draw the test square from the Calibrate tab.")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM6")
    parser.add_argument("--steps", type=float, default=1.0,
                        help="safe probing value; the real one comes from the ruler test")
    parser.add_argument("--jog", type=float, default=20.0,
                        help="commanded mm for the one test move; at 1 step/mm that is 20 steps")
    parser.add_argument("--z-max", type=float, default=20.0)
    parser.add_argument("--pen-up", type=float, default=5.0)
    parser.add_argument("--pen-down", type=float, default=0.0)
    parser.add_argument("--travel", type=float, default=200.0)
    parser.add_argument("--axis", default="X", choices=["X", "Y"],
                        help="axis for the single measuring move")
    parser.add_argument("--hold", action="store_true",
                        help="leave the drivers energised so the measured move cannot drift")
    parser.add_argument("--calibrate", action="store_true",
                        help="interactive: identify each axis by eye and measure steps/mm with a ruler")
    parser.add_argument("--flash", action="store_true", help="run arduino-cli upload first")
    args = parser.parse_args()

    if args.flash:
        import subprocess
        from pathlib import Path
        sketch = Path(__file__).resolve().parent.parent / "firmware" / "plotter"
        print("== flashing", sketch)
        result = subprocess.run(["arduino-cli", "upload", "-p", args.port,
                                 "--fqbn", "arduino:avr:uno", str(sketch)])
        if result.returncode:
            sys.exit("flash failed; if the port is busy, close the browser tab "
                     "or the serial monitor")

    try:
        board = Board(args.port)
    except Exception as exc:
        sys.exit("cannot open {}: {}\n"
                 "Release the port first: close the plotter page (Web Serial), the "
                 "Arduino IDE serial monitor, or VS Code's Serial Monitor, or unplug "
                 "and replug the Uno.".format(args.port, exc))

    if args.calibrate:
        try:
            return calibrate(board)
        finally:
            try:
                board.send("M18", 5.0)
            except Exception:
                pass
            board.close()

    checks = []

    def step(name, ok, detail=""):
        checks.append(ok)
        print(("PASS " if ok else "FAIL ") + name + ((" - " + detail) if detail else ""))

    try:
        first = board.boot.strip().splitlines()[0] if board.boot.strip() else "no banner"
        print("   boot:", first)
        step("firmware answers at boot", "DaVinci" in board.boot, first)

        reply = board.send("M115")
        step("M115 status", reply.startswith("ok CAL="), reply)
        print("   steps/mm before:", reply)

        reply = board.send("M92 X{} Y{} Z{}".format(args.steps, args.steps, args.steps))
        step("M92 probing steps/mm", reply == "ok", reply)

        for line in ("$XMIN=0", "$XMAX={}".format(args.travel),
                     "$YMIN=0", "$YMAX={}".format(args.travel),
                     "$ZMIN=0", "$ZMAX={}".format(args.z_max),
                     "$PENUP={:g}".format(args.pen_up),
                     "$PENDOWN={:g}".format(args.pen_down)):
            reply = board.send(line)
            step("set " + line.split("=")[0].lstrip("$"), reply == "ok", reply)

        reply = board.send("M210")
        step("M210 origin", reply == "ok", reply)

        reply = board.send("ARM")
        step("ARM (drivers on, no motion)", reply == "ok", reply)

        reply = board.send("J {}{:.0f} F600".format(args.axis, args.jog), timeout=90.0)
        step("measuring jog {}{:.0f} (steps={:.0f})".format(args.axis, args.jog,
                                                           args.jog * args.steps),
             reply == "ok", reply)

        reply = board.send("M114")
        step("M114 after jog", "known" in reply, reply)

        if args.hold:
            print("   drivers stay ON so the move cannot drift while you measure")
        else:
            reply = board.abort()
            step("! abort is accepted", reply.startswith("error:"), reply)

            reply = board.send("M115")
            step("abort left the board disarmed", "ARMED=0" in reply, reply)

            board.send("M18")
    finally:
        board.close()

    failed = checks.count(False)
    print()
    print("{}/{} checks passed".format(len(checks) - failed, len(checks)))
    print("Next: measure the {} travel and run  steps_per_mm = {:.0f} / measured_mm"
          .format(args.axis, args.jog * args.steps))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
