# Validation checklist

The automated tests run real SQLite and HTTP operations, then verify actual composition and G-code output. They **do not** simulate motors or certify that the machine is safe. Do not count a code path as physically tested unless you observed hardware execute it.

## Software checks (real behavior)

Run:

\`\`\`bash
python -m unittest discover -s tests -v
python app.py
\`\`\`

Open http://127.0.0.1:8775.

- [ ] Draw an actual word (with more than one connected stroke) on a touchscreen. Save. Refresh the page; the exact number/order of strokes survives.
- [ ] Record 4-5 separate versions of \`a\` and a connected sample of \`th\`. Confirm each is a distinct stored sample.
- [ ] Add context-specific \`th\` variants. Compose sentences with various neighboring characters; verify the selection IDs change appropriately.
- [ ] Write a long looped stroke; confirm the generated SVG keeps the loop and no individual pen lifts are invented.
- [ ] Import a photograph as the tracing reference. Trace it and save. Confirm that only the traced coordinates are stored, not invented stroke order from the photograph.
- [ ] Compose the same text with the same seed twice: outputs match byte-for-byte. Change the seed: at least some variations change.
- [ ] Add an unknown character. Verify a visible warning lists the missing character instead of fabricating it.
- [ ] Download SVG, open it separately in a browser or vector editor, and compare the shape to the drawing.
- [ ] Open the G-code text: verify millimeter units, absolute positions, feed values, pen-up before XY repositioning and pen-down only for strokes.
- [ ] Turn Z variation on then off. Only the enabled version should emit varying Z values on drawing moves.
- [ ] Close and restart the Python program. Verify data survives and deletion actually removes a sample.

## Hardware checks (MUST be performed on real printer)

- [ ] Read exact model, revision and PSU labels. Inspect for fire/melt damage.
- [ ] With power removed, measure which leads make up each motor coil pair; never trust color alone.
- [ ] Verify low-voltage PSU DC output voltage, polarity and current rating before connecting.
- [ ] Verify A4988 pin orientation, current-limit calculation and heat-sinking, with a single motor connected.
- [ ] At low speed and with the pen removed, jog 1mm in each axis and measure physical travel; check both polarities.
- [ ] Verify active limit switch behavior **per axis** and test a stopped or blocked axis; never rely on software limits alone.
- [ ] Test homing at minimal conservative speeds. Confirm an accessible motor power disconnect works.
- [ ] Calibrate steps/mm and true usable pen workspace with actual physical measurements.
- [ ] Test pen-up vs pen-down Z direction and travel with a **spring-loaded pen holder** on sacrificial paper.
- [ ] Plot a 10mm line, 10mm square, circle and repeated connected word. Inspect scale, squareness, backlash, skipped steps and exact return-to-origin.
- [ ] Only after all above, try low amplitude Z modulation. Watch for bed lag, pen gouging, jamming and motor heating.
- [ ] Wireless bridge (if implemented later): verify level shift, Grbl flow control, USB/serial contention, auth and recovery on link loss.

## Known gaps

Automatic photo segmentation/recognition, adaptive multi-glyph joins, measured pressure feedback, G-code streaming, machine homing and Arduino/ESP32 firmware deployment are **not yet implemented**. The hardware guide is a starting point, not a measured schematic for your printer.
