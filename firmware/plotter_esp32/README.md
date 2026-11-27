# Da Vinci plotter: Arduino Nano ESP32 firmware

Port of `firmware/plotter/plotter.ino` (Uno) to the Nano ESP32 (ESP32-S3, 3.3 V logic).
Same line protocol over USB serial, TCP port 23, and an HTTP jog page. Calibration and Wi-Fi
credentials are stored in NVS through `Preferences`, not EEPROM.

Status: compiles against `arduino:esp32:nano_nora` (arduino-esp32 2.0.18). Not uploaded, not run on hardware.

## Pin map (Arduino pin names, Nano ESP32)

| Function | Pin | GPIO | Notes |
|---|---|---|---|
| X STEP | D2 | 5 | Uno D2 |
| X DIR | D3 | 6 | |
| Y STEP | D4 | 7 | |
| Y DIR | D5 | 8 | |
| Z STEP | D6 | 9 | |
| Z DIR | D7 | 10 | |
| ENABLE (shared, active low) | D8 | 17 | Internal pull-up at boot, external 10k to 3.3 V recommended |
| X endstop | D9 | 18 | INPUT_PULLUP, optical open-collector |
| Y endstop | D10 | 21 | INPUT_PULLUP, optical open-collector |
| Z endstop | D11 | 38 | INPUT_PULLUP, optical open-collector |
| LED ready | A0 | 1 | |
| LED busy | A1 | 2 | |
| LED alarm | A3 | 4 | |
| LED heartbeat | D12 | 47 | |

Avoided: GPIO0/3/45/46 (strapping), GPIO19/20 (USB), D0/D1 (UART0).

The DIR pins moved, so do not wire pin-for-pin from the Uno. Harness mapping (planned A4988
wiring in `DAVINCI_HARDWARE_CONTEXT.md`):

| Axis | Uno STEP / DIR | Nano ESP32 STEP / DIR |
|---|---|---|
| X | D2 / D5 | D2 / D3 |
| Y | D3 / D6 | D4 / D5 |
| Z | D4 / D7 | D6 / D7 |
| ENABLE | D8 | D8 |

## Wiring and power

- Power: 12 V PSU to VIN (check the board's VIN rating before connecting). Nano ESP32 USB for
  programming and serial only. Tie PSU ground, Nano GND, and driver logic ground together.
- Driver logic supply: power the A4988 VDD from the Nano 3V3 pin so STEP, DIR, and ENABLE stay at
  3.3 V. Do not put 5 V on any Nano pin. If a 5 V-logic driver is used, level-shift the outputs.
- ENABLE: active low, one shared net to all three drivers. Add a 10k pull-up to 3.3 V so the
  drivers stay disabled during reset.
- Endstops: optical slot sensor, NPN open collector, pull-up to 3.3 V. Beam blocked means the
  transistor is off, so the input reads HIGH (`ENDSTOP_BLOCKED_LEVEL`). Change that define if the
  sensors are wired the other way. Sensor VCC at 3.3 V.
- LEDs: pin, then 220 ohm, LED, GND. HIGH lights the LED.

## Settings and commands

Same commands as the Uno firmware (`ARM`, `DISARM`, `J`, `G0`/`G1`, `G4`, `M3`/`M5`, `M17`/`M18`,
`M92`, `M114`, `M115`, `M210`, `M211`, `G92`, `$XMM` and the rest, `!` abort). Differences:

- Default steps/mm: X 5, Y 5, Z 160. Saved values in NVS override them.
- `$SSID=<name>` and `$PASS=<password>`: Wi-Fi station credentials. Accepted on USB serial only.
  The value runs to end of line and keeps its case. Password is 8-63 characters, or empty for an
  open network. Stored in NVS.
- `WIFI`: prints the connection state and IP.
- `$ENDSTOPS=0|1`: enables the endstop stop. Default 0. Saved to NVS. Set to 1 only after the
  sensors are wired and tested. With it on, any axis moving toward its endstop (negative direction,
  origin end assumed) stops immediately and invalidates the position.
- `M119`: reports `ENDSTOPS=` state and each axis endstop (1 = blocked).

Wi-Fi: station mode. Connect over TCP port 23 with netcat or a raw socket, one line per command.
Telnet option negotiation is not handled. The HTTP page is at `http://<ip>/`. It has jog buttons
(X, Y, Z), pen up/down, enable/disable, status, and a raw command box.

## Known limits

- TCP and HTTP have no authentication. Run on a trusted LAN only. Wi-Fi credentials cannot be set
  over the network.
- The HTTP page cannot stop a move in progress: HTTP is served between moves. Use `!` over serial
  or TCP to abort. A jog is short, so the page just waits for it to finish.
- Motion runs as a blocking `micros()` schedule in `loop()`, not a hardware timer. Wi-Fi runs on
  core 0. Core 1 sleeps with `delay(1)` during slow starts so the idle task keeps running.
- Step rate is capped at 1000 steps/s, the same as the Uno. The ESP32 can go faster. Measure
  before raising `MAX_STEP_RATE_SPS`.

## Unverified

- Not uploaded and not run. No serial port was opened. No motor, driver, or endstop has been
  tested.
- VIN input range, endstop polarity, A4988 VIH at 3.3 V, and the Wi-Fi join and TCP/HTTP behavior
  are all unverified on hardware.
- Endstop stop assumes the sensors sit at the origin (minimum) end of each axis.
