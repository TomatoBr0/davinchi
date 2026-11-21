"""Uno three-axis G-code exporter for composed handwriting paths."""
from __future__ import annotations

import argparse
from pathlib import Path


def render_uno_gcode(strokes: list[list[tuple[float, float, float]]],
                     options: dict[str, float]) -> str:
    """Render composed XY paths as G21/G90, feed-qualified moves, and M3/M5."""
    travel_feed = min(float(options["travel_feed_mm_min"]), 600.0)
    write_feed = min(float(options["write_feed_mm_min"]), 600.0)
    if travel_feed <= 0 or write_feed <= 0:
        raise ValueError("feeds must be positive")
    lines = ["G21", "G90", "M5"]
    for stroke in strokes:
        if not stroke:
            continue
        x, y, _ = stroke[0]
        lines.append(f"G0 X{x:.3f} Y{y:.3f} F{travel_feed:.0f}")
        lines.append("M3")
        if len(stroke) == 1:
            # Firmware G4 P is milliseconds; a brief press leaves a dot.
            lines.append("G4 P80")
        else:
            for px, py, _pressure in stroke[1:]:
                lines.append(f"G1 X{px:.3f} Y{py:.3f} F{write_feed:.0f}")
        lines.append("M5")
    if not lines[-1] == "M5":
        lines.append("M5")
    return "\n".join(lines) + "\n"


def main() -> None:
    import app

    parser = argparse.ArgumentParser(description="Export composed handwriting for the Uno plotter")
    parser.add_argument("text", help="Text to compose from saved handwriting samples")
    parser.add_argument("-o", "--output", type=Path, default=Path("handwriting-uno.nc"))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--db", type=Path, default=app.DB_PATH)
    args = parser.parse_args()
    result = app.compose({"text": args.text, "seed": args.seed}, app.Store(args.db).all())
    if result["missing"]:
        parser.error("cannot export Uno G-code with missing glyphs")
    args.output.write_text(result["uno_gcode"], encoding="utf-8")
    print(f"Wrote {args.output} ({result['stroke_count']} strokes; preview only)")


if __name__ == "__main__":
    main()

