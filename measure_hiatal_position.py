"""
measure_hiatal_position.py — Measure position of suture points along the hiatal long axis.

On a reference frame showing the full open hiatal opening:
  Step 1: Click the apex (posterior crural junction) — defines position = 0
  Step 2: Click a second point to define the midpoint line (long axis direction)
  Step 3: For each point A–D, click left crus then right crus entry position
          The line through each pair intersects the midpoint line;
          the distance from apex to that intersection = position of that measurement.

Results saved to:
    Videos/<case_id>/force_data/<case_id>_hiatal_positions.json
    Videos/<case_id>/force_data/<case_id>_hiatal_positions.xlsx

Usage:
    python3 measure_hiatal_position.py <image> <case_id>

Example:
    python3 measure_hiatal_position.py Videos/<case_id>/calibration_frame.png <case_id>

The plot window uses matplotlib's default interactive backend for your platform. Set the
MPLBACKEND environment variable (for example TkAgg or QtAgg) to choose another.
"""

import argparse
import sys
import json
import numpy as np
import cv2
import matplotlib.pyplot as plt
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill

import framelib

BASE     = Path(__file__).resolve().parent

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("image", help="reference frame showing the full open hiatal opening")
ap.add_argument("case_id")
ap.add_argument("--version", action="version", version=f"%(prog)s {framelib.PIPELINE_VERSION}")
_args = ap.parse_args()
img_path = _args.image
case_id  = _args.case_id

img_bgr = cv2.imread(str(BASE / img_path))
if img_bgr is None:
    sys.exit(f"ERROR: cannot read the image: {img_path}")

# Load calibration (px/mm from base calibration)
cal_path = BASE / "Videos" / case_id / "force_data" / f"{case_id}_calibration.json"
if not cal_path.exists():
    print(f"ERROR: Calibration file not found: {cal_path}")
    sys.exit(1)
with open(cal_path) as f:
    cal = json.load(f)
px_per_mm = cal.get("px_per_mm") or cal.get("px_per_mm_ruler")
print(f"Loaded calibration: {px_per_mm:.2f} px/mm")

img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
H, W    = img_rgb.shape[:2]

POINTS  = ["A", "B", "C", "D"]
COLORS  = {"apex": "#FF0000", "midline": "#FFFF00",
           "A": "#00FF88", "B": "#FF6600", "C": "#00BFFF", "D": "#FF00FF"}

state = {
    "phase":    "apex",       # apex → midline → A → B → C → D → done
    "apex":     None,
    "midline":  None,         # second point defining midline direction
    "pairs":    {},           # point_label -> {left, right}
    "results":  {},           # point_label -> {left_px, right_px, intersection_px, position_mm}
    "clicks":   [],           # temp clicks for current suture pair
}

fig = plt.figure(figsize=(13, 10))
ax  = fig.add_axes([0, 0, 1, 1])
ax.axis("off")
ax.imshow(img_rgb)

title_text = ax.set_title("", fontsize=12, color="white",
                           bbox=dict(boxstyle="round", facecolor="#333333", alpha=0.85))
info_text  = ax.text(10, H - 10, "", fontsize=11, color="white", va="bottom",
                     bbox=dict(facecolor="black", alpha=0.6))


def phase_instructions():
    p = state["phase"]
    if p == "apex":
        return "Step 1: Click the APEX (posterior crural junction)"
    if p == "midline":
        return "Step 2: Click a second point to define the MIDPOINT LINE direction"
    if p in POINTS:
        n = len(state["clicks"])
        side = "LEFT" if n == 0 else "RIGHT"
        return f"Point {p}  ({n+1}/2): Click {side} crus position on this frame"
    return "Done — close window to save"


def line_intersection(p1, p2, p3, p4):
    """Intersection of line p1-p2 and line p3-p4. Returns (point, t) where t is
    parameter along p1-p2 from p1."""
    d1 = np.array(p2) - np.array(p1)
    d2 = np.array(p4) - np.array(p3)
    # p1 + t*d1 = p3 + s*d2  =>  [d1 | -d2] [t; s] = p3 - p1
    A = np.array([[d1[0], -d2[0]],
                  [d1[1], -d2[1]]])
    b = np.array(p3) - np.array(p1)
    if abs(np.linalg.det(A)) < 1e-10:
        return None, None  # parallel
    ts = np.linalg.solve(A, b)
    t = ts[0]
    pt = np.array(p1) + t * d1
    return pt, t


def redraw():
    ax.cla()
    ax.axis("off")
    ax.imshow(img_rgb)

    # Draw midline
    if state["apex"] and state["midline"]:
        ap = state["apex"]
        ml = state["midline"]
        # Extend midline across full image
        d  = np.array(ml) - np.array(ap)
        if np.linalg.norm(d) > 0:
            d_norm = d / np.linalg.norm(d)
            far1   = np.array(ap) - d_norm * 2000
            far2   = np.array(ap) + d_norm * 2000
            ax.plot([far1[0], far2[0]], [far1[1], far2[1]],
                    "--", color=COLORS["midline"], linewidth=1.5, alpha=0.8)

    # Draw apex
    if state["apex"]:
        ax.plot(*state["apex"], "+", color=COLORS["apex"],
                markersize=18, markeredgewidth=2.5)
        ax.annotate("Apex", state["apex"], textcoords="offset points",
                    xytext=(6, 6), fontsize=9, color=COLORS["apex"])

    # Draw completed pairs and intersections
    for label, r in state["results"].items():
        color = COLORS[label]
        lp, rp = r["left_px"], r["right_px"]
        ix, iy = r["intersection_px"]
        ax.plot(lp[0], lp[1], "+", color=color, markersize=14, markeredgewidth=2)
        ax.plot(rp[0], rp[1], "+", color=color, markersize=14, markeredgewidth=2)
        ax.plot([lp[0], rp[0]], [lp[1], rp[1]], "-", color=color,
                linewidth=1.2, alpha=0.7)
        ax.plot(ix, iy, "o", color=color, markersize=8, zorder=5)
        ax.annotate(f"  {label}: {r['position_mm']:.1f} mm",
                    (ix, iy), fontsize=9, color=color,
                    bbox=dict(facecolor="black", alpha=0.5))
        # Line from apex to intersection
        if state["apex"]:
            ax.plot([state["apex"][0], ix], [state["apex"][1], iy],
                    ":", color=color, linewidth=1, alpha=0.6)

    # Draw in-progress clicks for current pair
    for i, pt in enumerate(state["clicks"]):
        label = state["phase"]
        color = COLORS.get(label, "white")
        ax.plot(pt[0], pt[1], "+", color=color, markersize=14, markeredgewidth=2)

    ax.set_title(phase_instructions(), fontsize=12, color="white",
                 bbox=dict(boxstyle="round", facecolor="#1a5276", alpha=0.85))

    # Lock view to image bounds
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)

    # Persistent instructions panel (bottom-left)
    steps = [
        "Step 1: Click APEX (posterior crural junction)  [red +]",
        "Step 2: Click second point to define MIDPOINT LINE  [yellow dashed]",
        "Step 3–6: For each point A → B → C → D:",
        "         Click LEFT crus, then RIGHT crus",
        "",
        "BACKSPACE = undo last click",
    ]
    done  = {"apex": 0, "midline": 1}.get(state["phase"], 2)
    panel = "\n".join(steps)
    ax.text(10, 10, panel, fontsize=9, color="white", va="top",
            bbox=dict(facecolor="black", alpha=0.65),
            fontfamily="monospace")

    fig.canvas.draw()


def onclick(event):
    if event.xdata is None or event.ydata is None:
        return
    x, y = int(event.xdata), int(event.ydata)
    p = state["phase"]

    if p == "apex":
        state["apex"] = (x, y)
        state["phase"] = "midline"
        redraw()

    elif p == "midline":
        state["midline"] = (x, y)
        state["phase"] = POINTS[0]
        redraw()

    elif p in POINTS:
        state["clicks"].append((x, y))
        redraw()

        if len(state["clicks"]) == 2:
            left, right = state["clicks"]
            apex    = state["apex"]
            midline = state["midline"]

            # Extend midline in both directions for intersection
            ml_far1 = (apex[0] - 5000 * (midline[0] - apex[0]),
                       apex[1] - 5000 * (midline[1] - apex[1]))
            ml_far2 = (apex[0] + 5000 * (midline[0] - apex[0]),
                       apex[1] + 5000 * (midline[1] - apex[1]))

            inter_pt, t = line_intersection(apex, midline, left, right)

            if inter_pt is None:
                print(f"  Point {p}: suture line is parallel to midline — cannot compute position")
                state["clicks"] = []
                return

            pos_px = np.linalg.norm(inter_pt - np.array(apex))
            pos_mm = pos_px / px_per_mm

            state["results"][p] = {
                "left_px":         list(left),
                "right_px":        list(right),
                "intersection_px": [round(inter_pt[0], 1), round(inter_pt[1], 1)],
                "position_px":     round(pos_px, 2),
                "position_mm":     round(pos_mm, 3),
            }
            print(f"  Point {p}: intersection at ({inter_pt[0]:.0f}, {inter_pt[1]:.0f})  "
                  f"→ {pos_px:.1f} px = {pos_mm:.2f} mm from apex")

            state["clicks"] = []
            idx = POINTS.index(p)
            state["phase"] = POINTS[idx + 1] if idx + 1 < len(POINTS) else "done"

            redraw()

            if state["phase"] == "done":
                ax.set_title("Done — all points marked. Close window to save.",
                             fontsize=13, color="white",
                             bbox=dict(boxstyle="round", facecolor="#1e8449", alpha=0.8))
                fig.canvas.draw()
                save_results()


def onkey(event):
    if event.key == "backspace" and state["phase"] in POINTS:
        if state["clicks"]:
            state["clicks"].pop()
            redraw()


def save_results():
    out_dir  = BASE / "Videos" / case_id / "force_data"
    out_json = out_dir / f"{case_id}_hiatal_positions.json"
    out_xlsx = out_dir / f"{case_id}_hiatal_positions.xlsx"

    data = {
        "case":       case_id,
        "px_per_mm":  px_per_mm,
        "apex_px":    list(state["apex"]),
        "midline_px": list(state["midline"]),
        "points":     state["results"],
    }
    with open(out_json, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved JSON: {out_json}")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Hiatal Positions"
    bold = Font(bold=True)
    gold = PatternFill(start_color="FFFFD700", end_color="FFFFD700", fill_type="solid")

    headers = ["Point", "Position (mm)", "Position (px)", "Left crus (px)",
               "Right crus (px)", "Intersection (px)", "px/mm"]
    for c, h in enumerate(headers, 1):
        ws.cell(row=1, column=c, value=h).font = bold

    for i, label in enumerate(POINTS):
        if label not in state["results"]:
            continue
        r = state["results"][label]
        row = [label, r["position_mm"], r["position_px"],
               str(r["left_px"]), str(r["right_px"]),
               str(r["intersection_px"]), px_per_mm]
        for c, v in enumerate(row, 1):
            cell = ws.cell(row=i + 2, column=c, value=v)
            cell.fill = gold

    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 14
    for col in ["D", "E", "F"]:
        ws.column_dimensions[col].width = 18
    ws.column_dimensions["G"].width = 10

    wb.save(out_xlsx)
    print(f"Saved Excel: {out_xlsx}")


fig.canvas.mpl_connect("button_press_event", onclick)
fig.canvas.mpl_connect("key_press_event", onkey)
plt.get_current_fig_manager().full_screen_toggle()
redraw()
plt.show()
