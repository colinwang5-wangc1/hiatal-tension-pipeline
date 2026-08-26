"""
merge_distance_force.py — Merge crural distance measurements into the force Excel
and compute a Total Force column, ready for fit_moduli.py.

Reads:
    Videos/<case_id>/force_data/<case_id>_points_ABCD_force.xlsx  (from extract_point_forces.py)
    Videos/<case_id>/force_data/<case_id>_suture_entry.xlsx       (from mark_suture_entry.py)

For each "Point <X>" sheet:
    - Adds "Total Force (N)" = sum of the active-arm columns for every row
      (missing arm readings treated as 0)
    - Adds "Distance (mm)" / "Distance (px)", filled in only for rows whose
      "Seconds" value matches a marked "Abs seconds" entry in the corresponding
      sheet of <case_id>_suture_entry.xlsx (i.e. rows that were actually marked)

Writes the result back to <case_id>_points_ABCD_force.xlsx in place.

Usage:
    python3 merge_distance_force.py [case_id]     (default YV003)
"""

import sys
import openpyxl
from pathlib import Path

BASE = Path(__file__).resolve().parent
case_id = sys.argv[1] if len(sys.argv) > 1 else "YV003"

POINTS = ["A", "B", "C", "D"]


def load_distances(suture_path):
    """Return {point_label: {abs_seconds: (distance_mm, distance_px)}}."""
    if not suture_path.exists():
        print(f"WARNING: {suture_path.name} not found — Distance columns will be left blank")
        return {}

    wb = openpyxl.load_workbook(suture_path)
    out = {}
    for label in POINTS:
        if label not in wb.sheetnames:
            continue
        ws = wb[label]
        headers = [c.value for c in ws[1]]
        col = {h: i for i, h in enumerate(headers)}
        lookup = {}
        for row in ws.iter_rows(min_row=2, values_only=True):
            abs_sec = row[col["Abs seconds"]]
            if abs_sec is None:
                continue
            lookup[round(float(abs_sec), 3)] = (
                row[col["Distance (mm)"]],
                row[col["Distance (px)"]],
            )
        out[label] = lookup
    return out


def main():
    force_path = BASE / "Videos" / case_id / "force_data" / f"{case_id}_points_ABCD_force.xlsx"
    suture_path = BASE / "Videos" / case_id / "force_data" / f"{case_id}_suture_entry.xlsx"

    if not force_path.exists():
        print(f"ERROR: {force_path} not found — run extract_point_forces.py first")
        sys.exit(1)

    distances = load_distances(suture_path)

    wb = openpyxl.load_workbook(force_path)

    for label in POINTS:
        sheet_name = f"Point {label}"
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        headers = [c.value for c in ws[1]]
        col = {h: i for i, h in enumerate(headers)}

        # Arm columns are everything between "In Window" and the end of the
        # original header row (before we append new columns below)
        arm_cols = [h for h in headers if h not in ("Timestamp", "Seconds", "In Window")]

        # Append new headers if not already present
        new_headers = ["Distance (mm)", "Distance (px)", "Total Force (N)"]
        for h in new_headers:
            if h not in col:
                c = ws.max_column + 1
                ws.cell(row=1, column=c, value=h)
                col[h] = c - 1

        lookup = distances.get(label, {})
        n_matched = 0
        for row in ws.iter_rows(min_row=2):
            secs = row[col["Seconds"]].value
            total = sum(
                (row[col[arm]].value or 0) for arm in arm_cols
            )
            row[col["Total Force (N)"]].value = total

            dist = lookup.get(round(float(secs), 3)) if secs is not None else None
            if dist is not None:
                row[col["Distance (mm)"]].value = dist[0]
                row[col["Distance (px)"]].value = dist[1]
                n_matched += 1

        print(f"  {sheet_name}: Total Force computed for all rows, "
              f"Distance matched for {n_matched} rows")

    wb.save(force_path)
    print(f"Saved: {force_path}")


if __name__ == "__main__":
    main()
