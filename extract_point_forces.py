"""
extract_point_forces.py — Extract force data for points A-D from the patient Excel sheet.

For each point, pulls force readings from all active arms within the time window,
plus a configurable buffer before and after. Saves one Excel file per case with
one sheet per point.
"""

import json
import openpyxl
from openpyxl.styles import PatternFill, Font
from pathlib import Path
import sys

# How many seconds before/after each window to include
BUFFER_SECS = 5

BASE = Path(__file__).resolve().parent
PATIENT_FILE = BASE / "Hiatal tension patients.xlsx"


def ts_to_secs(ts):
    """Convert HH:MM:SS.mmm string to float seconds."""
    if not ts:
        return None
    parts = str(ts).split(":")
    h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


def secs_to_ts(secs):
    """Convert float seconds to HH:MM:SS.mmm string."""
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = secs % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def load_force_arm(json_path, arm):
    """Return list of (x_secs, y_force) for a given arm."""
    with open(json_path) as f:
        data = json.load(f)
    arm_data = data.get(arm, [])
    return [(pt["x"], pt["y"]) for pt in arm_data if pt.get("y") is not None]


def extract_window(arm_data, start_secs, end_secs, buffer=BUFFER_SECS):
    """Return points within [start-buffer, end+buffer]."""
    lo = start_secs - buffer
    hi = end_secs + buffer
    return [(x, y) for x, y in arm_data if lo <= x <= hi]


def main():
    # Load patient sheet
    wb_in = openpyxl.load_workbook(PATIENT_FILE)
    ws = wb_in.active

    headers = [cell.value for cell in ws[1]]
    col = {h: i for i, h in enumerate(headers)}

    for row in ws.iter_rows(min_row=2, values_only=True):
        case = row[col["Study ID"]]
        if not case or not str(case).startswith("YV"):
            continue

        # Check if any points are defined
        points = {}
        for pt in ["A", "B", "C", "D"]:
            start = row[col[f"Point {pt} start"]]
            end   = row[col[f"Point {pt} end"]]
            if start and end:
                points[pt] = (ts_to_secs(str(start)), ts_to_secs(str(end)))

        if not points:
            print(f"{case}: no points defined, skipping")
            continue

        json_path = BASE / "Videos" / case / "force_data" / f"{case}_force_raw.json"
        if not json_path.exists():
            print(f"{case}: force JSON not found, skipping")
            continue

        # Determine active arms
        with open(json_path) as f:
            raw = json.load(f)
        arms = [arm for arm in ["USM1", "USM2", "USM3", "USM4"]
                if arm in raw and len(raw[arm]) > 0]

        print(f"\n{case}: points {list(points.keys())}, arms {arms}")

        # Load force data per arm
        arm_data = {arm: load_force_arm(json_path, arm) for arm in arms}

        # Build output workbook
        wb_out = openpyxl.Workbook()
        wb_out.remove(wb_out.active)  # remove default sheet

        highlight = PatternFill(start_color="FFFFD700", end_color="FFFFD700", fill_type="solid")
        bold = Font(bold=True)

        for pt_name, (start_s, end_s) in points.items():
            ws_out = wb_out.create_sheet(title=f"Point {pt_name}")

            # Header row
            header = ["Timestamp", "Seconds"] + arms + ["In Window"]
            for c, h in enumerate(header, 1):
                cell = ws_out.cell(row=1, column=c, value=h)
                cell.font = bold

            # Collect all unique x values across arms in the window
            all_x = set()
            for arm in arms:
                for x, y in extract_window(arm_data[arm], start_s, end_s):
                    all_x.add(x)
            all_x = sorted(all_x)

            # Build lookup dicts
            arm_lookup = {}
            for arm in arms:
                arm_lookup[arm] = {x: y for x, y in arm_data[arm]}

            # Write rows
            for r, x in enumerate(all_x, 2):
                in_window = start_s <= x <= end_s
                ws_out.cell(row=r, column=1, value=secs_to_ts(x))
                ws_out.cell(row=r, column=2, value=round(x, 3))
                for c, arm in enumerate(arms, 3):
                    ws_out.cell(row=r, column=c, value=arm_lookup[arm].get(x))
                ws_out.cell(row=r, column=len(arms) + 3, value="YES" if in_window else "")

                # Highlight rows within the window
                if in_window:
                    for c in range(1, len(arms) + 4):
                        ws_out.cell(row=r, column=c).fill = highlight

            # Column widths
            ws_out.column_dimensions["A"].width = 16
            for i in range(2, len(arms) + 4):
                ws_out.column_dimensions[chr(64 + i)].width = 12

            print(f"  Point {pt_name}: {start_s:.1f}s–{end_s:.1f}s → {len(all_x)} rows")

        out_path = BASE / "Videos" / case / "force_data" / f"{case}_points_ABCD_force.xlsx"
        wb_out.save(out_path)
        print(f"  Saved: {out_path}")


if __name__ == "__main__":
    main()
