# Calibration step 1: steps/mm from a test square

Files:
- `calibration_sheet.pdf`: US Letter sheet, 4 ArUco markers (DICT_4X4_50, ids 0-3, 20 mm), 100 mm test square with mm rulers, centre crosshair, check box.
- `calibration_sheet.json`: marker corners, square and crosshair positions in sheet mm (origin bottom-left, y up).
- `../../tools/calibration_test.nc`: draws the 100 mm square and a crosshair in sheet coordinates.
- Regenerate the sheet with `python tools/make_calibration_sheet.py`.

## Procedure

1. Print `calibration_sheet.pdf` at **100% / Actual size** (no fit-to-page, no scaling).
2. Measure the printed 100 mm square with a ruler. It must read 100.0 mm edge to edge. If not, the printer is scaling: fix the print settings and reprint before continuing.
3. Tape the sheet to the bed. Align the paper's bottom-left corner (the ORIGIN corner) with the plotter origin.
4. Jog the pen to the crosshair centre at sheet (108, 140) mm, using the sheet rulers as a guide.
5. Send the setup over serial, one line at a time, waiting for `ok` after each line. Use measured values only:
   - `$XMM=...`, `$YMM=...`, `$ZMM=...` (current steps/mm)
   - `$XMIN=0 $XMAX=...`, `$YMIN=0 $YMAX=...` (must cover at least X 160 and Y 190)
   - `$XPOS=...`, `$YPOS=...`, `$ZPOS=...` (the pen position from step 4)
   - `$PENUP=...`, `$PENDOWN=...` (measured pen Z endpoints)
   - `ARM`
6. Load a dark pen. Send `tools/calibration_test.nc` line by line, waiting for `ok` after each line. The file has no comments because the firmware rejects them. It ends with a return to the origin. Do not run it until the travel limits in step 5 are set.
7. Let the ink dry. Photograph the sheet flat, with all four markers fully visible and the camera roughly square to the page. Then run:
   `python tools/calibrate_from_photo.py photo.jpg --xmm <current X> --ymm <current Y>`
   The script prints the measured X and Y sizes, skew, centre offset and suggested `$XMM` and `$YMM`. It needs `pip install opencv-contrib-python`.
8. Or measure by hand with the rulers. Compute `new = old * expected / measured` separately for X and Y, with expected = 100.0 mm. For example, a drawn X of 98.0 mm with `$XMM=80` gives `80 * 100 / 98 = 81.63`.
9. Enter the new values, then repeat from step 5 until the square measures within about 0.2 mm.

Notes:
- The grey square on the sheet is the printed reference. Draw with a dark pen so the trace stands out in the photo.
- The sheet's measurements assume the paper is flat and not moved between drawing and photo. Re-tape if it shifts.
- `M92 X.. Y.. Z..` (what the app's **Apply steps/mm** button sends) saves steps/mm and the taught max corner to EEPROM, so they survive a power cycle. The `$XMM` route below is RAM-only. The origin is never saved: jog and send M210 after every power-up.
