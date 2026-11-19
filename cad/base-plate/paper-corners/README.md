# Paper corner caps for the base plate

Four slip-on caps that hold the corners of a US Letter sheet (215.9 x 279.4 mm) flat
on the 220 x 285 x 10 mm base plate in `cad/base-plate/`. Each cap is an L-shaped
wrapper around one plate corner with a cover over the paper corner, and carries an
ArUco marker (`DICT_4X4_50`, ids 0-3) on its top face for camera calibration.

Files:

- `corner_cap_id{0..3}.stl` - single-colour cap (4 files, one per corner)
- `corner_cap_id{N}_inlay_body.stl` - cap with the marker's black cells recessed 0.6 mm
- `corner_cap_id{N}_inlay_black.stl` - the black marker cells that fill that recess
- `aruco_markers_print.svg` - ids 0-3 at exact size (print at 100%, black square = 24 mm) for single-colour caps
- `layout.json` - units, plate and paper rectangles, cap parameters, marker centres and top z
- `preview_top.png`, `preview_iso.png`, `preview_cap_section.png` - renders from the generator
- `make_corner_caps.py` - the generator (numpy + Pillow only)

## Regenerate

```
python make_corner_caps.py
```

The script reads `plate_width`, `plate_depth` and `plate_thickness` from
`../DaVinci_Plate_Editable.scad` and fails if they are missing. The template is not
modified. All STLs are in assembled plate coordinates (origin = plate lower-left corner,
+X right, +Y up, plate on z 0..10), so each file is already in its final position.

## Print

- Print each cap **top face down** (the slicer should flip it, so the top face is on the
  bed). The geometry is meant to avoid overhangs in that orientation; this was not checked
  in a slicer.
- **Cap colour must be white or very light.** The marker's quiet zone (the 4 mm border
  around the black square) is the cap surface itself; a dark cap makes the marker
  unreadable. Single-colour caps need a printed paper marker stuck on top instead.
- Two-colour: print `_inlay_body` in white/light and `_inlay_black` in black, both
  with the same cap orientation. The black cells sit in the 0.6 mm recess.
- 0.2 mm layers, PETG.

## Fit

- Each cap adds WALL + CLEAR = 3.0 + 0.2 = 3.2 mm per side. The assembled footprint is
  about **226.4 x 291.4 mm** (plate 220 x 285).
- Check frame and rod clearance with cardboard first, at the real assembled footprint.
- Each cap covers about 36 mm of each paper corner (CAP 38 mm from the plate edge, paper
  inset 2.05 mm in X and 2.8 mm in Y).
- Clearance between the plate edge and the wall is 0.2 mm. The 0.6 mm slot holds the
  sheet; the cap top is 10 mm above the paper (z = T + 10 = 20 mm).
- Keep pen travel away from the 10 mm caps.
- The caps are a friction fit. If they lift, tape them down or add a small screw.
- The markers are checked only in the rendered preview (OpenCV decodes ids 0-3 with the
  right corner placement). The camera has not been tested with them.
