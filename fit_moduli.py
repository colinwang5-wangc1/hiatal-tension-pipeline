"""
fit_moduli.py — Fit constitutive models to force vs strain for points A–D.

Converts crural deformation to strain and fits candidate models to each of the
12 curves (4 points × {USM1, USM3, Total}) under two zero-strain conventions.

Strain definition (per user decision):
    eps = deformation / max_distance,  deformation = max_distance - current_distance

Zero-strain conventions:
    A (zero displacement = zero strain): keep all points, strain measured from the
      widest gap. Fit 1-parameter models (Neo-Hookean + linear).
    B (last zero-force point = zero strain): trim the stress-free slack region,
      strain measured from the gap at force onset. Fit linear model.

Models restricted to 1-parameter forms only (per user decision — with 5-8 points
per curve, 2+ parameter nonlinear models (Fung, power law) are not identifiable;
the data cannot resolve more than one free parameter):
    Linear        F = m*eps + b            effective modulus = slope m  [N]
    Neo-Hookean   F = 2*C1*(lam - 1/lam^2), lam=1+eps   small-strain E0 = 6*C1

CAVEAT: no tissue cross-sectional area is available, so all "moduli" are effective
stiffnesses in units of Newtons (force per unit strain), NOT true Pa moduli.

Input: the merged workbook from merge_distance_force.py
    Videos/<case_id>/force_data/<case_id>_points_ABCD_force_merged.xlsx
Each force second contributes one point: its mean distance over the measured frames.
The fits use only those means. The plots also show each force second's spread and the
individual frames behind it (from <case_id>_frame_distances.csv):
    black dot + horizontal bar   mean strain +/- (SD of distance across frames) / reference length
    small grey dots              every measured frame of that force second, at that second's force
The bars mix tissue motion, click noise and timing ambiguity (see merge_distance_force.py)
and are NOT propagated into the fits.

Rows: every force second that was measured is a row, labelled by role (window = between the noted
start and end; buffer-before / buffer-after = in the buffer). --rows all (default) fits all measured
rows; --rows window leaves the buffer rows out of the fits (they stay in the merged workbook). Plots
draw window points filled and buffer points hollow. Outputs are named by row set so both can coexist:
    <case_id>_moduli_table_<rows>.xlsx    and    plots/<case_id>_point<X>_model_fits_<rows>.png
The strain reference (widest gap, force onset) is taken from the rows used.

Convention B reference (--onset): the zero-strain gap is the gap at the last zero-force row before the force
first becomes nonzero (first-rise, the definition in the Methods). Version 1.0.0 instead took the zero-force row
with the smallest gap (smallest-gap), which differs whenever the force trace returns to zero after loading, for
example when an instrument is released; that rule is available for comparison. A Convention B fit needs at
least 3 points.

Usage:
    python3 fit_moduli.py <case_id> [--rows all|window] [--onset first-rise|smallest-gap]
"""

import argparse
import csv
import sys
import json
import numpy as np
import framelib as fl
import openpyxl
from openpyxl.styles import Font, PatternFill
from scipy.optimize import curve_fit
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

BASE    = Path(__file__).resolve().parent
case_id = None         # set from the command line by main()

POINTS   = ["A", "B", "C", "D"]
CHANNELS = ["USM1", "USM3", "Total"]

# ---------- models ----------
def m_linear(eps, m, b):        return m * eps + b
def m_neo(eps, C1):
    lam = 1.0 + eps
    return 2.0 * C1 * (lam - 1.0 / lam**2)

def r2(y, yhat):
    y = np.asarray(y, float)
    ss_res = np.sum((y - yhat) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    return 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else float("nan")


def load_point(ws, rows_mode="all"):
    headers = [c.value for c in ws[1]]
    col = {h: i for i, h in enumerate(headers)}
    role_col = col.get("Role")
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True)
            if r[col["Distance (mm)"]] is not None
            and (rows_mode == "all" or role_col is None or r[role_col] == "window")]
    if not rows:
        sys.exit(f"ERROR: no measured rows for {ws.title} (rows = {rows_mode}); mark frames and run "
                 f"merge_distance_force.py first")
    dist = np.array([r[col["Distance (mm)"]] for r in rows], float)
    sd_col = col.get("Distance SD (mm)")
    data = {
        "role":  np.array(["window" if role_col is None else r[role_col] for r in rows]),
        "dist":  dist,
        "secs":  np.array([r[col["Seconds"]] for r in rows], float),
        "sd":    np.array([np.nan if sd_col is None or r[sd_col] is None else r[sd_col] for r in rows], float),
        "USM1":  np.array([r[col["USM1"]] or 0 for r in rows], float),
        "USM3":  np.array([r[col["USM3"]] or 0 for r in rows], float),
        "Total": np.array([r[col["Total Force (N)"]] for r in rows], float),
        "max_dist": float(np.max(dist)),
    }
    return data


def load_frames():
    """{(point, force second): [distance_mm of each measured frame]} from the per-frame table."""
    path = BASE / "Videos" / case_id / "force_data" / f"{case_id}_frame_distances.csv"
    out = {}
    if not path.exists():
        return out
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["status"] == "marked":
                out.setdefault((r["point"], round(float(r["force_second"]), 3)), []).append(float(r["distance_mm"]))
    return out


def fit_all(eps, force):
    """Fit all models; return dict of params + R² (NaN on failure)."""
    out = {}
    n = len(eps)

    # Linear (free intercept)
    try:
        p, _ = curve_fit(m_linear, eps, force, p0=[1.0, 0.0], maxfev=10000)
        out["lin_slope"], out["lin_int"] = p
        out["lin_r2"] = r2(force, m_linear(eps, *p))
    except Exception:
        out["lin_slope"] = out["lin_int"] = out["lin_r2"] = float("nan")

    # Neo-Hookean
    try:
        p, _ = curve_fit(m_neo, eps, force, p0=[0.5],
                         bounds=([0], [1e3]), maxfev=20000)
        out["neo_C1"] = p[0]
        out["neo_E0"] = 6.0 * p[0]
        out["neo_r2"] = r2(force, m_neo(eps, *p))
    except Exception:
        out["neo_C1"] = out["neo_E0"] = out["neo_r2"] = float("nan")

    return out


ONSET_RULES = ("first-rise", "smallest-gap")
MIN_B_POINTS = 3      # a straight-line fit through 2 points has R2 = 1 whatever the data


def onset_index(dist, force, rule="first-rise"):
    """Convention B: row index of the zero-strain reference, or None when it is undefined.

    first-rise (default; the definition in the Methods): the last zero-force row before the force first
    becomes nonzero. Rows are in time order. Undefined if the force is nonzero from the first row or never
    nonzero.
    smallest-gap (the rule of version 1.0.0): the zero-force row with the smallest gap. It gives the same
    answer only when the force is zero before loading and nowhere after. A force trace that returns to zero
    later (for example when the instrument is released) moves the reference to the end of the window.
    """
    zero = np.isclose(force, 0.0, atol=1e-6)
    if rule == "smallest-gap":
        z = np.flatnonzero(zero)
        return None if len(z) == 0 else int(z[np.argmin(dist[z])])
    nonzero = np.flatnonzero(~zero)
    if len(nonzero) == 0 or nonzero[0] == 0:
        return None
    return int(nonzero[0] - 1)


def convention_b(dist, force, max_dist, rule="first-rise"):
    """Convention B reference: None, or {oi, d0 (deformation at onset), L0 (gap at onset), keep (rows kept)}."""
    oi = onset_index(dist, force, rule)
    if oi is None:
        return None
    deform = max_dist - dist
    d0 = float(deform[oi])
    keep = (np.arange(len(dist)) >= oi) if rule == "first-rise" else (deform >= d0 - 1e-9)
    return {"oi": oi, "d0": d0, "L0": float(max_dist - d0), "keep": keep}


def parse_args(argv):
    ap = argparse.ArgumentParser(description="Fit force-strain models to the merged force and distance data.")
    ap.add_argument("case_id", nargs="?")
    ap.add_argument("--rows", choices=["all", "window"], default="all",
                    help="all = every measured row (window and buffer); window = only rows between the "
                         "noted start and end [all]")
    ap.add_argument("--onset", choices=list(ONSET_RULES), default="first-rise",
                    help="Convention B reference: first-rise = last zero-force row before the force first becomes "
                         "nonzero (the Methods definition); smallest-gap = the version 1.0.0 rule [first-rise]")
    ap.add_argument("--version", action="version", version=f"%(prog)s {fl.PIPELINE_VERSION}")
    return ap.parse_args(argv)


def main(argv=None):
    global case_id
    args = parse_args([] if argv is None else argv)
    if args.case_id:
        case_id = args.case_id
    if not case_id:
        sys.exit("ERROR: a case_id is required. Usage: python3 fit_moduli.py <case_id> [--rows all|window]")
    rows_mode = args.rows
    merged = BASE / "Videos" / case_id / "force_data" / f"{case_id}_points_ABCD_force_merged.xlsx"
    if not merged.exists():
        sys.exit(f"ERROR: {merged.name} not found - run merge_distance_force.py {case_id} first")
    wb = openpyxl.load_workbook(merged)
    frames = load_frames()

    results = {}   # (point, channel) -> {"A": fit, "B": fit, meta...}

    for pt in POINTS:
        d = load_point(wb[f"Point {pt}"], rows_mode)
        max_dist = d["max_dist"]
        for ch in CHANNELS:
            force = d[ch]
            deform = max_dist - d["dist"]

            # Convention A: strain from widest gap, all points
            epsA = deform / max_dist
            fitA = fit_all(epsA, force)

            # Convention B: strain from force onset, trimmed
            cb = convention_b(d["dist"], force, max_dist, args.onset)
            if cb is None:
                fitB = None
                b_note = ("no zero-force point — B undefined" if args.onset == "smallest-gap"
                          else "no zero-force row before the force first rises — B undefined")
            else:
                keep = cb["keep"]
                epsB = (deform[keep] - cb["d0"]) / cb["L0"]
                n_keep = int(np.sum(keep))
                if n_keep >= MIN_B_POINTS:
                    fitB = fit_all(epsB, force[keep])
                    b_note = f"onset@deform={cb['d0']:.1f}mm, n={n_keep}"
                else:
                    fitB = None
                    b_note = f"onset@deform={cb['d0']:.1f}mm, n={n_keep} (fewer than {MIN_B_POINTS}, not fitted)"

            results[(pt, ch)] = {
                "A": fitA, "B": fitB, "b_note": b_note, "cb": cb,
                "n": len(force), "max_dist": max_dist,
                "epsA": epsA, "force": force, "deform": deform,
                "sd": d["sd"], "secs": d["secs"], "role": d["role"],
            }

    write_table(results, rows_mode, args.onset)
    plot_overlays(results, wb, frames, rows_mode, args.onset)
    print("\nDone.")


def write_table(results, rows_mode="all", onset="first-rise"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Moduli"
    bold = Font(bold=True)
    gold = PatternFill(start_color="FFFFD700", end_color="FFFFD700", fill_type="solid")
    rows_label = "all measured rows (window + buffer)" if rows_mode == "all" else "window rows only"

    headers = [
        "Point", "Channel", "n", "n window", "n buffer", "Rows used",
        "A: Linear E (N)", "A: Lin R2",
        "A: NeoH C1", "A: NeoH E0 (N)", "A: NeoH R2",
        "B: Linear E (N)", "B: Lin R2", "B note",
    ]
    for c, h in enumerate(headers, 1):
        ws.cell(row=1, column=c, value=h).font = bold

    row = 2
    for pt in POINTS:
        for ch in CHANNELS:
            R = results[(pt, ch)]
            a = R["A"]; b = R["B"]
            n_win = int(np.sum(R["role"] == "window"))
            vals = [
                pt, ch, R["n"], n_win, R["n"] - n_win, rows_mode,
                round(a["lin_slope"], 3), round(a["lin_r2"], 3),
                round(a["neo_C1"], 3), round(a["neo_E0"], 3), round(a["neo_r2"], 3),
                round(b["lin_slope"], 3) if b else None,
                round(b["lin_r2"], 3) if b else None,
                R["b_note"],
            ]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=row, column=c, value=v)
                if ch == "Total":
                    cell.fill = gold
            row += 1

    ws.column_dimensions[ws.cell(row=1, column=len(headers)).column_letter].width = 34
    ws.append([])
    ws.append([f"Rows used: {rows_label}. Pipeline version {fl.PIPELINE_VERSION}. Fits use the per-force-second "
               "mean distance."])
    ws.append([f"Convention B reference rule: {onset} "
               + ("(the last zero-force row before the force first becomes nonzero)" if onset == "first-rise"
                  else "(version 1.0.0 rule: the zero-force row with the smallest gap)")
               + f". A Convention B fit needs at least {MIN_B_POINTS} points."])
    out = BASE / "Videos" / case_id / "force_data" / f"{case_id}_moduli_table_{rows_mode}.xlsx"
    wb.save(out)
    print(f"Saved table: {out}")


def _plot_fit(ax, eps, force, fit, title, xerr=None, fx=None, fy=None, roles=None):
    eps, force = np.asarray(eps), np.asarray(force)
    if fx is not None and len(fx):
        ax.scatter(fx, fy, color="#888", s=10, alpha=0.4, zorder=3, label="individual frames")
    if xerr is not None and len(eps) and np.any(np.isfinite(xerr)):
        ax.errorbar(eps, force, xerr=np.nan_to_num(xerr), fmt="none", ecolor="#333",
                    elinewidth=1.0, capsize=3, zorder=4, label="SD across frames")
    win = np.ones(len(eps), bool) if roles is None else (np.asarray(roles) == "window")
    ax.scatter(eps[win], force[win], color="#333", s=60, zorder=5, label="force sample, window (mean distance)")
    if (~win).any():
        ax.scatter(eps[~win], force[~win], facecolors="white", edgecolors="#333", linewidths=1.4, s=60,
                   zorder=5, label="force sample, buffer (mean distance)")
    if fit is None:
        ax.text(0.5, 0.5, "B not fitted\n(see title)",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=10, color="#999")
        ax.set_title(title, fontsize=11)
        return
    xmax = max(eps) if len(eps) and max(eps) > 0 else 1
    xs = np.linspace(0, xmax, 200)
    if not np.isnan(fit["lin_slope"]):
        m, b = fit["lin_slope"], fit["lin_int"]
        sign = "+" if b >= 0 else "-"
        ax.plot(xs, m_linear(xs, m, b),
                color="#000000", ls="--", lw=1.3,
                label=(f"Linear: F={m:.2f}ε {sign} {abs(b):.2f}\n"
                       f"  R²={fit['lin_r2']:.2f}"))
    if not np.isnan(fit["neo_r2"]):
        C1 = fit["neo_C1"]
        ax.plot(xs, m_neo(xs, C1),
                color="#8E24AA", lw=1.4,
                label=(f"NeoH: F=2({C1:.2f})(λ-1/λ²), λ=1+ε\n"
                       f"  E0={fit['neo_E0']:.2f}, R²={fit['neo_r2']:.2f}"))
    ax.set_title(title, fontsize=11)
    ax.legend(fontsize=7, loc="best")


def _frame_cloud(frames, pt, secs, force, ref, mask=None):
    """Strain and force of every measured frame: strain = (ref - frame distance) / ref."""
    fx, fy = [], []
    for j, s in enumerate(secs):
        if mask is not None and not mask[j]:
            continue
        for dmm in frames.get((pt, round(float(s), 3)), []):
            fx.append((ref - dmm) / ref)
            fy.append(force[j])
    return np.array(fx), np.array(fy)


def plot_overlays(results, wb, frames=None, rows_mode="all", onset="first-rise"):
    """One figure per point: 2 rows (Convention A / B) x 3 channels (USM1, USM3, Total)."""
    frames = frames or {}
    plots_dir = BASE / "Videos" / case_id / "plots"
    plots_dir.mkdir(exist_ok=True)
    rows_label = "all measured rows" if rows_mode == "all" else "window rows only"

    for pt in POINTS:
        fig, axes = plt.subplots(2, 3, figsize=(18, 10))
        fig.suptitle(f"{case_id} — Point {pt}: force vs strain ({rows_label}) — "
                     f"Convention A (top, from widest gap) vs Convention B (bottom, slack trimmed)",
                     fontsize=13, fontweight="bold")

        for col, ch in enumerate(CHANNELS):
            R = results[(pt, ch)]

            # Convention A: strain from widest gap, all points
            fxA, fyA = _frame_cloud(frames, pt, R["secs"], R["force"], R["max_dist"])
            _plot_fit(axes[0, col], R["epsA"], R["force"], R["A"], ch,
                      xerr=R["sd"] / R["max_dist"], fx=fxA, fy=fyA, roles=R["role"])

            # Convention B: strain from force onset, trimmed
            b = R["B"]
            if b is not None:
                cb = R["cb"]
                keep, d0, L0 = cb["keep"], cb["d0"], cb["L0"]
                epsB = (R["deform"][keep] - d0) / L0
                forceB = R["force"][keep]
                errB = R["sd"][keep] / L0
                fxB, fyB = _frame_cloud(frames, pt, R["secs"], R["force"], L0, mask=keep)
                rolesB = R["role"][keep]
            else:
                epsB, forceB, errB = np.array([]), np.array([]), None
                fxB = fyB = rolesB = None
            _plot_fit(axes[1, col], epsB, forceB, b, f"{ch}  ({R['b_note']})",
                      xerr=errB, fx=fxB, fy=fyB, roles=rolesB)

        for ax in axes[0, :]:
            ax.set_xlabel("Strain  (deformation / max distance)", fontsize=9)
        for ax in axes[1, :]:
            ax.set_xlabel("Strain  (from force onset)", fontsize=9)
        for ax in axes[:, 0]:
            ax.set_ylabel("Force (N)", fontsize=10)
        for ax in axes.flat:
            ax.grid(True, alpha=0.3)

        fig.text(0.5, 0.004, "Bars: SD of distance across the measured frames of each force second, divided by the "
                 "reference length (tissue motion + click noise + timing); grey dots: individual frames; "
                 f"filled = window rows, hollow = buffer rows. Fits use the means only ({rows_label}). "
                 f"Convention B reference: {onset}. Pipeline v{fl.PIPELINE_VERSION}.",
                 ha="center", fontsize=8, color="#555")
        plt.tight_layout(rect=[0, 0.02, 1, 1])
        out = plots_dir / f"{case_id}_point{pt}_model_fits_{rows_mode}.png"
        plt.savefig(out, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"Saved plot: {out.name}")


if __name__ == "__main__":
    main(sys.argv[1:])
