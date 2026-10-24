"""
End-to-end test on a synthetic case: per-frame marks -> merge_distance_force.py ->
fit_moduli.py. The gap closes linearly and force rises linearly with strain, so the
fitted linear modulus can be checked against a plain regression on the per-second means,
for both row sets (--rows all and --rows window).

Each point has 2 buffer-before rows, 8 window rows and 2 buffer-after rows.

Run from the repository root:
    python3 -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import framelib as fl  # noqa: E402
import fit_moduli as fm  # noqa: E402
import merge_distance_force as mg  # noqa: E402
from test_framelib import synthetic_index  # noqa: E402

CASE = "case1"
PXMM = 10.0
STARTS = {"A": 8378, "B": 8413, "C": 8453, "D": 8490}
N_SEC = 8
BUF = 2


def gap(t, start):
    return 40.0 - 4.0 * (t - start)        # mm, closing at 4 mm/s


def rows_for(start):
    """(force second, role, USM1) for one point."""
    out = []
    for j in range(-BUF, N_SEC + BUF):
        role = "buffer-before" if j < 0 else ("window" if j < N_SEC else "buffer-after")
        f1 = 0.0 if j < 2 else 0.8 * (j - 1)          # zero force until the 2nd window second, then rising
        out.append((start + j, role, f1))
    return out


def build_case(root, idx, params):
    fdir = Path(root) / "Videos" / CASE / "force_data"
    fdir.mkdir(parents=True)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    store = fl.MarksStore(fdir / f"{CASE}_frame_marks.json", CASE)
    store.set_video(idx)
    for label, start in STARTS.items():
        ws = wb.create_sheet(f"Point {label}")
        ws.append(["Timestamp", "Seconds", "USM1", "USM3", "In Window", "Role"])
        rows = rows_for(start)
        for x, role, f1 in rows:
            ws.append([fl.fmt_time(x), float(x), f1, 0.5 * f1, "YES" if role == "window" else "", role])
        store.note_params(label, params)
        plan = fl.plan_point(idx, [x for x, _, _ in rows], **params)
        for k in plan.frames:
            d = gap(idx.pts_s[k], start)
            store.put(label, k, {"pts_s": float(idx.pts_s[k]), "left_crus_px": [0, 0], "right_crus_px": [d * PXMM, 0],
                                 "distance_px": d * PXMM, "distance_mm": d, "px_per_mm": PXMM,
                                 "skipped": False, "source": "manual"})
    wb.save(fdir / f"{CASE}_points_ABCD_force.xlsx")
    idx.save(fl.frame_table_path(fdir, CASE))
    store.save()
    return fdir


def merged_rows(fdir, label="A"):
    ws = openpyxl.load_workbook(fdir / f"{CASE}_points_ABCD_force_merged.xlsx")[f"Point {label}"]
    head = [c.value for c in ws[1]]
    return [dict(zip(head, [c.value for c in r])) for r in ws.iter_rows(min_row=2)]


def expected_slope(fdir, rows_mode):
    data = [r for r in merged_rows(fdir) if r["Distance (mm)"] is not None
            and (rows_mode == "all" or r["Role"] == "window")]
    d = np.array([r["Distance (mm)"] for r in data], float)
    f = np.array([r["Total Force (N)"] for r in data], float)
    eps = (d.max() - d) / d.max()
    return np.polyfit(eps, f, 1)[0], len(data)


class TestConventionB(unittest.TestCase):
    """The zero-strain reference for Convention B, including force traces that return to zero."""

    dist = np.array([40.0, 38, 34, 30, 26, 22, 18, 14, 12, 12])
    # zero before loading, loading, then the force falls back to zero when the instrument is released
    force = np.array([0.0, 0, 0, 1.0, 2.0, 3.0, 4.0, 3.0, 0.0, 0.0])

    def test_first_rise_takes_the_last_zero_before_loading(self):
        self.assertEqual(fm.onset_index(self.dist, self.force, "first-rise"), 2)
        cb = fm.convention_b(self.dist, self.force, 40.0, "first-rise")
        self.assertEqual((cb["oi"], cb["d0"], cb["L0"]), (2, 6.0, 34.0))
        self.assertEqual(int(cb["keep"].sum()), 8)                    # rows 2 to 9

    def test_version_1_rule_jumps_to_the_end_when_force_returns_to_zero(self):
        # the failure that motivated the change: the smallest-gap zero-force row is the post-release row
        self.assertEqual(fm.onset_index(self.dist, self.force, "smallest-gap"), 8)
        cb = fm.convention_b(self.dist, self.force, 40.0, "smallest-gap")
        self.assertEqual(int(cb["keep"].sum()), 2)

    def test_both_rules_agree_when_force_is_zero_only_before_loading(self):
        force = np.array([0.0, 0, 0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
        self.assertEqual(fm.onset_index(self.dist, force, "first-rise"),
                         fm.onset_index(self.dist, force, "smallest-gap"))
        a = fm.convention_b(self.dist, force, 40.0, "first-rise")
        b = fm.convention_b(self.dist, force, 40.0, "smallest-gap")
        self.assertEqual(a["d0"], b["d0"])
        self.assertTrue(np.array_equal(a["keep"], b["keep"]))

    def test_undefined_cases(self):
        self.assertIsNone(fm.onset_index(self.dist, np.ones(10), "first-rise"))          # nonzero from the first row
        self.assertIsNone(fm.onset_index(self.dist, np.zeros(10), "first-rise"))         # never nonzero
        self.assertIsNone(fm.onset_index(self.dist, np.ones(10), "smallest-gap"))        # no zero at all
        self.assertIsNone(fm.convention_b(self.dist, np.ones(10), 40.0))


class TestFitChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = synthetic_index()

    def run_chain(self, root, *fit_args):
        mg.BASE = Path(root)
        mg.main([CASE])
        fm.BASE, fm.case_id = Path(root), CASE
        fm.main(list(fit_args))

    def table_row(self, fdir, rows_mode, point="A", channel="Total"):
        table = openpyxl.load_workbook(fdir / f"{CASE}_moduli_table_{rows_mode}.xlsx").active
        head = [c.value for c in table[1]]
        for r in table.iter_rows(min_row=2, values_only=True):
            if r[0] == point and r[1] == channel:
                return dict(zip(head, r))
        raise AssertionError("row not found")

    def test_all_rows_is_the_default_and_matches_a_plain_regression(self):
        params = fl.resolve_params(stride=10)
        with tempfile.TemporaryDirectory() as root:
            fdir = build_case(root, self.idx, params)
            self.run_chain(root)
            plots = Path(root) / "Videos" / CASE / "plots"
            for p in "ABCD":
                self.assertGreater((plots / f"{CASE}_point{p}_model_fits_all.png").stat().st_size, 10_000)
            row = self.table_row(fdir, "all")
            slope, n = expected_slope(fdir, "all")
            self.assertEqual((row["n"], row["n window"], row["n buffer"], row["Rows used"]), (n, N_SEC, 2 * BUF, "all"))
            self.assertAlmostEqual(row["A: Linear E (N)"], round(slope, 3), places=3)

    def test_window_rows_option_leaves_buffer_out_and_names_files_apart(self):
        params = fl.resolve_params(stride=10)
        with tempfile.TemporaryDirectory() as root:
            fdir = build_case(root, self.idx, params)
            self.run_chain(root)
            fm.main(["--rows", "window"])
            plots = Path(root) / "Videos" / CASE / "plots"
            self.assertTrue((plots / f"{CASE}_pointA_model_fits_window.png").exists())
            self.assertTrue((plots / f"{CASE}_pointA_model_fits_all.png").exists())          # both coexist
            row = self.table_row(fdir, "window")
            slope, n = expected_slope(fdir, "window")
            self.assertEqual((row["n"], row["n window"], row["n buffer"], row["Rows used"]), (N_SEC, N_SEC, 0, "window"))
            self.assertAlmostEqual(row["A: Linear E (N)"], round(slope, 3), places=3)
            self.assertNotEqual(self.table_row(fdir, "all")["n"], row["n"])

    def test_row_set_changes_the_strain_reference(self):
        # the widest gap lies in the buffer-before rows, so 'all' and 'window' use different references
        params = fl.resolve_params(stride=10)
        with tempfile.TemporaryDirectory() as root:
            fdir = build_case(root, self.idx, params)
            self.run_chain(root)
            fm.main(["--rows", "window"])
            self.assertNotAlmostEqual(self.table_row(fdir, "all")["A: Linear E (N)"],
                                      self.table_row(fdir, "window")["A: Linear E (N)"], places=2)

    def test_table_footer_names_rows_and_version(self):
        params = fl.resolve_params(stride=10)
        with tempfile.TemporaryDirectory() as root:
            fdir = build_case(root, self.idx, params)
            self.run_chain(root, "--rows", "window")
            table = openpyxl.load_workbook(fdir / f"{CASE}_moduli_table_window.xlsx").active
            text = " ".join(str(c.value) for row in table.iter_rows() for c in row if c.value is not None)
            self.assertIn("window rows only", text)
            self.assertIn(fl.PIPELINE_VERSION, text)

    def test_plots_still_work_without_the_frame_table(self):
        params = fl.resolve_params(stride=10)
        with tempfile.TemporaryDirectory() as root:
            fdir = build_case(root, self.idx, params)
            mg.BASE = Path(root)
            mg.main([CASE])
            (fdir / f"{CASE}_frame_distances.csv").unlink()
            fm.BASE, fm.case_id = Path(root), CASE
            fm.main()
            self.assertTrue((Path(root) / "Videos" / CASE / "plots" / f"{CASE}_pointA_model_fits_all.png").exists())

    def test_fit_asks_for_merge_first(self):
        with tempfile.TemporaryDirectory() as root:
            fm.BASE, fm.case_id = Path(root), CASE
            with self.assertRaises(SystemExit):
                fm.main()


if __name__ == "__main__":
    unittest.main()
