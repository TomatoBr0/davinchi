"""Measure the pen-drawn calibration square from a phone photo of the sheet.

Usage:
  python tools/calibrate_from_photo.py photo.jpg [--xmm CUR_X --ymm CUR_Y] [--dark 110]

Needs OpenCV with the aruco module: pip install opencv-contrib-python
Expects all four DICT_4X4_50 markers (ids 0-3) to be visible in the photo.
"""
import argparse
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SHEET = os.path.join(ROOT, "docs", "calibration", "calibration_sheet.json")
EXPECTED_CENTER = (108.0, 140.0)  # sheet mm, square centre
EXPECTED_SIZE = 100.0
ROI = (50.0, 70.0, 170.0, 200.0)  # sheet mm window that gets rectified


def order_quad(pts):
    """Return TL, TR, BR, BL for an image-style (y down) quad."""
    import numpy as np
    p = np.asarray(pts, float)
    s = p.sum(1)
    d = p[:, 1] - p[:, 0]
    return np.array([p[np.argmin(s)], p[np.argmin(d)], p[np.argmax(s)], p[np.argmax(d)]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("--sheet", default=DEFAULT_SHEET)
    ap.add_argument("--xmm", type=float, help="current X steps/mm, for the suggested value")
    ap.add_argument("--ymm", type=float, help="current Y steps/mm, for the suggested value")
    ap.add_argument("--dark", type=int, default=110, help="grey level below which pen ink counts")
    ap.add_argument("--px-per-mm", type=float, default=5.0)
    args = ap.parse_args()

    try:
        import cv2
        import numpy as np
    except ImportError:
        print("OpenCV is not installed. Install it with: pip install opencv-contrib-python")
        return 1
    if not hasattr(cv2, "aruco"):
        print("cv2.aruco is missing. Install: pip install opencv-contrib-python")
        return 1

    with open(args.sheet, encoding="utf-8") as f:
        sheet = json.load(f)
    img = cv2.imread(args.photo)
    if img is None:
        print(f"cannot read {args.photo}")
        return 1
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 1. Markers -> homography from photo pixels to sheet mm
    dic = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    if hasattr(cv2.aruco, "ArucoDetector"):
        corners, ids, _ = cv2.aruco.ArucoDetector(dic, cv2.aruco.DetectorParameters()).detectMarkers(gray)
    else:
        corners, ids, _ = cv2.aruco.detectMarkers(gray, dic)
    found = {} if ids is None else {int(i): c.reshape(4, 2) for c, i in zip(corners, ids.flatten())}
    if not all(m["id"] in found for m in sheet["markers"]):
        print(f"found markers {sorted(found)}; need all of {[m['id'] for m in sheet['markers']]}")
        return 1
    src, dst = [], []
    for m in sheet["markers"]:
        src += found[m["id"]].tolist()
        dst += m["corners_mm"]
    H, _ = cv2.findHomography(np.float32(src), np.float32(dst), cv2.RANSAC, 1.0)

    # 2. Rectify the square window into sheet mm (5 px per mm by default)
    s = args.px_per_mm
    x0, y0, x1, y1 = ROI
    T = np.array([[s, 0, -x0 * s], [0, -s, y1 * s], [0, 0, 1]])
    rect = cv2.warpPerspective(gray, T @ H, (int((x1 - x0) * s), int((y1 - y0) * s)))

    def to_mm(pts):
        return [[px / s + x0, y1 - py / s] for px, py in pts]

    # 3. Largest dark quadrilateral near the expected centre (pen ring)
    mask = ((rect < args.dark) * 255).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnts, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    hier = hier[0]
    best = None
    for i, c in enumerate(cnts):
        if hier[i][3] != -1:
            continue  # only outer boundaries
        approx = cv2.approxPolyDP(c, 0.03 * cv2.arcLength(c, True), True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        area_mm2 = cv2.contourArea(approx) / (s * s)
        if not (0.3 * EXPECTED_SIZE ** 2 <= area_mm2 <= 1.7 * EXPECTED_SIZE ** 2):
            continue
        bx, by, bw, bh = cv2.boundingRect(approx)
        mx, my = to_mm([[bx + bw / 2, by + bh / 2]])[0]
        if math.dist((mx, my), EXPECTED_CENTER) > 15:
            continue
        if best is None or area_mm2 > best[0]:
            best = (area_mm2, approx.reshape(4, 2), i)
    if best is None:
        print("no drawn square found near the expected spot; check lighting, focus and --dark")
        return 1
    _, outer_pts, idx = best

    # Pen centreline: average outer and inner (hole) boundary when present
    outer = order_quad(outer_pts)
    centre_pts = outer
    child = hier[idx][2]
    inner_note = "outer edge only"
    if child != -1:
        inner_best = None
        while child != -1:
            a = cv2.contourArea(cnts[child])
            if inner_best is None or a > inner_best[0]:
                inner_best = (a, cnts[child])
            child = hier[child][0]
        ap4 = cv2.approxPolyDP(inner_best[1], 0.03 * cv2.arcLength(inner_best[1], True), True)
        if len(ap4) == 4:
            centre_pts = (outer + order_quad(ap4.reshape(4, 2))) / 2.0
            inner_note = "pen centreline (outer+inner)/2"
    TL, TR, BR, BL = to_mm(centre_pts)

    # 4. Measurements
    top, bot = math.dist(TL, TR), math.dist(BL, BR)
    left, right = math.dist(TL, BL), math.dist(TR, BR)
    meas_x, meas_y = (top + bot) / 2, (left + right) / 2
    ux, uy = (TR[0] - TL[0], TR[1] - TL[1])
    vx, vy = (BL[0] - TL[0], BL[1] - TL[1])
    angle = math.degrees(math.acos(max(-1, min(1, (ux * vx + uy * vy) / (math.hypot(ux, uy) * math.hypot(vx, vy))))))
    skew = angle - 90.0
    rot = math.degrees(math.atan2(uy, ux))
    cx = sum(p[0] for p in (TL, TR, BR, BL)) / 4
    cy = sum(p[1] for p in (TL, TR, BR, BL)) / 4
    ox, oy = cx - EXPECTED_CENTER[0], cy - EXPECTED_CENTER[1]
    fx, fy = EXPECTED_SIZE / meas_x, EXPECTED_SIZE / meas_y

    print(f"drawn square ({inner_note}), sheet mm:")
    print(f"  TL {TL[0]:.2f},{TL[1]:.2f}  TR {TR[0]:.2f},{TR[1]:.2f}  "
          f"BR {BR[0]:.2f},{BR[1]:.2f}  BL {BL[0]:.2f},{BL[1]:.2f}")
    print(f"measured X size: {meas_x:.2f} mm (top {top:.2f}, bottom {bot:.2f}), expected {EXPECTED_SIZE:.1f}")
    print(f"measured Y size: {meas_y:.2f} mm (left {left:.2f}, right {right:.2f}), expected {EXPECTED_SIZE:.1f}")
    print(f"skew (non-perpendicularity): {skew:+.2f} deg, rotation vs sheet: {rot:+.2f} deg")
    print(f"centre offset: dX {ox:+.2f} mm, dY {oy:+.2f} mm")
    print(f"X factor expected/measured: {fx:.4f}   Y factor: {fy:.4f}")
    if args.xmm:
        print(f"suggested $XMM = {args.xmm * fx:.3f}  (was {args.xmm})")
    if args.ymm:
        print(f"suggested $YMM = {args.ymm * fy:.3f}  (was {args.ymm})")
    if not args.xmm and not args.ymm:
        print("pass --xmm/--ymm with the current steps/mm to get the new values")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
