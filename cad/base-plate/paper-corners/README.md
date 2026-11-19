# Paper corner tabs for the base plate

Four slip-on tabs that hold the corners of a US Letter sheet (215.9 x 279.4 mm) down on
the 220 x 285 x 10 mm base plate in `cad/base-plate/`. Each tab is a 26 x 26 mm square
centred on a plate corner. One quarter of it lies over the paper corner and holds the
sheet down with a small compression spring. The other three quarters stick out past the
plate as a handle. The ArUco markers (`DICT_4X4_50`, ids 0-3) are printed on paper and
glued on the top of each tab, so the tabs are single colour.

## Files

- `corner_cap_id{0..3}.stl` - single-colour tab, in assembled plate coordinates
  (0 bottom-left, 1 bottom-right, 2 top-right, 3 top-left)
- `aruco_markers_print.svg` - four 24 mm stickers with dashed cut lines and a check bar
  (print at 100%)
- `layout.json` - parameters, geometry, paper rectangle, marker centres, footprint
- `preview_top.png`, `preview_iso.png`, `preview_cap_section.png` - renders from the generator
- `make_corner_caps.py` - the generator (numpy + Pillow only)

## How it works

- The tab slides on diagonally from outside the corner. Its walls sit beside the plate
  edges (0.2 mm clearance) and its lips slide under the plate bottom edge.
- The spring sits in a 5 mm square indent in the underside of the top, and presses the
  paper corner down.
- The lips stop the spring from pushing the tab up.
- To load paper: slide the 4 tabs off by their handles, place the sheet, and slide the
  tabs back on.

## Regenerate

```
python make_corner_caps.py
```

The script reads `plate_width`, `plate_depth` and `plate_thickness` from
`../DaVinci_Plate_Editable.scad` and fails if they are missing. It also deletes the old
two-colour `corner_cap_id*_inlay_*.stl` files if they are still in this folder. The
template is not modified.

## MEASURE YOUR SPRING

The defaults (`SPRING_OD = 4.5`, `SPRING_FREE = 12.0`, `PRELOAD = 3.0`) are a typical
click-pen spring. They are not measured. Measure your spring, then set these at the top
of `make_corner_caps.py`:

- `SPRING_OD` - outside diameter. The pocket is `SPRING_OD + 0.5` square.
- `SPRING_FREE` - free length.
- `PRELOAD` - how much the spring is compressed when installed.

Then run `python make_corner_caps.py` again. `GAP = SPRING_FREE - INDENT - PRELOAD`
(7.8 mm with the defaults) is the clear height between the paper and the underside of the
top. The script asserts that the installed length (9.0 mm) equals `SPRING_FREE - PRELOAD`.

## Print

- Print each tab **top face down** on the bed. The flat top is the bed contact. Walls and
  lips then point up, and the 2 mm lip at the far end is a small overhang. The overhang
  was not checked in a slicer.
- 0.2 mm layers, PETG. The tab is single colour, so any colour works.
- Tab height is 22 mm (z -1.8 to 20.2), with walls 3 mm thick.

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

- **Footprint:** the tabs reach 13 mm past the plate on every side, so the overall size at the
  corners is **246 x 311 mm** (plate 220 x 285). The walls and lips alone are 226.4 x 291.4 mm.
  Check frame and rod clearance with cardboard at the corners.
- **Lips:** the lips sit 1.8 mm below the plate bottom (0.2 mm gap + 1.6 mm thick). Check
  the plate supports and mounts near the corners.
- **Paper coverage:** each tab covers only about 11 x 10 mm of each paper corner (paper inset
  2.05 mm in X and 2.8 mm in Y).
- **Height:** the tab top is at z = 20.2 mm, which is 10.2 mm above the plate top. The paper
  is treated as zero thickness (0.1 mm in the preview).
- Keep pen travel clear of the tabs.
- The tabs are a friction and spring fit. If they lift, tape them down or add a small screw.

## Geometry check (last run)

- Each tab: 396 triangles, 0 open edges, 0 non-manifold edges, volume 3.4063 cm3.
  All four are the same volume.
- Analytic volume (inclusion-exclusion over the boxes, minus the pocket) is 3.4063 cm3.
