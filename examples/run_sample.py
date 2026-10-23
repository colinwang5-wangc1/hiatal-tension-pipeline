"""
run_sample.py — Run the whole pipeline on the synthetic sample case and check it against the known truth.

Use this to confirm the pipeline works in a new environment (a new computer, operating system or Python version).
It needs no patient data and no one to click: the sample case is synthetic (see make_sample_case.py) and
auto_mark.py stands in for the operator. Each stage is a real command-line script, run as its own process:

    0  make_sample_case.py            builds the synthetic video, force log, tracking sheet and calibration files
    1  index_video.py                 frame table from the video's stored timestamps
    2  parse_force_api.py             force log -> Excel/CSV
    3  extract_point_forces.py        force samples in each window plus the buffer, with roles
    4  plan_measurements.py --yes     summary of force values and frames, default stride
    5  examples/auto_mark.py (x4)     marks every planned frame (stands in for calibrate_reference.py and
                                      mark_suture_entry.py, which need a person)
    6  mark_suture_entry.py --verify  every marked frame is re-decoded and checked
    7  merge_distance_force.py        per-force-second distance summaries
    8  fit_moduli.py                  force-strain fits, for all rows and for window rows only

and then checks the results against the truth built into the sample (frame rate, selected force rows, every
measured distance, the force-distance pairing, and the fitted modulus). The exit code is 0 only if every check passes.

Usage:
    python3 examples/run_sample.py [case_id] [--fresh] [--quiet]
        --fresh   delete and rebuild the sample case first (only ever deletes a folder that holds a sample)
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_sample_case as mk  # noqa: E402

TOLERANCE_MM_FRAME = 0.05        # per measured frame, against the true gap at that frame's stored time
TOLERANCE_MM_PAIRING = 0.06      # fitted distance at the force second, away from the gap's kinks
TOLERANCE_MODULUS = 0.03         # fraction of the true total modulus
MIN_R2 = 0.99


def stage(number, label, cmd, quiet):
    start = time.time()
    done = subprocess.run([sys.executable, *[str(c) for c in cmd]], cwd=ROOT, capture_output=True, text=True)
    elapsed = time.time() - start
    if done.returncode != 0:
        print(f"[{number}] {label}: FAILED after {elapsed:.1f} s\n{done.stdout[-1500:]}\n{done.stderr[-1500:]}")
        sys.exit(1)
    if not quiet:
        print(f"[{number}] {label}  ({elapsed:.1f} s)")
    return done.stdout


def sheet_rows(path, name):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[name]
    head = [c.value for c in ws[1]]
    rows = [dict(zip(head, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
    wb.close()
    return rows


class Report:
    def __init__(self):
        self.results = []

    def check(self, name, ok, detail=""):
        self.results.append((name, bool(ok), detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))

    @property
    def ok(self):
        return all(ok for _, ok, _ in self.results)


def run(case_id="SAMPLE001", fresh=False, quiet=False):
    case_dir = ROOT / "Videos" / case_id
    fd = case_dir / "force_data"
    truth_path = case_dir / "ground_truth.json"
    if case_dir.exists() and not truth_path.exists():
        sys.exit(f"ERROR: {case_dir} exists but is not a sample case (no ground_truth.json). "
                 "Choose another case_id; this script will not touch it.")
    if fresh and case_dir.exists():
        shutil.rmtree(case_dir)
    if not case_dir.exists():
        if not quiet:
            print("[0] make_sample_case.py")
        mk.build(case_id, ROOT, quiet=True)
    truth = json.loads(truth_path.read_text())
    video = case_dir / truth["video"]["file"]
    sheet = case_dir / "sample_tracking_sheet.xlsx"
    knots = [tuple(k) for k in truth["gap_knots_s_mm"]]

    stage(1, "index_video.py", ["index_video.py", video, case_id], quiet)
    stage(2, "parse_force_api.py", ["parse_force_api.py", fd / f"{case_id}_force_raw.json", case_id], quiet)
    stage(3, "extract_point_forces.py", ["extract_point_forces.py", case_id, "--tracking-sheet", sheet], quiet)
    plan_out = stage(4, "plan_measurements.py --yes", ["plan_measurements.py", case_id, "--yes"], quiet)
    for p in "ABCD":
        stage(5, f"auto_mark.py (point {p})", ["examples/auto_mark.py", video, case_id, p], quiet)
    for p in "ABCD":
        stage(6, f"mark_suture_entry.py --verify (point {p})", ["mark_suture_entry.py", video, case_id, p, "--verify"], quiet)
    stage(7, "merge_distance_force.py", ["merge_distance_force.py", case_id], quiet)
    stage(8, "fit_moduli.py --rows all", ["fit_moduli.py", case_id, "--rows", "all"], quiet)
    stage(8, "fit_moduli.py --rows window", ["fit_moduli.py", case_id, "--rows", "window"], quiet)

    print("\nChecking the results against the known truth")
    rep = Report()

    meta = json.loads((fd / f"{case_id}_frame_times.json").read_text())
    rep.check("frame table has every frame of the video", meta["frames"] == truth["video"]["frames"],
              f"{meta['frames']} frames")
    rep.check("frame rate read from the stored timestamps is 29.97, not 30",
              abs(meta["mean_fps"] - truth["video"]["fps"]) < 1e-3, f"{meta['mean_fps']:.5f} fps")

    force = json.loads((fd / f"{case_id}_force_raw.json").read_text())
    present = {a: {e["x"] for e in force[a]} for a in ("USM1", "USM3")}
    seconds = present["USM1"] | present["USM3"]
    sel = {r["Point"]: r for r in sheet_rows(fd / f"{case_id}_points_ABCD_force.xlsx", "Selection") if r["Point"] in list("ABCD")}
    ok = True
    for p, s in truth["window_starts_s"].items():
        want = len([x for x in seconds if s <= x <= s + truth["window_length_s"]])
        ok &= sel[p]["Window rows"] == want and sel[p]["Buffer-before rows"] > 0 and sel[p]["Buffer-after rows"] > 0
    rep.check("force samples selected per window, with buffer rows on both sides", ok)

    plan = json.loads((fd / f"{case_id}_measurement_plan.json").read_text())
    planned = sum(v["planned_frames"] for v in plan["points"].values())
    marks = json.loads((fd / f"{case_id}_frame_marks.json").read_text())
    n_marked = sum(1 for pt in marks["points"].values() for r in pt["frames"].values() if not r.get("skipped"))
    rep.check("every planned frame was marked", n_marked == planned, f"{n_marked} of {planned} frames")

    import csv
    with open(fd / f"{case_id}_frame_distances.csv", newline="") as f:
        frames = [r for r in csv.DictReader(f) if r["status"] == "marked"]
    errs = np.array([float(r["distance_mm"]) - mk.gap_mm(float(r["time_s"]), knots) for r in frames])
    rep.check("every measured distance matches the true gap at that frame's stored time",
              np.abs(errs).max() <= TOLERANCE_MM_FRAME,
              f"max |error| {np.abs(errs).max():.3f} mm over {len(errs)} measurements")

    knot_times = np.array([t for t, _ in knots])
    worst = 0.0
    n_pair = 0
    for p in "ABCD":
        for r in sheet_rows(fd / f"{case_id}_points_ABCD_force_merged.xlsx", f"Point {p}"):
            if r.get("Fit at x (mm)") is None or r["N frames"] is None or r["N frames"] < 3:
                continue
            x = r["Seconds"]
            if np.min(np.abs(knot_times - x)) < 1.0:
                continue
            worst = max(worst, abs(r["Fit at x (mm)"] - mk.gap_mm(x, knots)))
            n_pair += 1
    rep.check("distance at each force second matches the true gap at that second (force-video pairing)",
              n_pair > 20 and worst <= TOLERANCE_MM_PAIRING, f"max |error| {worst:.3f} mm over {n_pair} force seconds")

    for mode in ("all", "window"):
        bad, detail = False, []
        for r in sheet_rows(fd / f"{case_id}_moduli_table_{mode}.xlsx", "Moduli"):
            if r["Channel"] != "Total":
                continue
            rel = abs(r["A: Linear E (N)"] - truth["total_modulus_N"]) / truth["total_modulus_N"]
            bad |= rel > TOLERANCE_MODULUS or r["A: Lin R2"] < MIN_R2
            detail.append(f"{r['Point']} {r['A: Linear E (N)']:.2f} N (R2 {r['A: Lin R2']:.3f})")
        rep.check(f"fitted total modulus recovers {truth['total_modulus_N']:g} N within {TOLERANCE_MODULUS:.0%}, rows = {mode}",
                  not bad, "; ".join(detail))

    # why stored timestamps matter: what the old frame = int(x * 30) rule would have picked
    x = float(truth["window_starts_s"]["D"] + 5)
    naive = int(x * 30)
    t_naive = naive * 1001 / 30000.0
    print(f"\nFor interest: for force second {x:g}, the rule frame = int(x * 30) picks frame {naive}, which is at "
          f"{t_naive:.3f} s on the video clock ({(t_naive - x) * 1000:+.0f} ms off). The true gap there differs from the "
          f"gap at {x:g} s by {abs(mk.gap_mm(t_naive, knots) - mk.gap_mm(x, knots)):.2f} mm. "
          "This pipeline finds frames by their stored timestamps instead.")
    print("\n" + ("ALL CHECKS PASSED" if rep.ok else "SOME CHECKS FAILED"))
    return 0 if rep.ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run the pipeline on the synthetic sample case and check the results.")
    ap.add_argument("case_id", nargs="?", default="SAMPLE001")
    ap.add_argument("--fresh", action="store_true", help="rebuild the sample case first")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    sys.exit(run(a.case_id, a.fresh, a.quiet))
