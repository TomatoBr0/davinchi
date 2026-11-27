# From a recorded stroke to paper

## While wiring

Start with the [single-motor bench test](../firmware/DaVinci_One_Motor_Test/README.md). Upload over USB with motor power disconnected. The salvaged driver header and current setting still need the measurements listed there. The Uno pin assignments in the plotter sketch describe its outputs. Use the hardware notes to identify the corresponding driver inputs.

## Prepare a job offline

To use your existing phone samples, download the dataset ZIP from the Da Vinci capture site and run `python import_phone_export.py export.zip --db data/samples.sqlite3`. Reimporting the same export skips previously imported IDs. Traces and recorded strokes retain their lift boundaries.

Run `python app.py`, open http://127.0.0.1:8775 (Carl owns 8765; use `--port` if 8775 is busy), save some handwritten letter or word samples, then compose and preview text using those labels. Download the Uno job. The SVG preview shows the page orientation. The GRBL preview uses a different dialect. For the first test, use the bundled 5 mm square instead.

    python send_plot.py examples/first-square.dvc

This checks the whole file and prints stroke count, maximum coordinates and feed. A successful check does not measure the hardware.

## Commission the machine

1. Verify each axis independently with the bench sketch. Record the direction, measured steps per millimeter at the actual driver microstep setting, and usable travel with the plate and pen holder installed. Positive X follows the page to the right and positive Y goes down the page. Set up a repeatable physical page origin with clearance for the whole job.
2. In Arduino IDE open `firmware/plotter/plotter.ino`, select Arduino Uno and the USB port, and upload with motor power disconnected. Close Serial Monitor before using the sender.
3. Copy `machine.example.json` to `machine.json`. Replace each null with a measured number. XMM, YMM and ZMM are steps/mm. XMIN and YMIN are zero at the manually established page origin. XMAX and YMAX are usable reach from that origin. ZMIN and ZMAX bound the bed motion. PENUP and PENDOWN are two distinct coordinates in that same Z system, one clear of the page and the other just touching. Neither the plate size nor paper size establishes machine travel.
4. Check a job against your profile with `python send_plot.py examples/first-square.dvc --machine machine.json`. A Letter-sized design may exceed this printer's usable travel.
5. Install the USB dependency with `python -m pip install pyserial`. Run `python -m serial.tools.list_ports` to identify the Uno. Position the carriage at page X0 Y0 and bed at the measured PENUP height. Each new job assumes you physically restored that position. Start with the pen removed, verified motor wiring, and an accessible physical power cutoff.

    python send_plot.py examples/first-square.dvc --machine machine.json --port COM4 --at-origin

Replace COM4 with the listed port. The sender loads calibration into RAM, declares the physical starting coordinates, checks the controller limits and waits for acknowledgment after every command. There is no automatic homing or endstop detection. Check the travel direction, pen lift and measured 5 mm sides before fitting the pen and repeating at the same origin. If position is lost or the job is interrupted, re-establish the origin before restarting.
