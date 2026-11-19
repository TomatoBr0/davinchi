# Paper corner tabs for the base plate

Four slip-on tabs that hold the corners of a US Letter sheet (215.9 x 279.4 mm) down on
the 220 x 285 x 10 mm base plate in `cad/base-plate/`. Each tab is a 26 x 26 mm square
centred on a plate corner. One quarter of it lies over the paper corner. The other three
quarters stick out past the plate as a handle. A spring under the plate pulls the tab down
onto the paper. The ArUco markers (`DICT_4X4_50`, ids 0-3) are printed on paper and glued on
the top of each tab, so the tabs are single colour.

## Files

- `corner_cap_id{0..3}.stl` - single-colour tab, in assembled plate coordinates
  (0 bottom-left, 1 bottom-right, 2 top-right, 3 top-left)
- `../DaVinci_Plate_220x285x10mm_SpringPockets.stl` - the plate with four 5 x 5 x 1 mm
  spring pockets in its underside (written to `cad/base-plate/`, next to the blank STL)
- `aruco_markers_print.svg` - four 24 mm stickers with dashed cut lines and a check bar
  (print at 100%)
- `layout.json` - parameters, geometry, paper rectangle, marker centres, plate pocket centres
- `preview_top.png`, `preview_iso.png`, `preview_cap_section.png` - renders from the generator
- `make_corner_caps.py` - the generator (numpy + Pillow only)

## How it works

- The tab slides on diagonally from outside the corner. Its walls sit beside the plate
  edges (0.2 mm clearance). Its bottom flange hangs under the plate corner.
- The top rests on the paper. Its underside is at the plate top (z = 10), so the tab top is
  only 2.4 mm above the paper.
- A spring sits between the flange and the plate underside. It seats in a 5 mm square pocket
  in the flange top (1.2 mm deep) and in a 5 mm square pocket in the plate underside (1.0 mm
  deep). Both pockets are centred 7 mm from each plate edge, so the spring sits under the
  paper corner. It pushes the plate up and the tab down, so the tab presses the paper.
- To load paper: lift the handle. The spring compresses and the top rises off the paper.
  Place the sheet, then let the handle down.

## Regenerate

```
python make_corner_caps.py
```

The script reads `plate_width`, `plate_depth` and `plate_thickness` from
`../DaVinci_Plate_Editable.scad` and fails if they are missing. It also deletes the old
two-colour `corner_cap_id*_inlay_*.stl` files if they are still in this folder. It writes the
spring-pocket plate STL to `cad/base-plate/`, and does not overwrite the blank STL. The
template is not modified.

`spring_pockets`, `spring_pocket_size`, `spring_pocket_depth` and `spring_pocket_inset` in the
SCAD file must match this script (`POCKET`, `PLATE_INDENT`, and an inset of
`(CLEAR_IN + HALF) / 2 = 7.0`).

## MEASURE YOUR SPRING

The defaults (`SPRING_OD = 4.5`, `SPRING_FREE = 12.0`, `PRELOAD = 3.0`,
`SPRING_SOLID = 4.0`) are a typical click-pen spring. They are not measured. Measure your
spring, then set these at the top of `make_corner_caps.py`:

- `SPRING_OD` - outside diameter. The pockets are `SPRING_OD + 0.5` square.
- `SPRING_FREE` - free length.
- `PRELOAD` - how much the spring is compressed when installed.
- `SPRING_SOLID` - solid height (fully compressed). It sets the usable lift. The default
  of 4.0 is a guess.

Then run `python make_corner_caps.py` again. The spring spans from the flange pocket floor
to the plate pocket ceiling. It is `INDENT + GAP_B + PLATE_INDENT = SPRING_FREE - PRELOAD`
long (9.0 mm with the defaults), and the script asserts this.
`GAP_B = SPRING_FREE - INDENT - PLATE_INDENT - PRELOAD` (6.8 mm with the defaults) is the
clear height between the flange top and the plate underside. The usable lift is
`(SPRING_FREE - PRELOAD) - SPRING_SOLID` (5.0 mm with the defaults), and the script asserts it
is at least 1 mm. The top can rise at most `GAP_B` before the flange hits the plate, but the
spring's solid height is the real limit.

## Print

- Print each tab **top face down** on the bed. The flat top is the bed contact. The walls
  and flange then point up, and the flange is a 13 mm wide overhang at the far end.
  **Supports are probably needed under the flange**, or print the tab on its side. I did not
  check this in a slicer.
- 0.2 mm layers, PETG. The tab is single colour, so any colour works.
- Tab height is 21.6 mm (z -9.2 to 12.4), with walls 3 mm thick.
- Plate STL: printed bottom face down, each pocket ceiling is a 5 x 5 mm bridge 1 mm above
  the bed. Not checked in a slicer.

## Markers (stickers)

- Print `aruco_markers_print.svg` at **100%** with no fit-to-page. The black square must
  measure 18 mm. Check with the 18 mm bar on the sheet.
- Cut the 24 mm stickers out on the dashed lines and glue each one centred on its tab top.
- Keep the white border. The 3 mm quiet zone around the black square is required for
  detection.
- The sticker orientation does not matter for the id.
- Marker ids: 0 bottom-left, 1 bottom-right, 2 top-right, 3 top-left.
- The markers are checked only in the rendered preview. OpenCV decodes ids 0-3 at the right
  corners. **The camera has not been tested with them.**

## Fit - check before printing a full set

- **Under the plate corners:** the flange hangs **9.2 mm** below the plate underside
  (`GAP_B + FLANGE_T` = 6.8 + 2.4), within 13 mm of each corner. **Check the bed supports,
  mounting hardware and Z mechanism under the plate corners** before printing.
- **Footprint:** the tabs reach 13 mm past the plate on every side, so the overall size at the
  corners is **246 x 311 mm** (plate 220 x 285). The walls and flange alone are 226.4 x 291.4 mm.
  Check frame and rod clearance with cardboard at the corners.
- **Paper coverage:** each tab covers only about 11 x 10 mm of each paper corner (paper inset
  2.05 mm in X and 2.8 mm in Y).
- **Height:** the tab top is at z = 12.4 mm, which is 2.4 mm above the plate top and the
  paper. The paper is treated as zero thickness (0.1 mm in the preview). The tab top is
  low, so it clears the pen.
- The plate pockets (STL and SCAD) leave 9 mm of plate between the pocket ceiling and the
  plate top. A 5 mm deep top counterbore would still leave 4 mm above the pocket ceiling.
- Keep pen travel clear of the tabs.
- Install by sliding each tab diagonally onto its corner while lifting the handle.
  The tabs are a spring fit. If they lift, tape them down or add a small screw.

## Geometry check (last run)

- Each tab: 280 triangles, 0 open edges, 0 non-manifold edges, volume 3.7040 cm3.
  All four are the same volume.
- Analytic volume (inclusion-exclusion over the boxes, minus the flange pocket) is 3.7040 cm3.
  Difference is below 1e-14 cm3.
- Plate with spring pockets (`../DaVinci_Plate_220x285x10mm_SpringPockets.stl`): 212 triangles,
  0 open, 0 non-manifold, volume 626.9000 cm3 (627 cm3 minus 4 x 0.025 cm3).
