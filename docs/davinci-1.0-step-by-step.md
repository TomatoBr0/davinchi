# Da Vinci 1.0 → handwriting plotter: step by step

Specific to the original **XYZprinting Da Vinci 1.0** (single extruder, heated bed, Z moves the bed) with a dead mainboard, an Elegoo Uno and GRBL 1.1. Community sources are linked at the end; treat wire colours as *one builder's harness*, not a guarantee for yours.

## Reuse / test / discard at a glance

| Part | Verdict | How to test (power OFF unless stated) |
|---|---|---|
| Frame, X/Y gantry, rods, belts, pulleys | **Reuse** | Push each axis by hand: smooth, no binding, belts tight |
| X, Y, Z stepper motors | **Reuse** | Multimeter: find two coil pairs (a few Ω each, open between pairs); spin by hand, then short one pair and feel it get stiffer |
| Z leadscrew + bed carriage | **Reuse** as pen up/down | Bed moves freely by hand down the screw |
| PSU (internal, 12V) | **Probably reuse** | Unpowered: inspect for burn marks/bulged caps. Powered (only if you're comfortable, never open its case): measure the yellow/black output plug DC with a multimeter |
| A4988 driver modules on old board | **Maybe reuse** | Look for burn marks, cracked chips. Only proof is a one-motor powered test (Step 6) |
| Optical endstops | **Don't reuse first** | Builders report they're not compatible with RAMPS-style boards and can be damaged; mechanical switches are cheap and simpler |
| Extruder, hot end, heater, thermistors | **Remove/disconnect** | Not needed. Insulate the heater leads; never leave them connected to anything |
| Bed heater | **Disconnect** | Insulate leads. The bed stays as a flat writing surface |
| LCD, LED strip, cartridge chip reader, bed-level contacts | **Remove** | Not needed |
| Original mainboard | **Discard** (keep for driver salvage) | — |
| Extruder fan | **Optional reuse** | 12V fan can cool the drivers |

## Steps

### 1. Document before you unplug anything
- Pull the side panels (they unclip from the top). Photograph every connector on the mainboard, both sides of the board, and each driver module's pin labels.
- Put masking-tape labels on each harness: X motor, Y motor, Z motor, X/Y/Z endstop, PSU, heaters, fan, LCD.

### 2. Strip it down to a motion machine
- Remove the mainboard. Disconnect and insulate the extruder heater, bed heater and thermistors. Remove the LCD/LED/cartridge wiring.
- The extruder carriage stays as the **pen carrier**; you can take the hot end off to save weight.

### 3. Test the motors (free, multimeter only)
- For each motor's 4 wires, find the two pairs with continuity (a few ohms). Write them down as coil A and coil B.
- One reported Da Vinci 1.0 mapping: orange→1A, blue→1B, red→2A, yellow→2B. **Confirm yours**; a swapped pair only reverses direction, but splitting a pair means the motor won't turn properly.

### 4. Check the PSU
- Find the 12V output (FrankenVinci used **two yellow (+12V) and two black (GND)** wires). Confirm with a meter that it reads ~12V DC and note the rated current on the label.
- Never connect 12V to the Uno's 5V/GND header or to any Uno pin.

### 5. Identify the drivers
- If the modules plug in, unplug them and identify the chip (A4988 expected), pin order (VMOT, GND, 2B, 2A, 1A, 1B, VDD, GND / EN, MS1-3, RST, SLP, STEP, DIR) and sense resistor value. Their header spacing may not match a standard CNC shield.
- If any is burnt or soldered to a dead board, this is the most likely purchase: a CNC Shield V3 + A4988/DRV8825 set is a few dollars.

### 6. Flash GRBL and do a one-motor test
- Flash GRBL 1.1 to the Uno from the Arduino IDE (gnea/grbl). Open a serial terminal at 115200; you should see the `Grbl 1.1` banner. Type `$$` to list settings.
- Wire ONE driver: Uno D2→STEP, D5→DIR, D8→EN, Uno 5V/GND→driver logic, PSU 12V/GND→VMOT with a ≥47 µF capacitor across it, motor coils to the outputs.
- Set the current limit low first (A4988: Vref ≈ current × 8 × sense resistor). Send `$X` then `G91 G0 X5`. The motor should turn smoothly and stay cool. Repeat for Y (D3/D6) and Z (D4/D7).

### 7. Endstops
- Fit mechanical switches near the original optical sensor spots. In FrankenVinci, X and Y sat at the **max** end and Z at **min**; in GRBL set `$23` (homing direction invert mask) to match.
- Wire to D9 (X), D10 (Y), D12 (Z on GRBL 1.1). Check with `?` that each switch toggles the `Pn:` state before enabling `$22=1` homing.

### 8. Calibrate
- Steps/mm: command `G91 G1 X50 F600`, measure the real distance, set `$100 = old × 50 / measured`. Same for Y (`$101`) and Z (`$102`).
- Set max travel `$130-132`, max rates `$110-112`, acceleration `$120-122`. Enable soft limits `$20=1` after homing works.
- Check which way +Y and +Z go. This app's page has Y pointing down and the pen *up* at higher Z; flip in GRBL (`$3` direction invert) or in the exporter.

### 9. Pen mount
- Clamp a pen to the carriage with a spring so it floats. Pen-down is the bed raised to just touching; pen-up is the bed 2mm lower. The heavy bed is slow, so lower `z_feed` in the app and accept the speed for now. A servo pen lift is the first upgrade worth buying.

### 10. First plots
- Tape paper to the bed. Run a 10mm square, then a circle, then a single word from the app. Watch the first runs with a hand on the power switch.

## What you can test today without powering anything
1. Motor coil pairs (Step 3).
2. Mechanical smoothness of all three axes.
3. Driver modules: visual inspection and chip ID.
4. The software: `python app.py` and record samples.
5. GRBL on the Uno over USB alone (Step 6 banner and `$$`, no motors attached).

## Sources
- FrankenVinci (Da Vinci 1.0 → RAMPS): https://www.techmonkeybusiness.com/articles/Frankenvinci.html
- SoliForum Da Vinci 1.0a → RAMPS 1.4: https://www.soliforum.com/topic/18568/davinci-10a-conversion-to-ramps-14-with-pics-and-firmware/
- SoliForum, replacing the 1.0a logic board: https://www.soliforum.com/topic/12079/how-to-replace-the-da-vinci-10a-logic-board-with-ramps/
- GRBL 1.1: https://github.com/gnea/grbl
- Pololu A4988: https://www.pololu.com/product/1182
