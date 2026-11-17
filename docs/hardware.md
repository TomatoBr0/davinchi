# Hardware plan: Da Vinci 1.0 + Elegoo Uno (with optional ESP32)

**Status:** research and integration guide, **not an electrically verified wire-by-wire schematic** for your exact machine. The original motherboard is damaged; verify the PSU, cables, motors and driver specifications independently before powering anything.

## How the motors are actually powered

The stepper motors are typically four-wire bipolar motors. They cannot be driven from Arduino I/O pins, TX/RX, a relay, or the low-current 5V/3.3V logic rails.

An **A4988 or suitable stepper driver** receives:
- **VMOT**: motor-power supply, normally the original **verified 12V DC** rail, routed to the CNC shield motor input.
- **Logic power**: provided by the controller/shield at a safe level for the driver.
- **STEP / DIR / ENABLE**: digital pulses from the Uno (the pulses determine movement, while the driver controls coil currents).
- **Coil A + coil B**: four wires from each existing motor, to the driver's A1/A2 and B1/B2 outputs.

The driver regulates the motor *coil current*. The fact the PSU supplies 12V does not mean that 12V can be placed directly across a motor coil. The driver must be appropriately current-limited.

**No relay is required to make the motors rotate.** A relay could switch separate power circuits, but cannot replace a stepper driver. Standard Grbl speaks G-code over serial/USB and then produces STEP/DIR pulses, rather than addressing motors through the old board's TX/RX.

\`\`\`text
Original PSU verified DC +12V and DC GND
           │
           ▼
    CNC Shield V3 MOTOR SUPPLY
       ├─ A4988 (X) ── coil pair A/B ── X motor
       ├─ A4988 (Y) ── coil pair A/B ── Y motor
       └─ A4988 (Z) ── coil pair A/B ── Z bed motor
                ▲
         Elegoo UNO + Grbl 1.1
                ▲
          PC USB serial
                │
    Handwriting Lab (renders G-code OFFLINE)
\`\`\`

The Uno receives power from USB initially. Do **not** feed 12V to a 5V pin, or connect a 3.3V rail to a stepper coil. Keep AC mains terminals inside the intact PSU enclosure. Unused heater leads must be isolated and disconnected.

## Which original PSU rails matter?

A documented original Da Vinci retrofit (“FrankenVinci”) used **two yellow 12V wires and two black ground wires** for its new RAMPS controller. A similar 1.0A machine reportedly exposes 12V, 5V and 3.3V rails. You remembered roughly 12V, 5.5V and 3.3V; **do not infer that 5.5V rail exists or that the colors are universal**. Confirm from the original PSU label / pinout and a DC multimeter measurement of the **low-voltage output** before reuse.

The exact PSU *capacity* matters: measure or read its rated current for the 12V rail, confirm polarity and signs of damage. Never open the power-supply casing or probe AC mains. If the PSU or connections look damaged, stop.

- https://www.techmonkeybusiness.com/articles/Frankenvinci.html
- https://eositis.wordpress.com/2021/11/14/da-vinci-1-0a-upgrade-to-mks-and-marlin/

## Arduino Uno / CNC Shield V3 signal map (common Grbl 1.1)

| Axis | STEP | DIR | ENABLE (shared) |
|---|---|---|---|
| X | D2 | D5 | D8 |
| Y | D3 | D6 | D8 |
| Z | D4 | D7 | D8 |

Usual Grbl 1.1 **limit inputs:** X D9, Y D10, Z **D12** when variable spindle enabled. CNC Shield V3 silkscreen may predate Grbl 1.1 and call D11 “Z limit”; **verify revision and labels before wiring**. Stock optical endstops are not necessarily direct-compatible with the shield; if unsure, install properly tested normally-open mechanical limit switches and confirm with Grbl status messages before enabling homing/limits.

- https://github.com/gnea/grbl/blob/master/grbl/cpu_map.h
- https://github.com/gnea/grbl

## Identify motor coil pairs instead of trusting colors

The FrankenVinci builder recorded this particular Da Vinci 1.0 motor-wire mapping:

| Their motor color | Their driver output |
|---|---|
| Orange | 1A |
| Blue | 1B |
| Red | 2A |
| Yellow | 2B |

**This is a starting reference, not your verified wiring.** With every circuit disconnected and unpowered:
1. Identify the cable to each axis motor.
2. Test resistance between wire pairs. The two leads of a coil show small, finite resistance; different-coil pairs are open.
3. Mark each pair A and B. Keep the pair together on the matching two driver outputs.
4. Check for shorts between coils and chassis.
5. Use compatible connectors or properly adapted wires. The stock Da Vinci connectors may be mechanically different from shield sockets.

Do not hot-plug stepper motors or drivers.

## Set driver current BEFORE first movement

Current-limit calibration depends on each stepper model's rated current, the A4988 variant's sense resistor and cooling. Pololu documents:

\`\`\`text
I_limit = Vref / (8 * R_sense)
Vref = I_limit * 8 * R_sense
\`\`\`

Examples of values are **not** substitute for identifying your specific motor/driver. Some A4988 clones have different sense-resistor values. Always power down before changing motor wiring; verify driver orientation by **pins/silkscreen**, never potentiometer position alone. Use suitable heatsinking and airflow.

- https://www.pololu.com/product/1182
- https://www.pololu.com/product/2128

## Optional ESP32: two legitimate designs

### Option A: Uno runs Grbl, ESP32 is a network bridge

\`\`\`text
Phone / touchscreen app ~ Wi-Fi ~ ESP32
                                 │ UART serial, GND
                       proper 5V-to-3.3V level shift
                                 │
                        Uno (Grbl) ─ CNC shield ─ drivers ─ motors
\`\`\`

- ESP32 outputs and inputs are typically **3.3V**; Uno serial TX is 5V. **Never directly connect Uno TX to ESP32 RX** without suitable level shifting, and share the logic grounds.
- Serial **TX crosses to RX** and vice versa. Uno **D0/RX and D1/TX are also shared with USB-serial**, so an always-connected bridge can interfere with USB flashing/console. Plan a switch, appropriate UART interface, or disconnect bridge for USB access.
- ESP32 cannot simply relay a whole G-code file into Grbl at full speed. The sender must obey Grbl's **ok/error** responses, RX buffer size and machine status; it also needs a usable emergency stop/disconnect recovery strategy.
- Build/verify motion **over USB first**. Wireless motion is a later, independently tested feature.

Espressif 3.3V UART reference: https://docs.espressif.com/projects/esptool/en/latest/esp32/esptool/serial-connection.html

### Option B: ESP32 directly runs FluidNC, no Uno

FluidNC is Wi-Fi-capable ESP32 motion-control firmware with a web UI and GRBL-style G-code compatibility. It can generate STEP/DIR for compatible external drivers directly and eliminates the two-controller serial bridge. It still **requires stepper driver hardware** and verified signal voltage, pin selection, homing inputs and a board-specific YAML machine configuration.

This may be the better *final* design if your ESP32 is supported, but an ordinary Arduino Uno CNC Shield V3 is **not a plug-and-play shield for ESP32 GPIO**.

- https://github.com/bdring/FluidNC

## First-power bring-up procedure

1. Keep the printer fully unplugged. Photograph labels on PSU outputs, all motors, remaining driver modules and limit sensors.
2. Check all motor pairs for continuity and motor-to-chassis shorts. Inspect harnesses for melted insulation.
3. Inspect the supply rating, connector polarity and voltage before any connection to new electronics. Leave mains isolated.
4. Use **one motor at a time**, current-limited driver with its orientation/jumpers verified, conservative speed/acceleration, and no pen attached. Keep an accessible way to disconnect DC motor power.
5. Confirm Grbl responds to USB, then make tiny low-speed jogs with sufficient free travel. Stop if buzzing, abnormal heat or bad movement.
6. Calibrate X/Y/Z directions, steps/mm, max travel, limit inputs and homing. Check negative/positive Z **relative to actual bed/pen motion** before exporting a pen-lift command.
7. Fit a **spring-loaded/compliant pen holder**. Test with paper/cardboard and small strokes before generating any complete page.

Grbl parameters to validate include \`$100-102\` steps/mm, \`$110-112\` maximum rates, \`$120-122\` acceleration and \`$130-132\` travel. Never guess axis calibrations from a printer's advertised build size.

## Height variation: a reality check

The stock Z motor moves the **entire bed**, not a lightweight pen. Constant movement in Z to imitate human pressure may be too slow or cause inconsistent contact. The app defaults to **zero Z variation** and exports only preview-only tool paths. Experiment with a compliant pen mount and small bounded variation after measuring which Z direction actually increases pressure. Arbitrary real pressure from a photo is not possible.

## Information to record before producing an exact harness diagram

- Printer label model and revision (Da Vinci 1.0 vs 1.0A).
- PSU nameplate and DC connector photos (pins/colors clearly visible, but do not probe mains).
- Each motor's printed model / current rating and 4-wire colors/pairs.
- Original driver boards if removable.
- Exact Elegoo Uno and ESP32 module labels.
- Whether optical endstops still work, and existing bed travel range.
