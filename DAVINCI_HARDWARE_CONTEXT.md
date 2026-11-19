# Da Vinci plotter: hardware and Arduino handoff

Last updated: November 19, 2026, America/Los_Angeles.
Owner: Caleb Darjany. Repository: https://github.com/TomatoBr0/davinchi

Repository assets: [base-plate CAD and ZIP](cad/base-plate/). Original photos and test-diagram files are not included in this GitHub upload; their references below identify evidence held by Caleb. All electrical results below retain their stated verification status.

## Read this first

This file consolidates the hardware investigation and user-reported bench measurements from the November 18-19 conversation. It is context for Claude Code or another coding assistant, not a complete, electrically verified wiring schematic.

**Current milestone: the removed extruder A4988 module has received logic power only. No successful motor rotation, motor holding test, 12 V driver-power test, firmware upload, homing, or plotting has been reported.**

The immediate unfinished test is a better VREF measurement on the meter's DCV 3 range, with only 3.3 V logic connected. The motor and 12 V supply remain disconnected for that test. The remaining control header pins and motor-rated current are also unresolved.

Do not convert a proposed test or a suggested connection into a completed result. Preserve the distinction between user-confirmed continuity, photograph markings, approximate meter readings, and assumptions.

## 1. Goal and working preferences

- Convert an XYZprinting Da Vinci 1.0 with a reported failed motherboard into a pen/handwriting plotter.
- Reuse its mechanics, X/Y/Z motors, PSU, and removable driver modules where practical.
- Use an already-owned Elegoo Arduino Uno; an ESP32 is also available for possible later work.
- Keep cost as close to zero as practical. No CNC shield has been confirmed available; the first prototype may use individually wired salvaged modules.
- First move one motor on the bench. Later control X/Y/Z and fit a compliant pen holder.
- The extruder is unnecessary for plotting. Caleb explicitly accepts risking the extruder motor and its driver as the experimental test pair. This does not mean the Uno, phone/computer, PSU, or other axes are expendable.
- Prefer concrete, small steps and references to writing visible on the board. Bare pin numbers and changing front/back orientations caused confusion.
- User shorthand: R6 = R306; R7 = R307. These are board reference designators, not resistance values.
- Avoid unsupported assurances. Challenge assumptions, especially that coil resistance establishes rated current, a larger plate expands reachable travel, or passive electrical checks prove a driver is functional.

## 2. Hardware inventory and markings

| Item | Observed or reported detail |
|---|---|
| Printer | XYZprinting Da Vinci 1.0; confirm exact machine-label revision before revision-specific wiring |
| Mainboard silkscreen | `3DP03-ES021`, `MB R5`, date `2013/12/26` |
| Driver boards | Four installed removable green modules; an additional empty footprint exists to their left |
| Driver module silkscreen | `3DP01 MOTOR R2`, `(3DP01-E0015)`, date `2013/10/16` |
| Driver IC | Clearly photographed `4988ET`; Allegro A4988, 28-contact QFN |
| Current-sense resistors | R301 and R302, both clearly marked `R200` = 0.20 ohm |
| Current-reference resistors | R306/R307 are unmarked or unreadable; actual component values NOT established |
| Test pad | Orange/copper round pad to the right of the chip, near R306/R307 |
| Controller | Elegoo Uno, intended Arduino Uno R3-compatible; exact board/USB-serial variant not documented |
| Optional controller | ESP32 owned; exact board type not established |
| Meter | Micronta 22-211 analog folding multimeter |
| PSU | AcBel FLXA5201A, option 02XA, revision B00 |

### PSU nameplate, not measured outputs

| Rail | Nameplate rating |
|---|---:|
| +3.3 V | 12 A |
| +5 V | 14 A |
| +12 V | 15 A |
| -12 V | 0.3 A |
| +5Vsb | 2 A |

The +3.3/+5 V rails have a combined 75 W limit; total nameplate power is 200 W. These ratings are not all simultaneously additive. The user reports the PSU works, but no multimeter-confirmed output pin mapping, voltage/polarity, or isolated bench power-on behavior has been recorded. Do not assume wire colors or an ATX-style enable procedure from the nameplate alone. Keep the PSU enclosure closed and its mains wiring intact. Disconnect/isolate heater circuits for the plotter conversion.

## 3. Which driver belongs to which motor

With the motherboard viewed as in the original photos: USB connector at the right, PSU below, four populated driver modules in a 2-by-2 group:

| Module position | Identification used in the session |
|---|---|
| Upper-left populated module | Extruder; intended test driver |
| Upper-right | Z / bed |
| Lower-left | X |
| Lower-right | Y |

This mapping was inferred from an annotated Da Vinci 1.0 motherboard photograph with matching connector positions but a different revision. **Physical cable tracing to the actual motors was recommended; its completion was not reported.** Do not treat all four identifications as independently measured. The extruder motor plug is the four-wire plug directly above the upper-left populated module. Ignore the empty module footprint farther left.

Reference image: https://www.techmonkeybusiness.com/images/Tech/DaVinci_Motherboard-sml.jpg

## 4. Orientation convention: use this consistently

**Component/front side facing you, writing upright:**

- `12V` printed at upper-left.
- `ENA` printed at lower-left.
- `DIR` printed at lower-right.
- Large power/motor header pads run along the top; control pads run along the bottom.

The header positions below are local labels for this document, NOT IC contact numbers. Call the top row T1-T8 and bottom row B1-B8, left to right in the front view, to avoid ambiguous references such as "pin 7".

Flipping to the underside reverses left/right if the same top edge is retained. In the user's underside photo, the pad next to `J301` at lower-left corresponds to front-side DIR/B8. `J301` labels the header, not an electrical signal by itself. Do not mix underside positions with this front-view table.

### Top header: photograph markings plus continuity tests

| Position | Signal | Evidence/status |
|---|---|---|
| T1 | +12 V / VMOT | Printed `12V`; motor supply not powered during recorded tests |
| T2 | Ground | User measured T2-T8 approximately 0 ohm |
| T3 | 2B | Printed label |
| T4 | 2A | Printed label |
| T5 | 1A | Printed label |
| T6 | 1B | Printed label |
| T7 | VDD logic supply | Printed `VDD`; used for 3.3 V logic-only test |
| T8 | Ground | Continuity to T2; used as measurement reference |

### Bottom control header: do not fill unknowns from a generic carrier

| Position | Signal | Evidence/status |
|---|---|---|
| B1 | ENA / active-low enable | Printed `ENA`; no separate chip-continuity result recorded |
| B2 | UNKNOWN | Needs mapping |
| B3 | UNKNOWN | Needs mapping |
| B4 | UNKNOWN | Needs mapping |
| B5 | UNKNOWN | Needs mapping |
| B6 | UNKNOWN | Needs mapping |
| B7 | STEP | User confirmed approximately 0 ohm to A4988 IC contact 16 |
| B8 | DIR | Printed `DIR`; no completed separate chip-continuity result recorded |

Generic Pololu carriers often place MS1/MS2/MS3/RESET/SLEEP in the five middle locations. **That arrangement has NOT been established for this module.** There are five unmapped positions B2-B6 after STEP was confirmed. Earlier conversation referred to six unknown middle positions before STEP was mapped; do not retain that stale count.

## 5. Chip-contact landmarks for continuity mapping

From Allegro's A4988 datasheet, component side with chip text upright:

| Chip edge | Contact(s) and function |
|---|---|
| Right, top to bottom | 21 OUT1B; 20 NC; 19 DIR; 18 GND; 17 REF; 16 STEP; 15 VDD |
| Bottom, left to right | 8 VREG; 9 MS1; 10 MS2; 11 MS3; 12 RESET; 13 ROSC; 14 SLEEP |
| Left | Contact 2 is ENABLE; use the datasheet's full orientation diagram before probing |

Printed `21` is beside the chip's upper-right edge; printed `15` is beside its lower-right edge. Printed `14` is below the chip, on a DIFFERENT edge.

- STEP contact 16 is the right-edge contact immediately ABOVE the contact beside printed `15`.
- REF contact 17 is the next right-edge contact ABOVE STEP, two contacts above 15.
- Do not mistake `U301`, `J301`, or a resistor's reference designator for a chip pin number.
- Tiny-contact tests can falsely read open from poor probe contact. The user initially reported infinity, then repeated the same tests and obtained zero. Use confirmed repeats, not the first false negatives.

## 6. User-confirmed motor checks

The motor was to be the unused extruder motor; see cable-identification caveat above. Four wires are present.

| Test | Reported result |
|---|---|
| Yellow-red pair | Approximately 3 ohms on R×1 |
| Blue-orange pair | Approximately 3 ohms on R×1 |
| Each wire to motor metal housing | User reported no shorts after instructions to check on R×1K |

Two separate coil pairs were identified. The exact full six-combination resistance table was not supplied. A multimeter short-to-case check is not a high-voltage insulation certification.

**Motor model, rated phase current, rated coil voltage, inductance, and steps/revolution were NOT read from its label.** Do not derive a safe rated current from 3-ohm winding resistance or apply 12 V directly across a coil.

For eventual wiring, put yellow/red together on one driver phase pair and blue/orange together on the other; for example, yellow/red -> 2B/2A and blue/orange -> 1B/1A is a possible assignment, not a completed physical wiring test. Swapping leads within a coil changes its polarity. Do not interleave the two pairs.

## 7. Driver passive tests and corrected readings

All were intended with the module removed, no electronics attached, and wall power/USB disconnected. Analog semiconductor paths make polarity matter.

| Test | Final reported observation |
|---|---|
| Meter probes together | Approximately 0 ohm after adjustment |
| T2-T8 | Approximately 0 ohm, consistent with common ground |
| T1 (+12 V) to ground | Around 23 ohms/midscale on R×1 with red on +12 V and black on ground; infinity with probes reversed |
| T7 (VDD) to T8 | Midscale on R×1 with red on VDD and black on ground; infinity or very little movement reversed |
| B7 to chip contact 16 | Approximately 0 ohm, confirmed on repeat |
| Orange pad to chip contact 17 | Approximately 0 ohm, confirmed on repeat |
| Orange pad to bottom header pads | No direct-zero connection reported on the sweep |

The original statement that VDD-ground read zero was explicitly corrected by the user. **There is no reported persistent, bidirectional zero-ohm VDD-ground short.** These tests do not certify that the driver is healthy. Direction-dependent readings suggest semiconductor conduction but do not conclusively identify which path or rule out all faults.

## 8. Current-setting circuit: what was actually traced

Definitions: the "near" end of R6/R7 means the end nearer the orange pad/right-edge REF trace in the component-side photo. "Far" means its opposite end. R6 is the upper small resistor of the R306/R307 pair; R7 is below it.

Confirmed by the user's approximately zero-ohm tests:

| Connection | Result |
|---|---|
| Orange pad to chip REF/contact 17 | Zero |
| Orange pad to near end of R6 | Zero |
| Orange pad to near end of R7 | Zero |
| Far end of R6 to VDD/T7 | Zero in BOTH probe directions |
| Far end of R7 to ground | Zero in BOTH probe directions |

This establishes the measured connection topology: **VDD -> R6 -> VREF/orange pad -> R7 -> ground.** Additional parallel circuitry may exist. No potentiometer is visible. Do not tell the user to turn an adjustment screw on this module.

### Resistor readings: NOT established component values

The final across-component readings were made on **R×100**, in order R7, R6, then reversed probes R7, R6:

| Component | First direction | Reversed |
|---|---:|---:|
| R7 | Scale 13 -> 1.3 kohm | Scale 11 -> 1.1 kohm |
| R6 | Scale 15 -> 1.5 kohm | Scale 19 -> 1.9 kohm |

Because these vary with polarity and were measured in circuit, **do not use them as actual R6/R7 values or calculate an authoritative divider ratio from them**. Earlier rough R×1 "halfway" readings are superseded for estimating these resistors. They are retained only as troubleshooting history, not precise component measurements. No resistor markings could be read in the macro photo. Searches did not produce a verified schematic/BOM for the exact module.

### Datasheet relationship, valid once VREF and sense resistance are established

For A4988: I_limit = VREF / (8 * R_sense).
The photographed R200 sense resistors give: **I_limit [A] = VREF [V] / 1.6**.

Examples only: 0.8 V -> 0.5 A; 1.0 V -> 0.625 A; 1.5 V -> 0.9375 A. None is an approved or physically validated motor setting. Full-step operation energizes both phases at about 70.7% of the peak trip limit; supply input current is not the same as phase current.

With the traced fixed divider, changing VDD changes VREF and therefore the current setting. Do not silently switch from 3.3 V logic to 5 V logic. Firmware speed changes or an ENA command do not by themselves change this analog current limit. Do not suggest reducing VDD below the chip's 3.0 V operating minimum as a way to start at low current.

## 9. Logic-only powered test and exact stopping point

Power source: USB-powered Uno; not the printer PSU. A wall charger/power bank can power the Uno without code. Only a phone was available at that point in the session, so no sketch upload was performed/reported.

Suggested test connections, made with USB unplugged:

| Source | Driver |
|---|---|
| Uno 3.3V | T7 / VDD |
| Uno GND | T8 / ground |
| Optional split of Uno 3.3V | B1 / ENA, to keep outputs disabled |

The user had only one 3.3 V pin and no established splitter. The assistant allowed leaving ENA disconnected for THIS logic-only voltage check, because both VMOT and motor were disconnected. **Do not carry that floating-ENA arrangement forward to powered motor operation.** Exact as-built breadboard/jumper routing was not photographed/verified.

Motor disconnected. T1/12 V disconnected. Printer PSU not connected to the driver. No STEP pulses needed for measuring the reference divider.

Readings and corrections:

- User first estimated VDD ~2.5 V and orange pad ~1 V.
- User subsequently measured unloaded Uno 3.3 V and corrected the earlier scale reading: a little over 3 V, consistent with ~3.3 V. The original 2.5 V report is not a confirmed supply fault.
- After reconnecting the driver, user supplied two meter photos: FIRST copper pad, SECOND VDD.
- The last assistant visually estimated VREF ~1-1.5 V and VDD ~3 V on DCV 15. **These are rough photograph estimates, not precise measurements and not proof of adequate margin above 3.0 V.**
- Outstanding instruction: keep motor/12 V disconnected, black probe on ground, measure ONLY the copper pad on **DCV 3** for better resolution and send a photo. Do not put VDD, which may exceed 3 V, on that range.
- No result from that final DCV 3 measurement was received before this handoff.

The analog meter loads its measured node. Its face specifies 20,000 ohms/volt DC (approximately 60 kohm input on DCV 3, 300 kohm on DCV 15). Since divider values are unknown, account for possible VREF loading error; do not overstate precision. A digital high-impedance meter, if available later, would help.

## 10. Meter use and communication lessons

- Instrument: Micronta 22-211 analog meter.
- For resistance: green OHMS scale, zero at RIGHT and infinity at LEFT, nonlinear scale. Multiply reading by R×1, R×10, R×100, or R×1K.
- Before each resistance range change: with no power on the device under test, touch probes together and zero using orange OHMS ADJUST wheel.
- For voltage: select DCV, use the appropriate BLACK DC scale; do not read green resistance or bottom dB scale. Do not use OHMS ADJUST for voltage measurements.
- State probe orientation when readings depend on polarity: "red on X, black on Y" and then reverse.
- Hold insulated probe handles; fingers across exposed conductors can affect high-resistance tests.
- For tiny contacts, distinguish a direct zero-ohm path from midscale conduction. A false infinity can be poor contact; do not scrape solder mask or push hard against IC contacts.
- For discussing a step, give at most a small batch of tests, exact visible landmark, selected range, and expected response.

## 11. Open work before any first motor run

1. Finish VREF measurement; verify stable VDD in the operating range with module attached. Establish a suitable starting current against the actual motor rating or a deliberately controlled bench limit.
2. Map B2-B6, including RESET/SLEEP and microstep configuration. Do not power or drive unknown control pins. Determine any onboard pullups/pulldowns rather than assuming bare-chip defaults are the whole circuit.
3. Verify controller output levels against the actual 3.3 V-powered A4988 input requirements/limits and power sequencing. Uno GPIO is nominally 5 V; do not assume a 3.3 V VDD guarantees compatibility with every interface. Check the datasheet and avoid back-powering through signals.
4. Identify the motor's model/rated phase current. 3-ohm resistance alone is insufficient.
5. Verify isolated PSU +12 V and DC ground, low-voltage connectors, and any enable behavior without exposing mains. Do not power through the damaged motherboard for the test.
6. Fit appropriate local motor-supply bulk capacitance/decoupling, rated wiring/connectors and accessible DC power cutoff. A4988 carrier guidance commonly calls for at least 47 uF electrolytic across VMOT-ground close to the module; establish polarity and voltage rating and assess this actual board. The small ceramics on the removed module are not proof of sufficient bulk protection.
7. No motor current through a cheap solderless breadboard; it can carry suitable low-current logic only. Never connect/disconnect a motor or driver while energized.
8. First test is a brief holding/slow-step test of the expendable extruder pair, mechanically clear of hazards, at conservative current/speed. Stop for abnormal heat, noise without motion, or wiring faults. Watch driver as well as motor temperature.
9. Verify ENA disable and physical power cutoff. A driver disable removes holding torque; do not let the eventual heavy bed drop unexpectedly.
10. Only then duplicate onto axes, calibrate steps/mm and direction, test endstops/homing and determine usable travel before plotting.

## 12. Concrete starting assignment for Claude Code

Prepare a small, separate **Uno bench-test firmware project**, not a full plotting rewrite. Read this file and current repository instructions first. Suggested location: `firmware/uno-bench/`; keep existing application behavior intact.

Desired behavior:

- Central pin configuration with proposed Uno pins clearly labeled: D2 STEP, D5 DIR, D8 ENA for the single bench motor; these are the conventional GRBL X signals, NOT proof that wires are connected. Confirm measured header endpoints and voltage compatibility separately.
- Do not flash automatically, assume computer access, or enable motion at boot. No automatic homing, arbitrary motion, or heater output.
- Drive ENA disabled by default and establish STEP/DIR states intentionally. Document hardware bias needed to keep outputs disabled during reset/boot before firmware takes control.
- Begin in a diagnostics/disarmed state. Make unresolved electrical setup explicit in configuration/documentation; firmware cannot establish an analog current limit by itself.
- A simple serial command interface for status, arm/enable, disable/stop, bounded slow jog by a small number of pulses, and direction. Names/protocol are implementation choices, not existing commands.
- Clamp pulse count and pulse rate; bounded runs only. Use a responsive nonblocking stepping loop so stop/disable can be processed during motion. Do not queue unlimited movement.
- Abort a bench run on its timeout and return to disabled. Specify what happens on reset and serial link loss; do not promise link-loss detection the hardware cannot provide.
- Default full-step bench mode only AFTER the corresponding module pins/pulls are confirmed. Do not silently assume GRBL/full-step/1/16 settings from a generic drawing.
- No firmware test should claim physical movement, successful current limiting, or electrical safety unless Caleb actually observes/reports it.
- Provide wiring by printed module labels and measured connections, with an explicit unresolved-pin list. Do not include guessed B2-B6 connections as facts.
- Include a concise upload guide for the actual Uno-compatible board/USB chip, serial monitor use, and a meaningful bench acceptance checklist. Compile-check when toolchains are available; report unavailable checks honestly.

Eventual GRBL 1.1 is still an option. Do not overwrite an existing GRBL installation without checking the current board state; none was confirmed during this conversation. A custom short bench sketch is only a first diagnostic milestone.

### Useful eventual GRBL mapping (proposal, not as-built wiring)

| Axis | STEP | DIR | Shared ENA |
|---|---|---|---|
| X | Uno D2 | D5 | D8 |
| Y | Uno D3 | D6 | D8 |
| Z | Uno D4 | D7 | D8 |

A4988 ENA is active low. GRBL limit mapping/revision details and physical endstop interfaces need checking. The printer's optical sensors have not been tested or adapted. Stock Z moves the whole bed: verify which sign creates actual pen clearance before sending any pen-lift G-code.

## 13. Existing software and planned system

Repository README was re-read when preparing this file on November 19. It describes:

- Python 3.10+ local app, `python app.py`, default URL `http://127.0.0.1:8765`.
- Standard-library SQLite/HTTP, browser stroke capture with pen lifts, timestamps and pressure where supported.
- Multiple handwriting variants for letters, connected sequences and words; optional contextual labels; SVG and offline GRBL-style G-code export.
- Photo import is a manual tracing reference, not automatic recovery of stroke order/pressure.
- Current prototype is heuristic, not a trained model. No printer communication or machine calibration is implemented according to the README.
- Existing docs: `docs/hardware.md`, `docs/zero-cost-build.md`, `docs/validation.md`; tests: `python -m unittest discover -s tests -v`.
- Host performs handwriting processing; Uno generates timed motor control. The Uno cannot process handwriting photos or replace the host composition engine.

Re-read current files before coding; do not assume the README describes every subsequently developed service/site. This handoff does not audit newer hosted handwriting-collection work.

Longer-term possibilities: USB Uno + driver modules first; ESP32 could later provide a properly designed UART/Wi-Fi bridge or a supported FluidNC-based controller. Neither ESP32 design is implemented/tested here. Uno serial and USB share D0/D1; account for contention and 5 V/3.3 V electrical interfaces if using a bridge. Stream G-code with flow control rather than dumping files into a buffer.

## 14. Proposed replacement base / paper bed plate

This is the agreed plate concept for the handwriting plotter. It is a paper-supporting bed plate, not an electronics mounting plate. It remains a proposed design, not a verified fit or an installed part.

### Agreed geometry

| Feature | Proposed dimension / requirement | Status |
|---|---|---|
| Overall width | **220 mm** | Selected in conversation |
| Overall length | **285 mm** | Selected in conversation |
| Thickness | **10 mm (1 cm)** | User requested; supersedes initial 5 mm idea |
| Material | **Plastic** | User selected; resin/polymer, print method and infill not chosen |
| Paper format | US Letter: **215.9 x 279.4 mm (8.5 x 11 in)** | Target sheet size |
| Centered paper margin | **2.05 mm on each side; 2.8 mm at each end** | Derived from the dimensions above |
| Top | Flat, continuous paper-support surface; fastener heads at or below it | Intended behavior |
| Initial mounting holes | **None** | User will position blank and mark locations physically |
| Initial screw recesses | **None in the delivered blank STL** | Added only after marking/measuring fasteners |
| Later screw-head recess | Cylindrical top counterbore, **5 mm deep**, provisional **5.5 mm diameter** | Unverified starting geometry |
| Remaining material below counterbore | **5 mm**, except for the shaft through-hole | Derived from 10 mm thickness minus 5 mm recess |
| Shaft through-hole | Diameter to be measured and set | Unresolved; do not guess |
| Underside mating recesses | Not included | Existing standoff/spring geometry unresolved |

The user's screw-head estimate was roughly **5 mm deep and 5 mm across**. A 5.5 mm counterbore diameter was proposed to provide 0.5 mm total diametral clearance around a genuinely 5 mm-wide head; it is not a measured fastener specification. Do not assume the recess works with the existing screw length or leveling hardware. Confirm that the finished head seats below the paper without tightening through or crushing the plastic.

A rectangular blank was generated, without modeled corner radii, retention clips, ribs, paper grooves, wall-clearance cutouts, countersinks or fastener pockets. These features were not requested/verified. The 10 mm thickness was chosen to provide recess depth, not from a stiffness calculation. A full-solid geometric model occupies **627 cm^3**; actual printed material and mass depend on material and slicer settings. Check that a one-piece 220 x 285 mm footprint fits the fabrication equipment.

### Positioning and mounting plan

1. Make a **220 x 285 mm cardboard outline** and position it over the intended supports in the unpowered machine. Account separately for the full **10 mm thickness**; a thin cardboard sheet alone does not validate vertical clearance.
2. Choose its placement/orientation around the existing mechanism. The final plate origin relative to the frame is NOT established. Check the original support's suitability rather than assuming the plate can simply be enlarged in every direction.
3. Check frame, rods, bed mechanism, cable, carriage and pen-holder clearance over the full intended travel. Determine whether leveling adjustment and access to fasteners remain possible.
4. Position the actual blank and **transfer the three mounting centers directly from the machine**. This supersedes the initial idea of deriving precision hole coordinates from ruler photographs.
5. Measure shaft diameter, head diameter/height, available screw length, supports and any spring/standoff stack. Add through-holes and top counterbores only after these are established.
6. Fit/level the plate and verify all screw heads sit flush or below the paper. Check the surface stays flat and paper can be held without protruding clips colliding with the pen/carriage. A paper retention method has not been selected.
7. Re-establish usable pen Z heights and travel limits for the changed stack. The plate is for unheated pen use; bed/extruder heaters should remain disconnected.

A larger paper-support surface does **not** increase the existing X/Y pen reach. Supporting the full sheet and writing on the full sheet are separate requirements. Actual reachable writing area, margins, scale, steps/mm, limits and homing must be measured before a whole-page plot.

### Three-point support evidence and limitations

- Three mounting points were photographed with a ruler: one left point and two right points, in the orientation of those photos.
- Early approximate interpretation: **~180 mm** between the two right points and **~190 mm** from the left point to either right point. Camera angle, ruler offset and perspective make these unsuitable as final CAD hole coordinates.
- User described a raised feature at each mounting point about **3.5 mm tall**, with a through-hole. The side photo appears to show spring/screw leveling hardware above a ribbed support.
- Whether the intended installation replaces only the flat black sheet and retains the ribbed support was asked but not explicitly resolved. Preserve/reuse of that support is a possibility, not a confirmed assembly decision.
- Do not combine a presumed 3.5 mm raised feature, the new 10 mm plate and a 5 mm recess into a final mounting stack without measuring which components sit above/below each other.
- No final outline clearance, installed stiffness, flatness, mounting hole spacing, screw length, material suitability or printable settings were physically validated.

### Existing CAD package and editable parameters

Previously created package: **DaVinci_Plate_220x285x10mm.zip**.

[Retrieve the plate package](https://chatgpt.com/library?file_id=libfile_2b692be3dd9c8191b087d192f11949d1&account_id=personal).

It contains:

| Filename | Contents |
|---|---|
| `DaVinci_Plate_220x285x10mm_Blank.stl` | Closed rectangular solid, 220 x 285 x 10 mm, no holes/recesses |
| `DaVinci_Plate_Editable.scad` | Parametric OpenSCAD source, initially producing the same blank |
| `Plate_Fit_Check_1to1.svg` | Full-size plate outline, centered Letter-paper footprint and 100 mm calibration bar |
| `README.txt` | Dimensions, fit-check procedure and unresolved mounting details |

Editable source settings as originally generated:

```scad
plate_width = 220;
plate_depth = 285;
plate_thickness = 10;
mounts = [];                  // measured [x,y] pairs go here later
shaft_clearance_diameter = 0; // intentionally unset; measure first
head_recess_diameter = 5.5;   // provisional
head_recess_depth = 5;        // provisional
```

Model coordinates: lower-left XY corner is (0,0), bottom is Z=0, top is Z=10. Recesses are cut from the top. This is only the CAD convention; it does not establish the printer's machine-coordinate origin or which edge faces the front. Centered paper occupies X=2.05..217.95 mm and Y=2.8..282.2 mm. The STL format has no unit metadata: import as millimeters and verify dimensions.

The generated SCAD requires a positive shaft clearance diameter before mount positions can be used and checks that counterbores stay inside the outline and leave material beneath. Those geometry checks are not mechanical validation. Retrieve/read the actual source before changing it; do not assume the package is present inside a Claude checkout.

### Notes for Claude Code when working on the plate

- Preserve the **220 x 285 x 10 mm plastic blank** as the current requested concept unless Caleb changes it.
- Keep mount locations empty until supplied/measured; do not infer coordinates from the approximate triangle above.
- Use the existing editable source if continuing CAD work. Do not label a file “ready to print/cut/install” until clearance and hardware fit are checked.
- Allow actual measured hole locations, recess dimensions, material and mounting stack to be entered without rewriting the whole model.
- Do not assume the driver/Arduino bench firmware needs a full Letter-sized movement envelope just because the plate can support Letter paper.

## 15. Primary references and evidence files

### Technical references read during the investigation

- Allegro A4988 datasheet (chip limits, contact map p.18, reference-current equation): https://www.allegromicro.com/-/media/files/datasheets/a4988-datasheet.pdf
- Pololu carrier documentation (reference formula, phase-vs-supply current, bulk-capacitor/spike warning). This is a DIFFERENT carrier: https://www.pololu.com/product/1182
- GRBL source/conventional Uno mapping: https://github.com/gnea/grbl/blob/master/grbl/cpu_map.h
- Firsthand Da Vinci conversion / annotated motherboard: https://www.techmonkeybusiness.com/articles/Frankenvinci.html
- Firsthand original-module width/adaptation experience; not a verified exact-module schematic: https://techie-s.work/posts/2022/10/hack-on-xyzprinting-davinci-10/
- Original meter manual: https://www.manualslib.com/manual/3288388/Micronta-22-211.html
- MCU/mainboard pinout research (not a module header schematic): https://github.com/luc-github/Repetier-Firmware-4-Davinci/blob/master/pinout.xlsx

At the time of the session, Safari/iPhone did not expose Web Serial for direct browser Uno uploading. A USB adapter may supply power but does not create browser serial support. No phone-upload solution was tested. Do not make phone compatibility a blocker for preparing firmware files; ask for/describe a supported upload environment when actually uploading.

### Most useful user photos / generated diagrams

These are evidence references, not files guaranteed to exist inside a Claude checkout. Obtain copies from Caleb if needed. Do not invent relative image paths.

| Filename | Contents | Retrieval identity |
|---|---|---|
| IMG_3514.jpeg | Clearest component-side module, labels, R200 resistors | libfile_ba77822c470c8191ac1eea94780a6782 |
| IMG_1A6A893D-9B2A-4286-9C2A-912E41F822A1.jpeg | Underside after sticker removal | libfile_0d168713e8ac819190321219446f4072 |
| IMG_3515.jpeg | R306/R307 macro; no legible resistance markings | libfile_54839bcf7bec8191b285a428f6fc30a4 |
| IMG_4320158D-ACFA-455C-87D0-2E445BD5F6A1.jpeg | PSU nameplate | libfile_bdb15ceb974081918cc2eaac38522db1 |
| IMG_0127BB05-8552-425D-9CAA-77D9C36D20BA.jpeg | Four populated drivers on motherboard | libfile_22aa3ee941088191818843f9fb7ef3ff |
| IMG_3EA5840C-F849-4EC3-8890-61B829DC89E9.jpeg | Whole motherboard and PSU | libfile_3b5d244ea96481918788d10b29b5f33c |
| DaVinci_Unpowered_Test_Diagram.png | Early passive-test guide; control mapping was incomplete | libfile_e76cf003a2b881918be344c6dcb58c5e |
| DaVinci_STEP_VREF_Probe_Locations.png | A-B STEP and C-D VREF continuity landmarks; user subsequently confirmed both zero | libfile_d5047f28f0f88191b952b7183444bf59 |

Two final DCV-15 meter attachments were IMG_8E06E72D-6731-440F-A4A3-A1A86F5A0866.jpeg (`libfile_3c2437b1edc08191920eda1e73e84dde`) and IMG_50DDC9C1-9008-424B-B3DE-B3D75A227633.jpeg (`libfile_3084f42aac98819189aff3527e6859d3`). The user identified displayed order as first copper pad, second VDD. Do not infer which node from filename sorting; re-establish image association if re-reading these. Numerical estimates remain provisional.

## 16. Resume checklist

- [ ] Confirm the current physical wiring and power state; this file cannot know whether Caleb has disconnected the bench since the last test.
- [ ] Obtain the pending copper-pad measurement on DCV 3 and confirm loaded VDD.
- [ ] Identify all remaining control pins and onboard pulls.
- [ ] Establish allowable motor current and a measured/configurable starting limit.
- [ ] Prepare/compile a disarmed-by-default Uno bench sketch and clear wiring notes.
- [ ] Verify PSU, decoupling, connections, cutoff and controller signal compatibility before motor power.
- [ ] Observe first holding test, slow bounded steps, direction reversal and disable behavior.
- [ ] Fit-check the proposed 220 x 285 x 10 mm paper bed; transfer mounting centers and measure recess/shaft hardware before adding holes.
- [ ] Record actual outcomes here rather than promoting proposals into facts.

