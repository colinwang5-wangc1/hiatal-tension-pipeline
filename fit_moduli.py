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

Usage:
    python3 fit_moduli.py [case_id]     (default YV003)
"""

import sys
import json
import numpy as np
import openpyxl
from openpyxl.styles import Font, PatternFill
from scipy.optimize import curve_fit
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

BASE    = Path(__file__).resolve().parent
case_id = sys.argv[1] if len(sys.argv) > 1 else "YV003"

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


def load_point(ws):
    headers = [c.value for c in ws[1]]
    col = {h: i for i, h in enumerate(headers)}
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True)
            if r[col["Distance (mm)"]] is not None]
    dist = np.array([r[col["Distance (mm)"]] for r in rows], float)
    data = {
        "dist":  dist,
        "USM1":  np.array([r[col["USM1"]] or 0 for r in rows], float),
        "USM3":  np.array([r[col["USM3"]] or 0 for r in rows], float),
        "Total": np.array([r[col["Total Force (N)"]] for r in rows], float),
        "max_dist": float(np.max(dist)),
    }
    return data


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


def onset_index(dist, force):
    """Convention B: index of the largest-deformation point with force == 0.
    Returns None if no zero-force point exists."""
    zeros = np.where(np.isclose(force, 0.0, atol=1e-6))[0]
    if len(zeros) == 0:
        return None
    # largest deformation = smallest distance among zero-force points
    return zeros[np.argmin(dist[zeros])]


def main():
    wb = openpyxl.load_workbook(BASE / "Videos" / case_id / "force_data"
                               / f"{case_id}_points_ABCD_force.xlsx")

    results = {}   # (point, channel) -> {"A": fit, "B": fit, meta...}

    for pt in POINTS:
        d = load_point(wb[f"Point {pt}"])
        max_dist = d["max_dist"]
        for ch in CHANNELS:
            force = d[ch]
            deform = max_dist - d["dist"]

            # Convention A: strain from widest gap, all points
            epsA = deform / max_dist
            fitA = fit_all(epsA, force)

            # Convention B: strain from force onset, trimmed
            oi = onset_index(d["dist"], force)
            if oi is not None:
                d0 = deform[oi]                     # deformation at onset
                L0 = max_dist - d0                  # gap at onset
                keep = deform >= d0 - 1e-9
                epsB = (deform[keep] - d0) / L0
                forceB = force[keep]
                fitB = fit_all(epsB, forceB) if len(epsB) >= 2 else None
                b_note = f"onset@deform={d0:.1f}mm, n={int(np.sum(keep))}"
            else:
                fitB = None
                b_note = "no zero-force point — B undefined"

            results[(pt, ch)] = {
                "A": fitA, "B": fitB, "b_note": b_note,
                "n": len(force), "max_dist": max_dist,
                "epsA": epsA, "force": force, "deform": deform,
                "oi": oi,
            }

    write_table(results)
    plot_overlays(results, wb)
    print("\nDone.")


def write_table(results):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Moduli"
    bold = Font(bold=True)
    gold = PatternFill(start_color="FFFFD700", end_color="FFFFD700", fill_type="solid")

    headers = [
        "Point", "Channel", "n",
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
            vals = [
                pt, ch, R["n"],
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

    ws.column_dimensions["K"].width = 34
    out = BASE / "Videos" / case_id / "force_data" / f"{case_id}_moduli_table.xlsx"
    wb.save(out)
    print(f"Saved table: {out}")


def _plot_fit(ax, eps, force, fit, title):
    ax.scatter(eps, force, color="#333", s=60, zorder=5, label="data")
    if fit is None:
        ax.text(0.5, 0.5, "B undefined\n(no zero-force point)",
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


def plot_overlays(results, wb):
    """One figure per point: 2 rows (Convention A / B) x 3 channels (USM1, USM3, Total)."""
    plots_dir = BASE / "Videos" / case_id / "plots"
    plots_dir.mkdir(exist_ok=True)

    for pt in POINTS:
        fig, axes = plt.subplots(2, 3, figsize=(18, 10))
        fig.suptitle(f"{case_id} — Point {pt}: force vs strain — "
                     f"Convention A (top, from widest gap) vs Convention B (bottom, slack trimmed)",
                     fontsize=13, fontweight="bold")

        for col, ch in enumerate(CHANNELS):
            R = results[(pt, ch)]

            # Convention A: strain from widest gap, all points
            _plot_fit(axes[0, col], R["epsA"], R["force"], R["A"], ch)

            # Convention B: strain from force onset, trimmed
            b = R["B"]
            if b is not None:
                oi = R["oi"]
                deform = R["deform"]
                d0 = deform[oi]
                L0 = R["max_dist"] - d0
                keep = deform >= d0 - 1e-9
                epsB = (deform[keep] - d0) / L0
                forceB = R["force"][keep]
            else:
                epsB, forceB = np.array([]), np.array([])
            _plot_fit(axes[1, col], epsB, forceB, b, f"{ch}  ({R['b_note']})")

        for ax in axes[0, :]:
            ax.set_xlabel("Strain  (deformation / max distance)", fontsize=9)
        for ax in axes[1, :]:
            ax.set_xlabel("Strain  (from force onset)", fontsize=9)
        for ax in axes[:, 0]:
            ax.set_ylabel("Force (N)", fontsize=10)
        for ax in axes.flat:
            ax.grid(True, alpha=0.3)

        plt.tight_layout()
        out = plots_dir / f"{case_id}_point{pt}_model_fits.png"
        plt.savefig(out, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"Saved plot: {out.name}")


if __name__ == "__main__":
    main()
