"""Write the 1:1 calibration sheet (US Letter) and its JSON sidecar.

Coordinates are millimetres with the origin at the bottom-left corner of the
page (y up). That corner is the plotter origin: tape the paper corner to the
origin of the bed. Run: python tools/make_calibration_sheet.py
"""
import json
import os
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "docs", "calibration")
PDF_PATH = os.path.join(OUT_DIR, "calibration_sheet.pdf")
JSON_PATH = os.path.join(OUT_DIR, "calibration_sheet.json")

PAGE_W, PAGE_H = 215.9, 279.4  # Letter, exact
MARKER_MM = 20.0
# DICT_4X4_50 inner 4x4 bits, row-major, '1' = black. Generated with cv2 and
# checked against cv2.aruco.generateImageMarker in verify_with_cv2().
MARKER_BITS = {
    0: ["0100", "1010", "1100", "1101"],
    1: ["1111", "0000", "0110", "0101"],
    2: ["1100", "1100", "1101", "0010"],
    3: ["0110", "0110", "1011", "1001"],
}
# id -> (role, lower-left corner in mm)
MARKER_POS = {
    0: ("top-left", (10.0, PAGE_H - 10.0 - MARKER_MM)),
    1: ("top-right", (PAGE_W - 10.0 - MARKER_MM, PAGE_H - 10.0 - MARKER_MM)),
    2: ("bottom-right", (PAGE_W - 10.0 - MARKER_MM, 10.0)),
    3: ("bottom-left", (10.0, 10.0)),
}

SQ_X, SQ_Y, SQ = 58.0, 90.0, 100.0  # test square, lower-left corner
CENTER = (SQ_X + SQ / 2, SQ_Y + SQ / 2)
ARM = 10.0  # crosshair half-length
XR_X0, XR_X1, XR_Y = 10.0, 160.0, 80.0  # 150 mm X ruler, baseline y
YR_X, YR_Y0, YR_Y1 = 50.0, 90.0, 190.0  # 100 mm Y ruler, baseline x


def verify_with_cv2():
    try:
        import cv2
    except ImportError:
        return "cv2 not installed, bits not cross-checked"
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for mid, rows in MARKER_BITS.items():
        img = cv2.aruco.generateImageMarker(d, mid, 6, borderBits=1)
        for r in range(4):
            for c in range(4):
                black = img[r + 1, c + 1] < 128
                assert black == (rows[r][c] == "1"), f"marker {mid} mismatch"
    return "cv2 cross-check ok"


def draw_marker(c, mid, x0, y0):
    cell = MARKER_MM / 6.0
    c.setFillGray(0)
    c.rect(x0 * mm, y0 * mm, MARKER_MM * mm, MARKER_MM * mm, stroke=0, fill=1)
    c.setFillGray(1)
    c.rect((x0 + cell) * mm, (y0 + cell) * mm, 4 * cell * mm, 4 * cell * mm, stroke=0, fill=1)
    c.setFillGray(0)
    for r, row in enumerate(MARKER_BITS[mid]):
        for col, bit in enumerate(row):
            if bit == "1":
                # row 0 is the top row of the marker
                cy = y0 + (5 - (r + 1)) * cell
                cx = x0 + (col + 1) * cell
                c.rect(cx * mm, cy * mm, cell * mm, cell * mm, stroke=0, fill=1)


def line(c, x0, y0, x1, y1, w=0.25, gray=0):
    c.setLineWidth(w)
    c.setStrokeGray(gray)
    c.line(x0 * mm, y0 * mm, x1 * mm, y1 * mm)


def text(c, x, y, s, size=7, align="l"):
    c.setFont("Helvetica", size)
    c.setFillGray(0)
    fn = {"l": c.drawString, "c": c.drawCentredString, "r": c.drawRightString}[align]
    fn(x * mm, y * mm, s)


def draw_rulers(c):
    # X ruler: ticks point up from baseline, labels above
    line(c, XR_X0, XR_Y, XR_X1, XR_Y, 0.4)
    for v in range(int(XR_X0), int(XR_X1) + 1):
        h = 3.5 if v % 10 == 0 else (2.2 if v % 5 == 0 else 1.2)
        line(c, v, XR_Y, v, XR_Y + h, 0.25)
        if v % 10 == 0:
            text(c, v, XR_Y + 4.5, str(v), 6, "c")
    text(c, XR_X1 + 3, XR_Y, "X mm", 6)
    # Y ruler: ticks point left from baseline, labels left
    line(c, YR_X, YR_Y0, YR_X, YR_Y1, 0.4)
    for v in range(int(YR_Y0), int(YR_Y1) + 1):
        h = 3.5 if v % 10 == 0 else (2.2 if v % 5 == 0 else 1.2)
        line(c, YR_X, v, YR_X - h, v, 0.25)
        if v % 10 == 0:
            text(c, YR_X - 4.5, v - 0.9, str(v), 6, "r")
    text(c, YR_X - 3, YR_Y1 + 3, "Y mm", 6, "c")


def build_pdf():
    os.makedirs(OUT_DIR, exist_ok=True)
    c = canvas.Canvas(PDF_PATH, pagesize=letter)
    c.setTitle("DaVinci plotter calibration sheet")

    for mid, (_, (x0, y0)) in MARKER_POS.items():
        draw_marker(c, mid, x0, y0)

    text(c, PAGE_W / 2, 262, "DaVinci plotter calibration sheet (print at 100% / Actual size)", 9, "c")

    # Target square: light grey outline so a dark pen trace stands out
    c.setStrokeGray(0.6)
    c.setLineWidth(0.5)
    c.rect(SQ_X * mm, SQ_Y * mm, SQ * mm, SQ * mm, stroke=1, fill=0)
    text(c, SQ_X, SQ_Y + SQ + 3, "100 mm test square (grey = printed reference)", 6)
    text(c, SQ_X + SQ + 1, SQ_Y + SQ + 1, "(158, 190)", 5, "r")

    # Crosshair at square centre
    cx, cy = CENTER
    line(c, cx - ARM, cy, cx + ARM, cy, 0.2)
    line(c, cx, cy - ARM, cx, cy + ARM, 0.2)
    text(c, cx + 1.5, cy + 1.5, f"centre ({cx:.0f}, {cy:.0f})", 5)

    draw_rulers(c)

    # Origin mark and plotter axis arrows
    line(c, 0, 0, 15, 0, 0.8)
    line(c, 0, 0, 0, 15, 0.8)
    text(c, 33, 22, "ORIGIN (0, 0): align paper corner to plotter origin", 6)
    line(c, 36, 42, 72, 42, 0.8)
    c.setFillGray(0)
    p = c.beginPath()
    p.moveTo(74 * mm, 42 * mm)
    p.lineTo(70.5 * mm, 43.2 * mm)
    p.lineTo(70.5 * mm, 40.8 * mm)
    p.close()
    c.drawPath(p, stroke=0, fill=1)
    text(c, 74.5, 40.5, "plotter X+", 6)
    line(c, 36, 42, 36, 72, 0.8)
    p = c.beginPath()
    p.moveTo(36 * mm, 74 * mm)
    p.lineTo(34.8 * mm, 70.5 * mm)
    p.lineTo(37.2 * mm, 70.5 * mm)
    p.close()
    c.drawPath(p, stroke=0, fill=1)
    text(c, 38, 72.5, "plotter Y+", 6)

    # Printed check box
    c.setLineWidth(0.6)
    c.setStrokeGray(0)
    c.rect(30 * mm, 215 * mm, 5 * mm, 5 * mm, stroke=1, fill=0)
    text(c, 38, 217.5, "CHECK: the 100 mm square must measure 100.0 mm edge to edge on the X and Y rulers.", 7)
    text(c, 38, 213, "If it does not, printer scaling is wrong: reprint at 100% / Actual size (no fit-to-page).", 7)

    text(c, PAGE_W / 2, 5.5,
         "ArUco DICT_4X4_50 ids 0-3, 20 mm outer size. Sheet units mm, origin bottom-left.", 5.5, "c")
    c.showPage()
    c.save()


def build_json():
    markers = []
    for mid, (role, (x0, y0)) in MARKER_POS.items():
        s = MARKER_MM
        corners = [[x0, y0 + s], [x0 + s, y0 + s], [x0 + s, y0], [x0, y0]]  # TL, TR, BR, BL
        markers.append({"id": mid, "role": role, "size_mm": s, "corners_mm": corners})
    sq = [[SQ_X, SQ_Y], [SQ_X + SQ, SQ_Y], [SQ_X + SQ, SQ_Y + SQ], [SQ_X, SQ_Y + SQ]]
    data = {
        "page": {"size": "letter", "width_mm": PAGE_W, "height_mm": PAGE_H,
                 "origin": "bottom-left, y up; the origin is the plotter origin (paper corner)"},
        "dictionary": "DICT_4X4_50",
        "marker_corner_order": "TL, TR, BR, BL (as printed, matches cv2.aruco.detectMarkers)",
        "markers": markers,
        "square": {"lower_left_mm": [SQ_X, SQ_Y], "size_mm": SQ, "corners_mm": sq,
                   "center_mm": list(CENTER), "corner_order": "BL, BR, TR, TL"},
        "crosshair": {"center_mm": list(CENTER), "arm_mm": ARM},
        "x_ruler": {"x0_mm": XR_X0, "x1_mm": XR_X1, "y_mm": XR_Y, "length_mm": XR_X1 - XR_X0},
        "y_ruler": {"x_mm": YR_X, "y0_mm": YR_Y0, "y1_mm": YR_Y1, "length_mm": YR_Y1 - YR_Y0},
    }
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


if __name__ == "__main__":
    print(verify_with_cv2())
    build_pdf()
    build_json()
    print("wrote", PDF_PATH)
    print("wrote", JSON_PATH)
