# Paper plate

US Letter plate with four 10 mm L-shaped corner stops and four ArUco marker spots
(DICT_4X4_50, ids 0-3, counter-clockwise from bottom-left). Regenerate after changing
parameters at the top of `make_paper_plate.py` (only numpy + Pillow needed):

```bash
python hardware/paper-plate/make_paper_plate.py
```

| File | Use |
|---|---|
| `paper_plate.stl` | Single-colour print. Markers: print `aruco_markers.svg` at 100% and stick in the 0.4 mm pockets |
| `paper_plate_inlay.stl` + `aruco_inlay_black.stl` | Two-tool print (e.g. Prusa XL): plate in white/light, cells in black, 0.6 mm inlay |
| `aruco_layout.json` | Marker centres in paper mm for the camera homography |
| `preview.png` | Top view |

Size 312.9 x 306.4 x 4 mm plate, walls 3 mm tall (fits a 360 mm XL bed; ~390 cm³ solid,
so use modest infill). Watertight meshes (0 open/non-manifold edges); markers verified
with OpenCV's detector on the preview.

Notes:
- Assumptions: "1 cm thick" = wall width; wall height 3 mm so pen-up travel stays clear.
  Keep travel moves inside the paper or raise pen-up Z above 3 mm.
- The plate is larger than the Da Vinci 1.0's ~200 x 200 mm travel: see `docs/build-order.md` stage 0.
- No lip over the paper (an unsupported lip would fuse to the plate); use low-tack tape
  or magnets if the sheet lifts.
- Paper sticker pockets are 32.2 mm square; the black square must measure 24 mm.
