# Work log (branch calibration-slicer-ui)

Updated as each piece lands. Nothing here has been run on hardware unless it says so.

| Work | Status | Where |
| --- | --- | --- |
| Calibration: X/Y 5 steps/mm, Z 160, +X = left, +Y = back | Done, tested on the printer | docs/hardware.md |
| Draw script (SVG to jog moves, pencil wear compensation, rotate/fit/pressure) | Done, lily, shuttle and Batman drawn | tools/davinci_draw.py, tools/davinci_jog.py |
| Line-art tracer (single line per ink stroke) | Done, shuttle drawn | tools/trace_lines.py, tools/davinci_preview.py |
| Sketch-style slicer + self-check match score | Tone fix, auto-tune (tune=1), per-stroke pressure, Hand sketch style in web slicer; 69 tests pass, not drawn yet | tools/sketch_style.py |
| Worksheet filling (Letter page in 4 placements, phone-photo page tracking) | Built, 57 tests pass, not tried on paper | tools/worksheet.py, docs/worksheet.md |
| Endstops (optical A/G/C, D9/D10/D11, ES / ESWATCH / G28 homing, off by default) | Built, compiles (50% flash), not uploaded or hardware-tested | firmware/plotter, docs/hardware.md |
| Nano ESP32 port with Wi-Fi (TCP 23, HTTP jog page, same commands) | Built, compiles, not uploaded; no Wi-Fi password in code (set by serial) | firmware/plotter_esp32 |
| Recreate slicer (strokes follow the original's lines, density matches its darkness, self-check) | Built, Batman preview 99% shape / 3.4% darkness off, not drawn | tools/recreate.py |
| Handwriting: upload notebook pages, label letters, read with Claude API, write in your hand | Built, 87 tests pass, needs real photos and pip install anthropic | tools/handwriting.py, web/handwriting.html, docs/handwriting.md |
| Phone relay (separate Cloudflare Worker: uploads + command queue, token auth, motion needs confirm) + laptop poller | Built, tests pass, not deployed; needs KV + secrets | cloud/relay, tools/relay_client.py |
| Carl assistant + DaVinci integration (Codex) | In progress, in the Carl repo | Carl repo |

To check: docs/plotting.md says +X moves right; on the printer +X moved left.
