# Fill a worksheet with the plotter

`tools/worksheet.py` takes one phone photo of a US Letter worksheet on the bed, finds the page and a pen dot that marks the head, and writes J moves for `tools/jog.py`. No camera hardware, no extra cost.

## Page size: four placements

Letter is 215.9 x 279.4 mm. Usable travel is about +-88 mm from the head start, so one placement reaches a 176 mm square. The page does not fit, so the job is split into four placements of the paper. The head stays at bed centre (the head start) every time. You slide the paper so a different part of it sits under the head.

Put the head start over these worksheet points (mm, measured from the top-left corner of the sheet as you read it):

| Placement | Head over (x, y) | Reach covers (x, y) |
|---|---|---|
| 1 | 54, 70 | x -34..142, y -18..158 |
| 2 | 162, 70 | x 74..250, y -18..158 |
| 3 | 54, 210 | x -34..142, y 122..298 |
| 4 | 162, 210 | x 74..250, y 122..298 |

The four boxes together cover the whole sheet. Each answer must lie wholly inside one placement. Text wider than about 65 mm can straddle a boundary and gets skipped with a message. Shorten it or split it into two elements.

The tool does not need the head to land exactly on those points. It uses wherever the dot really is. Aim roughly, and the reach check decides what is drawn.

## Orientation

The worksheet's top edge points away from you (toward the back of the machine), and the text reads normally from where you sit. In that orientation page x maps to machine -X and page y maps to machine -Y. Machine +X is your left, +Y is away from you.

## Step by step, per placement

1. Centre the head by hand at the start point, as usual. Set up the plotter as you do for any job (`XMM`, `YMM`, `ZMM` env vars, default 5, 5, 160).
2. Place the sheet so the target area from the table is under the head. Top edge away, text readable.
3. Make the start dot. Lower the pen, touch the paper for a moment, and lift:
   ```
   python tools/jog.py "J Z-5 F100"
   python tools/jog.py "J Z5 F100"
   ```
   Use a solid pen dot 4-6 mm wide. Do not move the head or the sheet between the dot and the photo.
4. Photograph the sheet from directly above. Show all four paper corners, use a dark background under the paper, avoid glare, and keep the worksheet top edge at the top of the photo.
5. Run the planner:
   ```
   python tools/worksheet.py photo.jpg answers.json --out-dir worksheet_out
   ```
   Check `worksheet_out/preview.png`. Blue strokes will be drawn here, red ones are out of reach for this placement, and the green box is the reach area.
6. Draw:
   ```
   python tools/jog.py @<absolute path printed as "run:">
   ```
   The job starts with the pen up, ends with the head back at the start, and leaves the pen up.
7. Move the sheet to the next placement, return the head to centre, and repeat from step 1.

The planner draws every element that is in reach, and placements overlap. Keep one answers file per placement, for example `answers_p1.json`, holding only the answers you want drawn there. Otherwise an answer that sits in an overlap gets drawn twice.

## Answers file

```json
[
  {"x": 20, "y": 30, "text": "NAME: ALEX", "size_mm": 6},
  {"x": 20, "y": 45, "text": "DATE 11/26", "size_mm": 5}
]
```

- `x, y`: left end of the first baseline, worksheet mm, y grows downward.
- `size_mm`: cap height (default 5). Line spacing is 1.4 x size for `\n` line breaks.
- Characters: A-Z (lowercase is drawn as uppercase), 0-9, space, `. , - _ : / ? + = ( )`. Anything else is an error.

## Start dot and multiple dots

The planner looks for solid dots 3.5-8 mm wide. If there is exactly one, it is the head start. Dots from earlier placements stay on the sheet. When there is more than one, the planner lists their positions and asks for `--start-mm X Y` with the coordinates of the new dot. Pass that explicitly. Printed text is not treated as a dot because letters are not solid circles.

## Z convention

Taken from `tools/lily_run.py`: travel height is `Z-3` from the bottom stop, pen down is `Z-2` more (writing height `Z-5`), and pen up is `Z+2`. The job starts at the bottom stop and returns there. If the pen writes too light or too heavy, change `LIFT` and `TRAVEL_Z` in `tools/worksheet.py` to match what `lily_run.py` uses on your machine.

## Limits

- Photo accuracy is about 0.25 mm on the page plane. Paper must be flat and must not move between dot and photo.
- The worksheet size assumes an unmodified US Letter sheet. Cropping or scanner scaling breaks the corner-based mapping.
- The dot is found by blob shape. A very dark printed mark that looks like a solid dot will be a false match. Use `--start-mm`.
- The 88 mm reach assumes the head start is at bed centre and that travel is symmetric. Check your real limits before a long job.
- Tests cover the synthetic image path only. Nothing has been drawn on the hardware yet.
