# Da Vinci: three-driver plan and one-motor bench test

Status: proposed harness, not physically tested. Use the spare extruder motor OFF the printer mechanism. Leave the damaged motherboard disconnected from drivers, motor power and controller. Arduino is an Elegoo Uno (5 V GPIO); the salvaged module is 3DP01 MOTOR R2 / 3DP01-E0015 with an Allegro A4988ET. It has a fixed current-reference divider, NOT a current-adjustment trimmer.

## Upload in Arduino IDE

1. Download this folder (or the repository ZIP). Keep `DaVinci_One_Motor_Test.ino` inside the folder named `DaVinci_One_Motor_Test`.
2. Open the `.ino`, select **Tools > Board > Arduino AVR Boards > Arduino Uno**, and select the USB port. Install Arduino AVR Boards through Boards Manager if needed.
3. Keep motor 12V disconnected while uploading. Click Upload.
4. Open Serial Monitor at **115200 baud**. Expect `Outputs disabled`. Do not send `s` until the wiring and VREF checks below pass.

## What connects to what

USB powers the Uno. The Uno's 3.3 V pin powers driver VDD. A separately verified PSU +12 V output powers driver 12V/VMOT. PSU DC return, Uno GND, and driver grounds join. The motor connects ONLY to the driver's four coil outputs. No PSU rail connects to Uno VIN, 5V or 3.3V in this test. Never parallel the PSU's 3.3 V rail with the Uno's 3.3 V output.

The PSU nameplate says AcBel FLXA5201A, +12 V 15 A; the DC connector positions and polarity have NOT been established. No wire color is an adequate substitute for measurement. Check low-voltage output +12 V versus its DC return using DCV 15/60 range, not resistance. Keep mains enclosed. Retain original chassis protective earth; chassis metal is not our assumed signal-ground reference.

Add a 100 uF electrolytic capacitor rated at least 25 V directly across driver VMOT and GND: capacitor + to VMOT, striped negative lead to GND. Use short motor-power leads and secure insulated connections; do not route motor current through a solderless breadboard or Uno. Use a suitable DC fuse near the PSU output (1 A is a reasonable initial single-motor bench fuse; this protects the wiring, not a guarantee against semiconductor damage). Add a 10k resistor from ENA to driver 3.3 V so reset leaves outputs disabled. Existing module ceramic decoupling must remain intact.

## Physical header reference

FRONT / COMPONENT SIDE. Writing upright: printed 12V upper-left, ENA lower-left, DIR lower-right. These T/B labels are local position names, not Allegro chip numbers. Underside views mirror the order.

| Top position, left to right | Board marking / function | Single-motor connection |
|---|---|---|
| T1 | 12V / VMOT | Verified PSU +12 V, through fuse |
| T2 | Unprinted GND | PSU DC return; capacitor negative |
| T3 | 2B | Yellow motor lead |
| T4 | 2A | Red motor lead |
| T5 | 1A | Blue motor lead |
| T6 | 1B | Orange motor lead |
| T7 | VDD | Uno 3.3 V |
| T8 | Unprinted GND | Uno GND; common with PSU DC return |

Yellow-red is one user-measured coil; blue-orange is the other, each about 3 ohms. Choosing which end of a coil is A/B changes direction; the assignment above is a valid initial choice, not a claim about original factory polarity. These colors apply to the tested spare motor only.

| Bottom position, left to right | Function | Connection AFTER verification |
|---|---|---|
| B1 | Printed ENA | Uno D8; 10k pull-up to 3.3 V |
| B2 | MS1 candidate; NOT verified | GND for full step |
| B3 | MS2 candidate; NOT verified | GND for full step |
| B4 | MS3 candidate; NOT verified | GND for full step |
| B5 | RESET candidate; NOT verified | 3.3 V |
| B6 | SLEEP candidate; NOT verified | 3.3 V |
| B7 | STEP, continuity confirmed to chip contact 16 | Uno D2 |
| B8 | Printed DIR | Uno D5 |

Do NOT connect B2-B6 by guess. The generic StepStick sequence is a candidate, not proof of this carrier's wiring. With ALL power removed (USB and PSU disconnected), use RX1, zero the meter with probes together, and confirm near-zero resistance in BOTH probe orientations between each candidate and its corresponding chip contact. Avoid slipping across adjacent chip contacts. If access is poor, stop and identify accessible component pads instead; do not attempt probing a live chip.

Chip contact references in this FRONT view:
- Bottom edge has seven contacts, left to right: 8 VREG, 9 MS1, 10 MS2, 11 MS3, 12 RESET, 13 ROSC, 14 SLEEP.
- Therefore MS1 is second from left, MS2 third, MS3 fourth, RESET third from RIGHT (counting 14 as first), SLEEP the rightmost bottom contact beside printed 14.
- Right edge bottom-to-top: 15 VDD, 16 STEP, 17 REF, 18 GND, 19 DIR, 20 NC, 21 OUT1B.
- Confirm B1 -> IC ENABLE contact 2 and B8 -> IC DIR contact 19 if their paths have not yet been traced. IC contact 2 is second from the TOP on the left edge, whose contacts run 1..7 top-to-bottom.
- Before grounding verified MS pins, check they are not hard-wired to VDD. Before pulling RESET/SLEEP high, check neither is hard-wired to ground. If a direct opposite-rail connection exists, do not add the proposed jumper; record it and revise the wiring.

## Current-reference gate BEFORE connecting 12 V

Use logic power ONLY: Uno USB, Uno 3.3 V -> VDD and common GND, ENA pulled HIGH. No VMOT and no motor power. The round orange copper pad is confirmed VREF, not ground. Keep its surface isolated from accidental wire contact.

1. Verify VDD approximately 3.3 V on DCV 15 range.
2. Measure copper-pad VREF to driver GND on DCV 3 range; read the BLACK 0-3 DC scale. Do not put VDD on this range, since 3.3 V exceeds it.
3. With the photographed R200 sense resistors (0.20 ohm), I_limit = VREF / 1.6. For example 1.0 V -> 0.625 A; 1.2 V -> 0.75 A; 1.3 V -> 0.813 A. Full-step coil current is about 70.7% of that maximum.
4. For this brief unloaded test, use a verified VREF no greater than about 1.3 V. This is a provisional conservative test ceiling, not a verified rating of the exact Minebea 17PM-K142BG01CN motor or thermal qualification. If VREF is higher or uncertain, report the reading before adding motor power. Very low VREF can cause weak movement; do not keep lowering VDD below 3.0 V to reduce current.
5. The divider is tied to VDD, so do not replace 3.3 V logic power with 5 V without recalculating and rechecking the current limit.

Uno STEP/DIR/ENA outputs are 5 V. The identified A4988's logic inputs permit 5 V with its VDD at 3.3 V (logic-input absolute maximum is 5.5 V, and HIGH threshold is 0.7*VDD). This does NOT apply to arbitrary other 3.3 V devices. Keep Uno logic and driver VDD on together; do not send signals into an unpowered driver.

## Run exactly one short test

1. Verify the header mapping and VREF gate above. Secure the spare motor on the bench with its shaft/gear unobstructed. No belt, filament, pen or printer axis connected.
2. Upload DaVinci_One_Motor_Test.ino to the Uno while 12 V is disconnected. This is a standalone test, not Marlin/Grbl; uploading replaces existing Uno firmware. If only your phone is available and you cannot upload yet, finish the logic-only checks and leave 12 V disconnected.
3. Disconnect USB, then connect the motor, bulk capacitor, fuse and all control wiring with everything unpowered. Check capacitor polarity and no rail shorts. Driver must be isolated from metal and the original motherboard.
4. Reconnect USB, open Serial Monitor at 115200. Sketch reports outputs disabled. Reset also leaves outputs disabled via ENA pull-up.
5. With connections secured and hands/probes clear, switch on the verified 12 V supply. Do not send a command if the driver/motor heats unusually or the supply behaves abnormally; cut 12 V.
6. Send lowercase s ONCE. Sketch enables the driver, sends 40 slow steps in one direction, pauses briefly, sends 40 steps back, then disables outputs. At full step and 1.8 degrees/step, that is about 72 degrees each way. Other microstep settings reduce the angle.
7. Send x to abort the software test. Removing 12 V is the physical stop. Software x is not an emergency-stop circuit. Expected: smooth slow movement each way, then a released shaft; small initial alignment motion is normal.
8. If it just vibrates, does not move, or heats unusually, cut 12 V. Do not swap wires or increase current while live. Record whether the shaft locks when enabled, whether it moves both ways, VDD/VREF values, and heating.
9. Turn OFF/unplug 12 V first, disconnect USB, and allow the capacitor to discharge before rewiring. Confirm VMOT is near zero on a DC voltage range before resistance tests or moving wires. Never deliberately short the capacitor.

The sketch is bounded and does not move automatically at boot. Host C++ compilation with simulated Arduino I/O passed checks for idle startup, ignored unknown commands, exactly 80 pulses per test, bounded run time, and abort disabling outputs. This is NOT an Arduino AVR build or a physical hardware test; the Arduino toolchain was unavailable here. A passed continuity test or an undamaged-looking driver is not proof of functional operation.

## Extend to three drivers ONLY after the single-motor test succeeds

| Axis | Uno STEP | Uno DIR | Uno ENABLE |
|---|---|---|---|
| X | D2 | D5 | D8 shared |
| Y | D3 | D6 | D8 shared |
| Z / bed | D4 | D7 | D8 shared |

Each driver gets its own verified coil pairs, VMOT/GND, VDD/GND, nearby bulk capacitor and verified control-mode wiring. Measure VREF for each module; do not assume identical divider behavior. Uno 3.3 V current budget must include every connected load (A4988 logic max 8 mA each, three about 24 mA; check the exact Uno's regulator budget). Use a proper low-voltage distribution terminal with suitable wiring/fusing for the expanded motor supply. Add/test endstops and travel limits before connecting printer axes or homing. The simple sketch runs ONLY the D2/D5 test channel; it is not three-axis motion firmware.

## Primary references

- Allegro A4988 datasheet (pinout, voltage limits, ENABLE, RESET/SLEEP, current formula): https://www.allegromicro.com/-/media/files/datasheets/a4988-datasheet.pdf
- Pololu A4988 carrier documentation (bulk capacitor and no hot-plugging): https://www.pololu.com/product/1182
- Grbl Uno signal mapping (future three-axis assignment): https://github.com/gnea/grbl/blob/master/grbl/cpu_map.h
- Marlin da Vinci reference: https://github.com/MarlinFirmware/Marlin/issues/23628 . Original-controller processor pin numbers are NOT Uno pins or carrier header positions.
