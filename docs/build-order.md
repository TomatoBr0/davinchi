# Build order

Each stage ends in a check you can observe before moving on. Stages in the same
column can run in parallel: software (left) needs no hardware until stage 6.

**Where the hardware is (2026-11-19, from [DAVINCI_HARDWARE_CONTEXT.md](../DAVINCI_HARDWARE_CONTEXT.md)):**
extruder A4988 module passively mapped (STEP, ENA, DIR, VREF divider; B2-B6 unknown),
extruder motor coil pairs found (~3 ohm each, no case short), logic-only 3.3 V test done
with rough VREF ~1-1.5 V. Pending: VREF on DCV 3, B2-B6 mapping, motor rated current, PSU
output check. **No motor has moved yet**, so stage 1 is mostly done and stage 3 is next
after the bench sketch. Record outcomes in that file.

| # | Stage | Done when |
|---|---|---|
| 0 | **Decide paper/work area.** Da Vinci 1.0 XY travel is ~200 x 200 mm; US Letter is 216 x 279. Choose: plot a 200 x 200 region, two-pass with ArUco re-registration, or extend Y. | Decision written here |
| 1 | **Teardown + $0 checks** (`docs/zero-cost-build.md`, step-by-step guide): label harnesses, coil pairs by multimeter, PSU label, driver chip ID | Coil pairs and PSU rating recorded |
| 2 | **Disarmed Uno bench sketch** (`firmware/uno-bench/`, spec in hardware context §12), then GRBL 1.1 later | Serial status works with ENA held disabled |
| 3 | **One motor, one driver** (extruder pair first), current-limited, 47 µF on VMOT; then X, Y, Z | Slow bounded steps, driver cool, disable works |
| 4 | **Endstops + homing + steps/mm** | `$H` works; 50 mm command measures 50 mm |
| 5 | **Paper plate + pen holder**: fit-check the 220 x 285 x 10 mm plate (`cad/base-plate/`), transfer the 3 mounts, add paper corners/markers; spring-loaded vertical mount (pencil: 0.7 mm 2B mechanical first) | 10 mm square, circle, word from `app.py` plot cleanly |
| 6 | **Dictation capture**: app shows a sentence, you write the whole line with a stylus; collect 300-500 lines | Lines stored with stroke order, pressure, text |
| 7 | **Pretrained handwriting RNN** (Graves; PyTorch port), primed with your recorded lines | One generated line plotted from G-code |
| 8 | **Fine-tune** on your lines (Colab, checkpoints) | Side-by-side with your real writing is hard to tell apart |
| 9 | **Page realism**: from schoolwork photos measure size/slant/margin drift per line; ramp sampling bias down the page | Full generated page looks like one of your pages |
| 10 | **Camera + ArUco**: markers 0-3 on the plate, homography to paper mm (`aruco_layout.json`) | Camera locates a drawn box to within ~0.5 mm |
| 11 | **Worksheets**: PDF box extraction (pdfplumber) + vision model for meaning → JSON layout → place strokes; hand-recorded symbols (subscripts, fractions) from the sample library | Plots answers inside the right boxes |
| 12 | **Voice model** (optional): few-shot first, QLoRA only if needed | Text reads like you |
| 13 | **Upgrades**: servo/light pen carriage for pressure, `G38.2` probed height map, pencil odometer + sharpener (FluidNC needed for a 4th motor) | Each upgrade measured before use |

Corrections carried from the brainstorm: GRBL is not Marlin (no `M302`/`M104`; home is
`$H`), stock Uno GRBL has no servo or E axis, don't let vpype reorder strokes, and don't
train stroke order from traced photos.
