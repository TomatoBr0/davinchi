# DaVinci Handwriting Plotter

Turn an XYZprinting Da Vinci 1.0 with a failed motherboard into a handwriting plotter, using an Elegoo Arduino Uno, the original X/Y/Z mechanics, and a personal library of handwritten strokes.

**Start here:** [From recorded handwriting to the Uno](docs/plotting.md). The local composer exports ordered stroke jobs, and the USB sender checks and streams them to the three-axis plotter sketch. Wiring, travel, steps/mm and pen heights still need verification on the real machine.

## Hardware handoff for Arduino development

Read [DAVINCI_HARDWARE_CONTEXT.md](DAVINCI_HARDWARE_CONTEXT.md) first for measured driver connections, corrected bench readings, unresolved pins and current-limit checks, and a disarmed-by-default Uno firmware brief. No motor motion has been verified yet.

The [220 x 285 x 10 mm paper-bed design](cad/base-plate/) includes the blank STL, editable OpenSCAD model, full-size fit-check SVG and original ZIP. Mounting positions and physical clearance remain unverified.

## Single-motor Arduino bench test

Open [DaVinci_One_Motor_Test.ino](firmware/DaVinci_One_Motor_Test/DaVinci_One_Motor_Test.ino) in its matching folder using Arduino IDE. Select **Arduino Uno**, choose the USB port, and upload with motor 12V disconnected. Read the [wiring and first-test instructions](firmware/DaVinci_One_Motor_Test/README.md) before connecting the driver/motor.

Serial Monitor: **115200 baud**. Send `s` for one bounded test (40 slow steps each way); `x` aborts. Outputs are disabled at boot and after each test. STEP = D2, DIR = D5, ENA = D8; use the external ENA pull-up described in the instructions. This standalone sketch replaces any current Uno firmware. The actual driver header's five middle control positions and VREF still need verification before applying motor power.

## $0-first hardware plan

**Buy nothing yet.** Check whether the Da Vinci's removable A4988 drivers survived the fried motherboard, and reuse the original 12V PSU, X/Y/Z motors, and Elegoo Uno. The CNC shield and ESP32 are optional for the first USB-controlled prototype. See [the $0-first salvage checklist](docs/zero-cost-build.md) and [hardware cautions](docs/hardware.md). Driver pinouts, motor-coil pairs, current limits and protective components must be verified before applying power.

## What works

- Record pen/touch/stylus movement in the browser, retaining **ordered paths**, pen lifts, timestamp and pressure (where supported).
- Optionally load an existing handwriting photo as a **tracing reference**, then trace real stroke order manually.
- Label saved samples as characters, letter combinations or full words, with optional preceding/following context.
- Keep all variants in a persistent SQLite library; delete unwanted samples.
- Compose typed text from saved sequences with seeded selection, weighting longer sequences and contextual compatibility, and controlled variation.
- Preview/export real **SVG** and **three-axis GRBL-style G-code**, including optional tiny Z variation. Z modulation defaults **off**.
- No web framework, cloud account, API keys or third-party runtime dependencies.

## Quick start

Requires Python 3.10+.

```bash
python app.py
```

Open http://127.0.0.1:8765 in a browser. To access the UI on a separate touchscreen, run the program on that device or set up an authenticated local tunnel. Do **not** expose this development server to the internet.

1. Enter a label such as `th`, `a`, or `together`.
2. Write it on the training canvas; optionally load a photo as a tracing layer.
3. Save many versions. Try connected pairs and actual words, not just the alphabet.
4. Type some text, choose settings, and click **Compose / preview**.
5. Download SVG to inspect or G-code to review. **Do not run the G-code on the printer until the hardware is rebuilt, homing is functional and directions/travel are calibrated.**

### Running tests

```bash
python -m unittest discover -s tests -v
```

The automated tests use actual SQLite transactions, the real HTTP endpoints, full composition and G-code output. Browser touchscreen input and physical motion require the separate manual checks in [docs/validation.md](docs/validation.md).

## File layout

```
app.py                 SQLite, composition engine, GRBL export, local HTTP API
web/index.html         touch and composition UI
web/app.js             browser pointer capture, local photo tracing, previews
web/style.css          responsive interface
tests/test_app.py      database/API/engine/export regression tests
docs/hardware.md       Arduino Uno, CNC shield, power and motion cautions
docs/validation.md     manual functional test checklist
```

## Design notes

- Samples capture **real pen-down strokes** as series of `{x,y,t,pressure}` points. Every pen lift starts a separate stroke.
- Each sample can represent a single character, a ligature, a complete word, or longer text. The renderer chooses context-aware chunks using weighted seeded selection, preserving within-sample joins.
- The original points are stored unchanged. Normalization happens only in the renderer.
- A **static photograph cannot reveal true stroke direction, pen lifts or pressure**. Tracing a photo is useful, but touchscreen/stylus recording is a more reliable source.
- Standard GRBL on Uno supports X/Y/Z steps, but the Da Vinci's motor pins, limit switches, driver current, Z direction, PSU and mechanics must be checked. A 12V PSU is **not** a suitable direct Arduino/servo supply.
- Z output is deliberately opt-in. Raising/lowering the heavy original bed per stroke may be slow, and tiny Z variations do not necessarily reproduce ballpoint pressure. Use a spring-loaded pen holder before experimenting.

## Current limitations

- Photo tracing is manual; automatic segmentation, handwriting recognition and photo-to-ordered-strokes reconstruction are future work.
- Variant selection is heuristic, not a trained ML handwriting model. Complex joins between *different* samples are not yet synthesized. For flowing handwriting, record longer connected sequences.
- An Uno cannot do photo processing or handwriting generation; the host computer does that work.
- SVG/G-code are exported in page coordinates, not in measured machine coordinates. The Uno sender uses manually measured calibration and a manual origin. Automatic homing and endstop monitoring are not implemented.
- Single-point ink marks/dots are represented as short dwell marks in G-code.

## License

No license is assigned yet. This avoids choosing legal terms for the repository without the owner's decision.
