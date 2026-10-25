"""
Tests for calibrate_reference.py: the click state machine, what is saved, the exit status when the window is
closed too early, and the inset that shows the previous reference frame. No display is needed.

Run from the repository root:
    python3 -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

import cv2
import numpy as np
import openpyxl

os.environ.setdefault("MPLBACKEND", "Agg")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import calibrate_reference as cal  # noqa: E402

CASE = "case1"


def write_image(path, w=160, h=120):
    cv2.imwrite(str(path), (np.random.RandomState(0).rand(h, w, 3) * 255).astype("uint8"))
    return str(path)


def quiet(func, *args, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        func(*args, **kw)
    return buf.getvalue()



def setUpModule():
    # plt.show() under the headless Agg backend warns that it cannot show the window: expected here, not a failure
    warnings.filterwarnings("ignore", message="FigureCanvasAgg is non-interactive")


class TestCalibrationSession(unittest.TestCase):
    def test_full_mode_ruler_then_landmarks(self):
        s = cal.Calibration()
        self.assertEqual(s.phase, "ruler")
        s.click(10, 10)
        self.assertEqual(s.phase, "ruler")
        s.click(110, 10)                              # 100 px apart
        self.assertEqual(s.phase, "ruler_input")
        s.click(50, 50)                               # ignored until the length is typed
        self.assertEqual(s.landmark_clicks, [])
        self.assertFalse(s.submit_ruler_mm("not a number"))
        self.assertFalse(s.submit_ruler_mm("0"))
        self.assertTrue(s.submit_ruler_mm("20"))
        self.assertAlmostEqual(s.px_per_mm, 5.0)
        self.assertEqual(s.phase, "landmark")
        s.click(0, 0)
        s.click(0, 60)                                # 60 px = 12 mm
        self.assertEqual(s.phase, "done")
        r = s.result
        self.assertAlmostEqual(r["landmark_mm"], 12.0)
        self.assertAlmostEqual(r["px_per_mm"], 5.0)
        self.assertEqual((r["ruler_mm"], r["landmark_coords_p1"], r["landmark_coords_p2"]), (20.0, (0, 0), (0, 60)))

    def test_landmark_only_mode_uses_the_known_distance(self):
        s = cal.Calibration(landmark_mm=12.0)
        self.assertEqual(s.phase, "landmark")
        s.click(0, 0)
        s.click(0, 90)                                # 90 px for 12 mm
        self.assertEqual(s.phase, "done")
        self.assertAlmostEqual(s.result["px_per_mm"], 7.5)
        self.assertAlmostEqual(s.result["landmark_mm"], 12.0)
        s.click(5, 5)                                 # a click after the end changes nothing
        self.assertEqual(len(s.landmark_clicks), 2)

    def test_two_identical_landmark_clicks_are_not_a_calibration(self):
        s = cal.Calibration(landmark_mm=12.0)
        s.click(40, 40)
        s.click(40, 40)
        self.assertNotEqual(s.phase, "done")          # zero distance would give px/mm = 0
        self.assertEqual(len(s.landmark_clicks), 1)


class TestSaving(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        cal.BASE = self.root
        self.fdir = self.root / "Videos" / CASE / "force_data"
        self.fdir.mkdir(parents=True)
        self.sheet = self.root / "sheet.xlsx"
        wb = openpyxl.Workbook()
        wb.active.append(["Study ID", "Point A start"])
        wb.active.append([CASE, "00:01:00"])
        wb.save(self.sheet)

    def tearDown(self):
        self.tmp.cleanup()

    def full(self, img):
        s = cal.Calibration()
        s.click(10, 10), s.click(110, 10), s.submit_ruler_mm("20")
        s.click(0, 0), s.click(0, 60)
        return s

    def test_full_mode_saves_the_json_and_leaves_the_tracking_sheet_alone(self):
        img = write_image(self.root / "ruler.png")
        before = self.sheet.read_bytes()
        out = quiet(cal.save_calibration, self.full(img), CASE, None, img)
        data = json.loads((self.fdir / f"{CASE}_calibration.json").read_text())
        self.assertEqual((data["mode"], data["px_per_mm"], data["clip"]), ("ruler", 5.0, "calibration"))
        self.assertEqual(data["pipeline_version"], cal.PIPELINE_VERSION)
        self.assertEqual((data["ruler_mm"], data["landmark_mm"]), (20.0, 12.0))
        self.assertEqual(self.sheet.read_bytes(), before)                      # version 2.x edited the sheet in place
        self.assertNotIn("tracking sheet", out)

    def test_landmark_only_saves_a_per_point_file(self):
        img = write_image(self.root / "a.png")
        s = cal.Calibration(landmark_mm=12.0)
        s.click(0, 0), s.click(0, 90)
        quiet(cal.save_calibration, s, CASE, "A", img)
        data = json.loads((self.fdir / f"{CASE}_A_calibration.json").read_text())
        self.assertEqual((data["mode"], data["clip"], data["px_per_mm"]), ("landmark_only", "A", 7.5))

    def test_the_frame_sidecar_is_recorded_so_deviations_can_be_found(self):
        img = write_image(self.root / "A_frame100.png")
        Path(img).with_suffix(".json").write_text(json.dumps(
            {"frame": 100, "video_time_s": 3.333, "is_default_frame": False, "video": "v.mp4"}))
        s = cal.Calibration(landmark_mm=12.0)
        s.click(0, 0), s.click(0, 90)
        quiet(cal.save_calibration, s, CASE, "A", img)
        data = json.loads((self.fdir / f"{CASE}_A_calibration.json").read_text())
        self.assertEqual(data["frame_info"]["frame"], 100)
        self.assertFalse(data["frame_info"]["is_default_frame"])

    def test_a_hand_made_still_has_no_frame_info(self):
        img = write_image(self.root / "still.png")
        s = cal.Calibration(landmark_mm=12.0)
        s.click(0, 0), s.click(0, 90)
        quiet(cal.save_calibration, s, CASE, "A", img)
        data = json.loads((self.fdir / f"{CASE}_A_calibration.json").read_text())
        self.assertIsNone(data["frame_info"])


class TestExitStatus(unittest.TestCase):
    """Closing the window before the calibration is complete must not look like success."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        cal.BASE = self.root
        self.fdir = self.root / "Videos" / CASE / "force_data"
        self.fdir.mkdir(parents=True)
        self.img = write_image(self.root / "still.png")

    def tearDown(self):
        self.tmp.cleanup()

    def test_closing_without_the_clicks_says_nothing_was_saved_and_fails(self):
        for argv in ([self.img, CASE], [self.img, CASE, "A"]):
            with self.subTest(argv=argv):
                if len(argv) == 3:
                    (self.fdir / f"{CASE}_calibration.json").write_text(json.dumps({"landmark_mm": 12.0}))
                with self.assertRaises(SystemExit) as cm:
                    quiet(cal.main, argv)
                self.assertIn("No calibration saved", str(cm.exception.code))
                self.assertNotEqual(cm.exception.code, 0)
                self.assertEqual(sorted(p.name for p in self.fdir.glob("*_calibration.json")),
                                 [f"{CASE}_calibration.json"] if len(argv) == 3 else [])

    def test_unreadable_image_and_missing_base_calibration_are_errors(self):
        with self.assertRaises(SystemExit) as cm:
            quiet(cal.main, [str(self.root / "nope.png"), CASE])
        self.assertIn("cannot read the image", str(cm.exception.code))
        (self.root / "text.png").write_text("not an image")
        with self.assertRaises(SystemExit) as cm:
            quiet(cal.main, [str(self.root / "text.png"), CASE])
        self.assertIn("cannot read the image", str(cm.exception.code))
        with self.assertRaises(SystemExit) as cm:
            quiet(cal.main, [self.img, CASE, "A"])                      # no ruler calibration yet
        self.assertIn("calibration", str(cm.exception.code).lower())

    def test_the_tracking_sheet_option_is_gone(self):
        with self.assertRaises(SystemExit) as cm:
            with contextlib.redirect_stderr(io.StringIO()):
                quiet(cal.main, [self.img, CASE, "--tracking-sheet", "x.xlsx"])
        self.assertEqual(cm.exception.code, 2)

    def test_a_point_must_be_a_to_d(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                quiet(cal.main, [self.img, CASE, "Z"])


class TestWindow(unittest.TestCase):
    """The window glue, driven headlessly: matplotlib's plt.show is replaced by two injected mouse clicks."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        cal.BASE = self.root
        (self.root / "Videos" / CASE / "force_data").mkdir(parents=True)
        self.img = write_image(self.root / "a.png", w=200, h=150)

    def tearDown(self):
        self.tmp.cleanup()

    def click_through(self, points):
        import matplotlib.pyplot as plt
        from matplotlib.backend_bases import MouseEvent
        real_show = plt.show
        seen = {}

        def fake_show(*a, **k):
            fig = plt.gcf()
            ax = fig.axes[0]
            seen["panel"] = len(fig.axes) > 2          # image axes, ruler box, and the reference panel if shown
            seen["axes_width"] = ax.get_position(original=True).width      # before matplotlib shrinks it to the image shape
            for x, y in points:
                px, py = ax.transData.transform((x, y))
                event = MouseEvent("button_press_event", fig.canvas, px, py, button=1)
                fig.canvas.callbacks.process("button_press_event", event)
            seen["title"] = ax.get_title()

        plt.show = fake_show
        try:
            return seen
        finally:
            self._restore = lambda: setattr(plt, "show", real_show)

    def test_two_landmark_clicks_save_the_calibration(self):
        seen = self.click_through([(20, 30), (20, 110)])
        try:
            img = cv2.cvtColor(cv2.imread(self.img), cv2.COLOR_BGR2RGB)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                saved = cal.run_gui(cal.Calibration(landmark_mm=10.0), img, CASE, "A", self.img, None)
        finally:
            self._restore()
        self.assertTrue(saved)
        data = json.loads((self.root / "Videos" / CASE / "force_data" / f"{CASE}_A_calibration.json").read_text())
        self.assertAlmostEqual(data["px_per_mm"], 8.0, delta=0.2)          # 80 px for 10 mm, to the nearest pixel
        self.assertFalse(seen["panel"])
        self.assertEqual(seen["axes_width"], 1.0)
        self.assertTrue(seen["title"].startswith("Done"))

    def test_the_previous_frame_panel_is_drawn_beside_the_frame(self):
        write_image(self.root / "ruler.png", w=200, h=150)
        ref = {"name": "the ruler frame", "image": str(self.root / "ruler.png"), "p1": (10, 20), "p2": (150, 90),
               "missing": None}
        seen = self.click_through([(20, 30), (20, 110)])
        try:
            img = cv2.cvtColor(cv2.imread(self.img), cv2.COLOR_BGR2RGB)
            with contextlib.redirect_stdout(io.StringIO()):
                saved = cal.run_gui(cal.Calibration(landmark_mm=10.0), img, CASE, "A", self.img, ref)
        finally:
            self._restore()
        self.assertTrue(saved)
        self.assertTrue(seen["panel"])
        self.assertLess(seen["axes_width"], 0.8)                              # the frame leaves room for the panel

    def test_a_missing_reference_image_is_shown_as_text_not_an_error(self):
        ref = {"name": "point A", "image": None, "p1": (1, 2), "p2": (3, 4), "missing": "gone.png"}
        self.click_through([(20, 30), (20, 110)])
        try:
            img = cv2.cvtColor(cv2.imread(self.img), cv2.COLOR_BGR2RGB)
            with contextlib.redirect_stdout(io.StringIO()):
                saved = cal.run_gui(cal.Calibration(landmark_mm=10.0), img, CASE, "B", self.img, ref)
        finally:
            self._restore()
        self.assertTrue(saved)

    def test_no_clicks_means_nothing_saved(self):
        self.click_through([])
        try:
            img = cv2.cvtColor(cv2.imread(self.img), cv2.COLOR_BGR2RGB)
            with contextlib.redirect_stdout(io.StringIO()):
                saved = cal.run_gui(cal.Calibration(landmark_mm=10.0), img, CASE, "A", self.img, None)
        finally:
            self._restore()
        self.assertFalse(saved)
        self.assertEqual(list((self.root / "Videos" / CASE / "force_data").iterdir()), [])


class TestPreviousReference(unittest.TestCase):
    """The inset: point A shows the ruler frame, B shows A's, C shows B's, D shows C's; the ruler frame when the
    previous point has not been calibrated."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fdir = self.root / "Videos" / CASE / "force_data"
        self.fdir.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, label, image, p1, p2):
        name = f"{CASE}_calibration.json" if label is None else f"{CASE}_{label}_calibration.json"
        (self.fdir / name).write_text(json.dumps({"calibration_frame": str(image), "landmark_coords_p1": list(p1),
                                                  "landmark_coords_p2": list(p2)}))

    def test_each_point_shows_the_one_before_it(self):
        for name in ("ruler", "a", "b", "c"):
            write_image(self.root / f"{name}.png")
        self.save(None, self.root / "ruler.png", (1, 2), (3, 4))
        self.save("A", self.root / "a.png", (5, 6), (7, 8))
        self.save("B", self.root / "b.png", (9, 10), (11, 12))
        self.save("C", self.root / "c.png", (13, 14), (15, 16))
        names = {lab: cal.previous_reference(CASE, lab, self.root)["name"] for lab in "ABCD"}
        self.assertEqual(names, {"A": "the ruler frame", "B": "point A", "C": "point B", "D": "point C"})
        ref = cal.previous_reference(CASE, "C", self.root)
        self.assertEqual((ref["p1"], ref["p2"], Path(ref["image"]).name), ((9, 10), (11, 12), "b.png"))

    def test_an_uncalibrated_previous_point_falls_back_to_the_ruler_frame(self):
        self.save(None, self.root / "ruler.png", (1, 2), (3, 4))
        self.save("A", self.root / "a.png", (5, 6), (7, 8))              # B is missing
        self.assertEqual(cal.previous_reference(CASE, "C", self.root)["name"], "the ruler frame")
        self.assertEqual(cal.previous_reference(CASE, "D", self.root)["name"], "the ruler frame")

    def test_nothing_to_show_without_any_calibration(self):
        self.assertIsNone(cal.previous_reference(CASE, "A", self.root))

    def test_a_relative_image_path_is_found_from_the_repository_folder(self):
        write_image(self.root / "Videos" / CASE / "ruler.png")
        self.save(None, Path("Videos") / CASE / "ruler.png", (1, 2), (3, 4))
        ref = cal.previous_reference(CASE, "A", self.root)
        self.assertTrue(Path(ref["image"]).exists())

    def test_a_missing_image_is_reported_not_fatal(self):
        self.save(None, self.root / "moved.png", (1, 2), (3, 4))
        ref = cal.previous_reference(CASE, "A", self.root)
        self.assertIsNone(ref["image"])
        self.assertIn("moved.png", ref["missing"])


if __name__ == "__main__":
    unittest.main()
