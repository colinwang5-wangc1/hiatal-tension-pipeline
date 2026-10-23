"""
calibrate_reference.py — Establish pixel/mm calibration using anatomical landmarks.

Two modes:

  FULL MODE (calibration frame with ruler):
    Step 1: Click two ruler tick marks → type known mm → get px/mm
    Step 2: Click two blood vessel landmarks → records distance in mm (ground truth)
    Usage: python3 calibrate_reference.py <image> <case_id>

  LANDMARK-ONLY MODE (a still from each point A-D, no ruler):
    Just click the two blood vessels. Uses the known landmark_mm from
    <case_id>_calibration.json to compute px/mm for this frame's depth.
    Usage: python3 calibrate_reference.py <image> <case_id> <point>

Examples:
    python3 calibrate_reference.py Videos/<case_id>/calibration_frame.png <case_id>
    python3 calibrate_reference.py Videos/<case_id>/point_A_still.png <case_id> A
    python3 calibrate_reference.py Videos/<case_id>/point_B_still.tiff <case_id> B

The plot window uses matplotlib's default interactive backend for your platform. Set the
MPLBACKEND environment variable (for example TkAgg or QtAgg) to choose another.
"""

import sys
import json
import numpy as np
import cv2
import matplotlib.pyplot as plt
from matplotlib.widgets import TextBox
from pathlib import Path
import openpyxl

BASE         = Path(__file__).resolve().parent
PATIENT_FILE = BASE / "Hiatal tension patients.xlsx"

if "--version" in sys.argv[1:]:
    import framelib
    print(f"{Path(__file__).name} {framelib.PIPELINE_VERSION}")
    sys.exit(0)
if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

img_path   = sys.argv[1]
case_id    = sys.argv[2]
clip_label = sys.argv[3] if len(sys.argv) > 3 else None

# Landmark-only mode if clip_label is provided
LANDMARK_ONLY = clip_label is not None

# Load known landmark_mm from base calibration JSON if in landmark-only mode
known_landmark_mm = None
if LANDMARK_ONLY:
    base_cal_path = BASE / "Videos" / case_id / "force_data" / f"{case_id}_calibration.json"
    if base_cal_path.exists():
        with open(base_cal_path) as f:
            base_cal = json.load(f)
        known_landmark_mm = base_cal["landmark_mm"]
        print(f"Loaded reference: landmark_mm = {known_landmark_mm} mm from {base_cal_path.name}")
    else:
        print(f"ERROR: Base calibration file not found: {base_cal_path}")
        sys.exit(1)

img_bgr = cv2.imread(img_path)
img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

state = {
    "phase": "landmark" if LANDMARK_ONLY else "ruler",
    "ruler_clicks": [],
    "landmark_clicks": [],
    "px_per_mm": None,
    "ruler_mm": None,
    "ruler_px_dist": None,
}

fig = plt.figure(figsize=(13, 10))
ax = fig.add_axes([0, 0.08, 1, 0.92])
ax_box = fig.add_axes([0.3, 0.01, 0.2, 0.05])
textbox = TextBox(ax_box, "Ruler mm: ", initial="")
ax_box.set_visible(False)

ax.imshow(img_rgb)
ax.axis("off")

info_text = ax.text(10, img_rgb.shape[0] - 10, "", fontsize=11, color="white",
                    va="bottom", bbox=dict(facecolor="black", alpha=0.6))

if LANDMARK_ONLY:
    ax.set_title(
        f"Click TWO blood vessel landmarks  |  reference = {known_landmark_mm} mm",
        fontsize=13, color="white",
        bbox=dict(boxstyle="round", facecolor="#1a5276", alpha=0.8))
else:
    ax.set_title("STEP 1: Click TWO ruler tick marks of known distance",
                 fontsize=13, color="white",
                 bbox=dict(boxstyle="round", facecolor="#333333", alpha=0.8))


def update_info():
    phase = state["phase"]
    px_mm = state["px_per_mm"]
    if phase == "ruler":
        n = len(state["ruler_clicks"])
        msg = f"Ruler clicks: {n}/2  — click two tick marks"
    elif phase == "ruler_input":
        msg = "Type the mm distance between the tick marks in the box below, then press Enter"
    elif phase == "landmark":
        n = len(state["landmark_clicks"])
        if px_mm:
            msg = f"px/mm = {px_mm:.2f}  |  Landmark clicks: {n}/2  — click two blood vessels"
        else:
            msg = f"Landmark clicks: {n}/2  — click two blood vessels"
    elif phase == "done":
        msg = "Done — close window to save"
    else:
        msg = ""
    info_text.set_text(msg)
    fig.canvas.draw()


def onclick(event):
    if event.inaxes != ax:
        return
    x, y = int(event.xdata), int(event.ydata)
    phase = state["phase"]

    if phase == "ruler":
        state["ruler_clicks"].append((x, y))
        ax.plot(x, y, "+", color="yellow", markersize=12, markeredgewidth=1.5)
        fig.canvas.draw()

        if len(state["ruler_clicks"]) == 2:
            p1, p2 = state["ruler_clicks"]
            ax.plot([p1[0], p2[0]], [p1[1], p2[1]], "-", color="yellow", linewidth=1.5)
            px_dist = np.sqrt((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2)
            state["ruler_px_dist"] = px_dist
            state["phase"] = "ruler_input"
            ax_box.set_visible(True)
            textbox.set_val("")
            update_info()
            fig.canvas.draw()

    elif phase == "landmark":
        state["landmark_clicks"].append((x, y))
        ax.plot(x, y, "+", color="cyan", markersize=12, markeredgewidth=1.5)
        fig.canvas.draw()

        if len(state["landmark_clicks"]) == 2:
            p1, p2 = state["landmark_clicks"]
            ax.plot([p1[0], p2[0]], [p1[1], p2[1]], "-", color="cyan", linewidth=1.5)
            px_dist = np.sqrt((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2)

            if LANDMARK_ONLY:
                # Use known mm from base calibration to derive px/mm
                mm_dist = known_landmark_mm
                state["px_per_mm"] = px_dist / known_landmark_mm
            else:
                mm_dist = px_dist / state["px_per_mm"]

            mid_x = (p1[0] + p2[0]) / 2
            mid_y = (p1[1] + p2[1]) / 2 - 15
            ax.annotate(f"Landmark: {px_dist:.0f} px = {mm_dist:.2f} mm\n→ {state['px_per_mm']:.2f} px/mm",
                        (mid_x, mid_y), color="cyan", fontsize=9,
                        ha="center", bbox=dict(facecolor="black", alpha=0.6))

            print(f"\nLandmark distance: {px_dist:.1f} px = {mm_dist:.2f} mm")
            print(f"Calibration: {state['px_per_mm']:.2f} px/mm  |  {1/state['px_per_mm']:.4f} mm/px")

            save_results(px_dist, mm_dist)
            state["phase"] = "done"
            ax.set_title(
                f"Done — {px_dist:.0f} px = {mm_dist:.2f} mm  |  {state['px_per_mm']:.2f} px/mm",
                fontsize=13, color="white",
                bbox=dict(boxstyle="round", facecolor="#1e8449", alpha=0.8))
            update_info()


def save_results(landmark_px, landmark_mm):
    px_per_mm = state["px_per_mm"]

    cal = {
        "case": case_id,
        "clip": clip_label if clip_label else "calibration",
        "calibration_frame": img_path,
        "mode": "landmark_only" if LANDMARK_ONLY else "ruler",
        "px_per_mm": round(px_per_mm, 4),
        "mm_per_px": round(1 / px_per_mm, 6),
        "landmark_px": round(landmark_px, 2),
        "landmark_mm": round(landmark_mm, 4),
        "landmark_coords_p1": state["landmark_clicks"][0],
        "landmark_coords_p2": state["landmark_clicks"][1],
    }
    if not LANDMARK_ONLY:
        cal["ruler_mm"] = state["ruler_mm"]
        cal["ruler_coords_p1"] = state["ruler_clicks"][0]
        cal["ruler_coords_p2"] = state["ruler_clicks"][1]

    suffix = f"_{clip_label}" if clip_label else ""
    out_json = BASE / "Videos" / case_id / "force_data" / f"{case_id}{suffix}_calibration.json"
    with open(out_json, "w") as f:
        json.dump(cal, f, indent=2)
    print(f"Saved: {out_json}")

    # Update patient Excel only for base calibration (not per-clip)
    if not LANDMARK_ONLY:
        wb = openpyxl.load_workbook(PATIENT_FILE)
        ws = wb.active
        headers = [cell.value for cell in ws[1]]

        def get_or_add_col(name):
            if name in headers:
                return headers.index(name) + 1
            col = len(headers) + 1
            ws.cell(row=1, column=col, value=name)
            headers.append(name)
            return col

        col_pxmm     = get_or_add_col("px_per_mm_ruler")
        col_mmpx     = get_or_add_col("mm_per_px_ruler")
        col_lmk_px   = get_or_add_col("landmark_px")
        col_lmk_mm   = get_or_add_col("landmark_mm")
        col_ruler_mm = get_or_add_col("ruler_distance_mm")

        for row in ws.iter_rows(min_row=2):
            if row[0].value == case_id:
                row[col_pxmm - 1].value     = round(px_per_mm, 4)
                row[col_mmpx - 1].value     = round(1 / px_per_mm, 6)
                row[col_lmk_px - 1].value   = round(landmark_px, 2)
                row[col_lmk_mm - 1].value   = round(landmark_mm, 4)
                row[col_ruler_mm - 1].value = state["ruler_mm"]
                break

        wb.save(PATIENT_FILE)
        print(f"Updated patient Excel")


def on_ruler_submit(text):
    if state["phase"] != "ruler_input":
        return
    try:
        mm = float(text)
    except ValueError:
        return
    px_dist = state["ruler_px_dist"]
    p1, p2  = state["ruler_clicks"]
    state["ruler_mm"]  = mm
    state["px_per_mm"] = px_dist / mm
    ax_box.set_visible(False)

    mid_x = (p1[0] + p2[0]) / 2
    mid_y = (p1[1] + p2[1]) / 2 - 15
    ax.annotate(f"{mm:.1f} mm = {px_dist:.0f} px\n→ {px_dist/mm:.2f} px/mm",
                (mid_x, mid_y), color="yellow", fontsize=9,
                ha="center", bbox=dict(facecolor="black", alpha=0.6))

    ax.set_title("STEP 2: Click TWO anatomical landmarks (blood vessels on the crus)",
                 fontsize=13, color="white",
                 bbox=dict(boxstyle="round", facecolor="#1a5276", alpha=0.8))
    state["phase"] = "landmark"
    update_info()


textbox.on_submit(on_ruler_submit)
fig.canvas.mpl_connect("button_press_event", onclick)
update_info()
plt.get_current_fig_manager().full_screen_toggle()
plt.show()
