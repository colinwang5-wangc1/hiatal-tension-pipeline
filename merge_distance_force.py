"""
merge_distance_force.py — Merge the per-frame crural distance measurements into the
force workbook, summarise them per force sample, and compute a Total Force column,
ready for fit_moduli.py.

Reads (never modified):
    Videos/<case_id>/force_data/<case_id>_points_ABCD_force.xlsx  (from extract_point_forces.py)
    Videos/<case_id>/force_data/<case_id>_frame_marks.json        (from mark_suture_entry.py)
    Videos/<case_id>/force_data/<case_id>_frame_times.csv         (frame timestamps, from index_video.py)

Writes (new files):
    Videos/<case_id>/force_data/<case_id>_points_ABCD_force_merged.xlsx
    Videos/<case_id>/force_data/<case_id>_frame_distances.csv     every planned frame, one row per
                                                                  (point, force second, frame)

For each "Point <X>" sheet, every force row gets:
    Total Force (N)            sum of the active-arm columns (a blank arm counts as 0)
    Distance (mm)              MEAN over the measured frames of that force second
    Distance SD (mm)           sample SD across those frames (blank when N < 2)
    N frames, Frames planned   measured (not skipped) frames / frames planned for it
    Distance min/max/median (mm), Distance (px)   (px = mean)
    Fit at x (mm), Slope (mm/s), Fit resid SD (mm)
                               straight line through distance vs frame time: its value at the
                               sample time, its slope, and the scatter about it (N >= 3)
The Role column from extract_point_forces.py (window, buffer-before, buffer-after) is kept, so buffer
rows stay in the data and can be left out of an analysis (fit_moduli.py --rows window).

How to read the spread: the frames of one force second lie up to +/-0.47 s apart (14 frames at 30 fps), and the
gap can change by several mm per second, so Distance SD mixes real tissue motion, click
noise and timing ambiguity. It is a conservative uncertainty of the distance at the
nominal sample time, not pure measurement error. "Fit resid SD" is closer to click noise.
With only 3-4 frames per force second any SD is a rough estimate.

The frames that belong to each force second come from the same parameters the marks were
made with (stored in the marks file), or from the options below to re-summarise the same
frames under another stride, e.g. the sparse subset of a denser pass. A half-window of 15 frames or more
(the 2.0.0 default) is refused: every frame must belong to one force second (see plan_measurements.py).

Usage:
    python3 merge_distance_force.py <case_id> [--half-window-frames N] [--stride N]
            [--time-offset-s S] [--window-center-shift-s S]
"""

import argparse
import csv
import os
import sys
from pathlib import Path

import numpy as np
import openpyxl
from openpyxl.styles import Font

import framelib as fl

BASE = Path(__file__).resolve().parent
POINTS = ["A", "B", "C", "D"]
NEW_COLS = [
    "Total Force (N)", "Distance (mm)", "Distance SD (mm)", "N frames", "Frames planned",
    "Distance min (mm)", "Distance max (mm)", "Distance median (mm)", "Distance (px)",
    "Fit at x (mm)", "Slope (mm/s)", "Fit resid SD (mm)",
]
NOT_ARM = ("Timestamp", "Seconds", "In Window", "Role")


def summarise(recs, t_rel):
    """Statistics of the measured frames of one force second. recs: non-skipped records."""
    n = len(recs)
    out = {"n": n}
    if n == 0:
        return out
    d = np.array([r["distance_mm"] for r in recs], float)
    out.update(mean=float(d.mean()), min=float(d.min()), max=float(d.max()), median=float(np.median(d)),
               px=float(np.mean([r["distance_px"] for r in recs])))
    if n >= 2:
        out["sd"] = float(d.std(ddof=1))
        t = np.asarray(t_rel, float)
        if np.ptp(t) > 0:
            slope, intercept = np.polyfit(t, d, 1)
            out["fit_at_x"], out["slope"] = float(intercept), float(slope)
            if n >= 3:
                out["fit_sd"] = float(np.sqrt(np.sum((d - (slope * t + intercept)) ** 2) / (n - 2)))
    return out


def r(v, nd=4):
    return None if v is None else round(v, nd)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Merge per-frame distances into the force workbook.")
    ap.add_argument("case_id")
    ap.add_argument("--half-window-frames", dest="half_window_frames", type=int)
    ap.add_argument("--stride", type=int)
    ap.add_argument("--time-offset-s", dest="time_offset_s", type=float)
    ap.add_argument("--window-center-shift-s", dest="window_center_shift_s", type=float)
    ap.add_argument("--version", action="version", version=f"%(prog)s {fl.PIPELINE_VERSION}")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    case_id = args.case_id
    force_dir = BASE / "Videos" / case_id / "force_data"
    force_path = force_dir / f"{case_id}_points_ABCD_force.xlsx"
    marks_path = force_dir / f"{case_id}_frame_marks.json"
    out_xlsx = force_dir / f"{case_id}_points_ABCD_force_merged.xlsx"
    out_csv = force_dir / f"{case_id}_frame_distances.csv"

    for p, hint in ((force_path, "run extract_point_forces.py first"),
                    (marks_path, "run mark_suture_entry.py first")):
        if not p.exists():
            sys.exit(f"ERROR: {p} not found - {hint}")

    index = fl.load_index(force_dir, case_id)
    store = fl.MarksStore(marks_path, case_id)
    vid = store.data.get("video", {})
    if vid.get("frames") not in (None, index.n):
        sys.exit("ERROR: the frame table and the marks come from videos with different frame counts")

    wb = openpyxl.load_workbook(force_path)
    bold = Font(bold=True)
    csv_rows, info = [], []

    for label in POINTS:
        sheet = f"Point {label}"
        if sheet not in wb.sheetnames:
            continue
        ws = wb[sheet]
        headers = [c.value for c in ws[1]]
        col = {h: i for i, h in enumerate(headers)}
        arm_cols = [h for h in headers if h not in NOT_ARM]
        for h in NEW_COLS:
            c = ws.max_column + 1
            ws.cell(row=1, column=c, value=h).font = bold
            col[h] = c - 1
            ws.column_dimensions[ws.cell(row=1, column=c).column_letter].width = 16

        given = {k: getattr(args, k) for k in fl.PARAM_DEFAULTS}
        params = fl.resolve_params(index, **{**(store.last_params(label) or {}),
                                             **{k: v for k, v in given.items() if v is not None}})
        try:
            fl.check_half_window(index, params["half_window_frames"])
        except ValueError as e:
            sys.exit(f"ERROR: point {label}: {e}")
        planned = measured = skipped = unmarked = 0
        with_data = {"window": 0, "buffer": 0}
        for row in ws.iter_rows(min_row=2):
            secs = row[col["Seconds"]].value
            row[col["Total Force (N)"]].value = sum((row[col[a]].value or 0) for a in arm_cols)
            if secs is None:
                continue
            x = round(float(secs), 3)
            if "Role" in col:
                role = row[col["Role"]].value
            else:   # workbook made by an older extraction: only its In Window rows were measured
                role = "window" if row[col["In Window"]].value == "YES" else None
            to_measure = role in fl.ROLES
            centre, frames = fl.sample_frames(index, x, **params)
            recs, t_rel = [], []
            t_target = fl.target_time(x, params)
            for sf in frames:
                rec = store.get(label, sf.frame)
                status = "unmarked" if rec is None else ("skipped" if rec.get("skipped") else "marked")
                if to_measure:
                    planned += 1
                    measured += status == "marked"
                    skipped += status == "skipped"
                    unmarked += status == "unmarked"
                    csv_rows.append([
                        label, x, role, sf.frame, r(index.pts_s[sf.frame], 6), sf.offset_frames, r(sf.offset_ms, 2),
                        r(rec.get("distance_mm")) if status == "marked" else None,
                        r(rec.get("distance_px"), 2) if status == "marked" else None,
                        *(rec["left_crus_px"] + rec["right_crus_px"] if status == "marked" else [None] * 4),
                        rec.get("px_per_mm") if rec else None, status])
                if status == "marked":
                    recs.append(rec)
                    t_rel.append(float(index.pts_s[sf.frame]) - t_target)
            st = summarise(recs, t_rel)
            row[col["Frames planned"]].value = len(frames) if to_measure else None
            row[col["N frames"]].value = st["n"] if st["n"] else None
            if st["n"]:
                with_data["window" if role == "window" else "buffer"] += 1
                row[col["Distance (mm)"]].value = r(st["mean"])
                row[col["Distance SD (mm)"]].value = r(st.get("sd"))
                row[col["Distance min (mm)"]].value = r(st["min"])
                row[col["Distance max (mm)"]].value = r(st["max"])
                row[col["Distance median (mm)"]].value = r(st["median"])
                row[col["Distance (px)"]].value = r(st["px"], 2)
                row[col["Fit at x (mm)"]].value = r(st.get("fit_at_x"))
                row[col["Slope (mm/s)"]].value = r(st.get("slope"))
                row[col["Fit resid SD (mm)"]].value = r(st.get("fit_sd"))
        print(f"  {sheet}: Total Force for all rows; distance summarised for {with_data['window']} window and "
              f"{with_data['buffer']} buffer force seconds ({measured} frames measured, {skipped} skipped, "
              f"{unmarked} not yet marked)")
        info.append([label, *(params[k] for k in fl.PARAM_DEFAULTS), with_data["window"], with_data["buffer"],
                     planned, measured, skipped, unmarked])

    ws = wb.create_sheet("Merge info")
    ws.append([f"Pipeline version {fl.PIPELINE_VERSION}. Per-point parameters and frame counts (frames counted over the "
               "force seconds that are measured; every frame belongs to one force second)"])
    ws.append(["Point", *fl.PARAM_DEFAULTS.keys(), "Window seconds with data", "Buffer seconds with data",
               "Frames planned", "Measured", "Skipped", "Not yet marked"])
    for line in info:
        ws.append(line)
    ws.append([])
    ws.append([f"Video: {vid.get('name', '?')}, {index.n} frames, time base {vid.get('time_base', '?')}. "
               "Video time zero = first frame; time_offset_s = video time minus force time."])
    ws.append(["Distance (mm) = mean over measured frames. Distance SD mixes tissue motion, click noise and "
               "timing ambiguity; see the header of merge_distance_force.py."])
    ws.append(["Role column: window = between the noted start and end; buffer-before / buffer-after = in the buffer. "
               "Buffer rows are measured and kept; fit_moduli.py --rows window leaves them out of the fits."])
    for c in ws[2]:
        c.font = bold

    tmp = out_xlsx.with_name(out_xlsx.name + ".tmp")
    wb.save(tmp)
    os.replace(tmp, out_xlsx)
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["point", "force_second", "role", "frame", "time_s", "offset_frames", "offset_ms", "distance_mm",
                    "distance_px", "left_x", "left_y", "right_x", "right_y", "px_per_mm", "status"])
        w.writerows(csv_rows)
    print(f"Saved: {out_xlsx}")
    print(f"Saved: {out_csv}")


if __name__ == "__main__":
    main()
