# Budget-first build: $0 before buying anything

**Budget target:** $0 for the first working software demo, and $0 additional cost for motor control *only if* existing drivers, PSU, wire, hardware, protection capacitors, and test equipment are available and verified. This is a conditional target, not a guarantee.

## Salvage inventory first

1. Elegoo Uno (already owned): runs GRBL 1.1; USB connection first.
2. Da Vinci original **X, Y and Z motors**, bed, gantry, belts, guide rods and PSU (already owned).
3. Original Da Vinci 1.0 controller: several original models include **plug-in A4988 stepper-driver modules**. Unplug the machine and photograph both sides of each module, including pin labels and sense resistors. **Do not assume the fried controller left the drivers undamaged.**
4. Reuse a solderless breadboard only for *low-current 5V logic tests*. Do **not** carry stepper-motor current through a cheap breadboard; use secure rated connectors or proper soldered terminals.
5. Check your spare parts for jumper wire, compatible connector terminals, electrolytic capacitors, accessible DC power disconnect, and a multimeter. The capacitor requirement cannot be skipped merely to hit $0.

## Cheapest legitimate wiring idea (with separately proven driver boards)

```
PC USB -> Uno with GRBL 1.1
                 ├─ D2 STEP, D5 DIR -> driver X
                 ├─ D3 STEP, D6 DIR -> driver Y
                 ├─ D4 STEP, D7 DIR -> driver Z
                 └─ D8 ENABLE -> drivers (if active low on measured carrier)
                            │
Da Vinci PSU verified +12V/GND -> each driver's motor supply, rated wiring, supply decoupling
                            │
driver outputs, verified coil pairs -> original X/Y/Z motors
```

**Important:** This is logical signal routing, not an exact pin-by-pin harness schematic. All driver logic connections (VDD, GND, STEP, DIR, ENABLE, RST, SLP, microstep mode), motor supply, coil outputs and decoupling need to be identified from the actual salvaged module. A4988 carriers are **not interchangeable by physical shape alone**; at least one documented Da Vinci modification notes an unusual driver-header spacing compared with standard modules. Never infer the mapping from the potentiometer's location.

- Typical bare Pololu A4988 requires an **8–35 V motor supply**, **3–5.5 V logic**, a **minimum 47 µF electrolytic capacitor near VMOT/GND** to protect from motor-supply spikes, and appropriately set current limit; the exact carrier could differ. https://www.pololu.com/product/1182
- Original Da Vinci 1.0 teardown shows modular A4988 drivers and original bipolar motors. https://www.tweaktown.com/reviews/6827/xyzprinting-da-vinci-1-0-3d-printer-review/index.html
- Original module-width caveat: https://techie-s.work/posts/2022/10/hack-on-xyzprinting-davinci-10/

## Free milestones

### Stage 1: $0 software

- Run `python app.py` and train your handwriting library with a touchscreen, mouse, or stylus.
- Store multiple variations of connected letter pairs and words, compose a page, and inspect/download SVG and review-only G-code.
- Run `python -m unittest discover -s tests -v`.
- This is possible without any physical printer electronics being powered.

### Stage 2: $0 electrical identification

- Completely remove mains power; photo-document the damaged controller, removable driver boards, PSU DC outputs, and motors.
- Measure motor coil pairs with a multimeter, inspect the harness and verify there are no shorts to chassis.
- Check PSU DC output **only if qualified to safely measure exposed low-voltage outputs without exposing or touching mains**.
- Identify driver model, pinout, current-sense resistor, motor current rating, capacitors, logic interface, and safe current limit.
- If any essential part or safe test tool is missing, pause rather than improvising a dangerous powered test.

### Stage 3: $0 first motor movement (conditional)

- Bypass the fried controller entirely, using verified intact driver board(s) with correct wiring and protection.
- Uno on USB, one driver/motor at a time, current limited, conservative speeds, and separate motor supply from the 12V rail.
- Verify STEP/DIR/ENABLE operation and reverse direction away from end stops; keep an immediately accessible way to disconnect motor power.
- Implement homing/limit switches and calibrate axes before connecting a pen.

### Stage 4: $0 mechanical prototype (conditional)

- A cheap pen clamped to a springy scrap mount.
- Original Z bed lifts/lowers for pen up/down, so **no servo purchase is necessary**.
- Start with small paper and one 10mm square; keep Z modulation disabled until proven.

## Optional ESP32, without buying anything

You already have an ESP32, but don't complicate early motor tests. It can later become a Wi-Fi sender to Uno via UART (5V Uno TX to 3.3V ESP32 RX **requires level shifting**) or **replace** Uno with FluidNC if the exact board and firmware/config are compatible. In either case a stepper driver remains mandatory. For a zero-cost first plot, use USB to Uno.

## Stop conditions: what could force a purchase?

- Damaged/missing driver modules => properly matched replacement stepper drivers, possibly a shield for ease.
- No safe motor supply connector, bulk capacitors or proper driver cooling => must obtain before applying power.
- No reliable limit-switch circuit => need to adapt/rebuild before unattended plotting/homing.
- No multimeter => borrow one; don't skip coil identification.
- No tested safe power cutoff => add one or use an accessible existing properly rated DC disconnect.

**Do not try** connecting a stepper to Uno GPIO, feeding 12V to Uno 5V/ESP32 pins, or driving motors via relay contacts. Driver protection is not optional for a free build.
