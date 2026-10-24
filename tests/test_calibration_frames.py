"""
export_calibration_frame.py (the exact first frame of a point's segment, D2) and the stepping logic of
pick_calibration_frame.py (choosing another frame when the default is unusable, D3), on a tiny synthetic video
made with PyAV (skipped if PyAV is missing). No display is needed.

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
from pathlib import Path

import numpy as np
import openpyxl

os.environ.setdefault("MPLBACKEND", "Agg")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import framelib as fl  # noqa: E402
import index_video as iv  # noqa: E402
from test_index_video import make_video  # noqa: E402

try:
    import av  # noqa: F401
    from PIL import Image
except ImportError:
    av = None
if av:
    import export_calibration_frame as ecf  # noqa: E402
    import pick_calibration_frame as pcf  # noqa: E402

CASE = "case1"


def quiet(func, *args, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        func(*args, **kw)
    return buf.getvalue()


def build_case(root, start="00:00:01", end="00:00:02", buffer_s=0.5):
    """A 90-frame video (frame k is a flat grey of (3k) % 250), its frame table, and a force workbook whose
    Selection sheet records point A's window (video time 1 s to 2 s) the way extract_point_forces.py does."""
    root = Path(root)
    fdir = root / "Videos" / CASE / "force_data"
    fdir.mkdir(parents=True)
    video = root / "clip.mp4"
    make_video(video)
    iv.BASE = root
    quiet(iv.main, [str(video), CASE])
    wb = openpyxl.Workbook()
    wb.active.title = "Point A"
    wb.active.append(["Timestamp", "Seconds", "USM1", "In Window", "Role"])
    sel = wb.create_sheet("Selection")
    sel.append(["Point", "Start (as entered)", "End (as entered)", "Buffer (s)", "Time offset (s)",
                "Window rows", "Buffer-before rows", "Buffer-after rows", "Force seconds kept"])
    sel.append(["A", start, end, buffer_s, 0.0, 2, 1, 1, "0 to 3"])
    wb.save(fdir / f"{CASE}_points_ABCD_force.xlsx")
    ecf.BASE = pcf.BASE = root
    return video, fdir


class TestSegmentHelpers(unittest.TestCase):
    def test_parse_hms(self):
        self.assertEqual(fl.parse_hms("02:19:38"), 8378.0)
        self.assertEqual(fl.parse_hms("00:00:01.250"), 1.25)
        self.assertEqual(fl.parse_hms("12.5"), 12.5)
        with self.assertRaises(ValueError):
            fl.parse_hms("soon")

    def test_position_of_a_time_in_the_segment(self):
        seg = {"start_s": 10.0, "end_s": 20.0, "buffer_s": 5.0}
        self.assertEqual(fl.segment_position(seg, 10.0), "window")
        self.assertEqual(fl.segment_position(seg, 20.0), "window")
        self.assertEqual(fl.segment_position(seg, 9.99), "buffer-before")
        self.assertEqual(fl.segment_position(seg, 5.0), "buffer-before")
        self.assertEqual(fl.segment_position(seg, 20.01), "buffer-after")
        self.assertEqual(fl.segment_position(seg, 4.99), "outside the selected range")
        self.assertEqual(fl.segment_position(seg, 25.01), "outside the selected range")


@unittest.skipUnless(av, "PyAV or Pillow is not installed")
class TestSelectionSheet(unittest.TestCase):
    def test_the_selection_sheet_gives_the_segment_of_each_point(self):
        with tempfile.TemporaryDirectory() as root:
            video, fdir = build_case(root)
            segs = fl.read_selection(fdir / f"{CASE}_points_ABCD_force.xlsx")
            self.assertEqual(set(segs), {"A"})
            self.assertEqual((segs["A"]["start_s"], segs["A"]["end_s"], segs["A"]["buffer_s"]), (1.0, 2.0, 0.5))
            self.assertEqual(segs["A"]["start_text"], "00:00:01")

    def test_a_workbook_without_a_selection_sheet_gives_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            wb = openpyxl.Workbook()
            wb.save(Path(root) / "w.xlsx")
            self.assertEqual(fl.read_selection(Path(root) / "w.xlsx"), {})


@unittest.skipUnless(av, "PyAV or Pillow is not installed")
class TestExportCalibrationFrame(unittest.TestCase):
    def png(self, root, name):
        return Path(root) / "Videos" / CASE / "calibration_frames" / name

    def test_default_is_the_first_frame_of_the_segment_at_native_resolution(self):
        with tempfile.TemporaryDirectory() as root:
            video, fdir = build_case(root)
            out = quiet(ecf.main, [str(video), CASE, "A"])
            path = self.png(root, f"{CASE}_A_frame30.png")                     # video time 1.000 s = frame 30
            self.assertTrue(path.exists(), out)
            img = np.asarray(Image.open(path).convert("RGB"))
            self.assertEqual(img.shape, (48, 64, 3))                           # the video's own size
            idx = fl.load_index(fdir, CASE, video)
            with fl.FrameReader(video, idx) as reader:
                self.assertTrue(np.array_equal(img, reader.get(30)))          # lossless: the decoded frame itself
            info = json.loads(path.with_suffix(".json").read_text())
            self.assertEqual((info["frame"], info["default_first_frame"], info["default_frame"]), (30, True, 30))
            self.assertEqual(info["position"], "window")
            self.assertEqual(info["crc32"], f"{fl.frame_crc32(img):08x}")
            self.assertEqual((info["case"], info["point"], info["pipeline_version"]),
                             (CASE, "A", fl.PIPELINE_VERSION))
            self.assertIn("first frame of the segment", out)

    def test_the_default_is_never_before_the_noted_start(self):
        # a start between two frames: 1.010 s lies 10 ms after frame 30 (1.000 s) and 23 ms before frame 31 (1.033 s).
        # The nearest frame is 30, which is before the segment; the first frame of the segment is 31.
        with tempfile.TemporaryDirectory() as root:
            video, fdir = build_case(root, start="00:00:01.010")
            quiet(ecf.main, [str(video), CASE, "A"])
            path = self.png(root, f"{CASE}_A_frame31.png")
            self.assertTrue(path.exists())
            info = json.loads(path.with_suffix(".json").read_text())
            self.assertEqual((info["frame"], info["default_first_frame"], info["position"]), (31, True, "window"))
            self.assertGreaterEqual(info["video_time_s"], 1.010)

    def test_a_start_exactly_on_a_frame_uses_that_frame(self):
        with tempfile.TemporaryDirectory() as root:
            video, fdir = build_case(root, start="00:00:01")
            quiet(ecf.main, [str(video), CASE, "A"])
            self.assertTrue(self.png(root, f"{CASE}_A_frame30.png").exists())

    def test_another_frame_is_recorded_as_a_deviation(self):
        with tempfile.TemporaryDirectory() as root:
            video, fdir = build_case(root)
            out = quiet(ecf.main, [str(video), CASE, "A", "--frame", "20"])
            path = self.png(root, f"{CASE}_A_frame20.png")
            info = json.loads(path.with_suffix(".json").read_text())
            self.assertEqual((info["frame"], info["default_first_frame"], info["default_frame"]), (20, False, 30))
            self.assertEqual(info["position"], "buffer-before")
            self.assertAlmostEqual(info["seconds_from_window_start"], -0.333, places=2)
            self.assertIn("not the default", out)
            self.assertFalse(self.png(root, f"{CASE}_A_frame30.png").exists())       # only what was asked for

    def test_the_sidecar_sits_next_to_the_png_under_the_name_calibrate_reference_reads(self):
        # calibrate_reference.read_frame_info(png) opens png.with_suffix(".json") (see test_calibration.py);
        # it is not imported here because OpenCV and PyAV do not share a process well on macOS.
        with tempfile.TemporaryDirectory() as root:
            video, fdir = build_case(root)
            quiet(ecf.main, [str(video), CASE, "A", "--frame", "20"])
            side = self.png(root, f"{CASE}_A_frame20.png").with_suffix(".json")
            info = json.loads(side.read_text())
            self.assertEqual((info["frame"], info["default_first_frame"]), (20, False))

    def test_explicit_output_path(self):
        with tempfile.TemporaryDirectory() as root:
            video, fdir = build_case(root)
            target = Path(root) / "mine" / "still.png"
            quiet(ecf.main, [str(video), CASE, "A", "--out", str(target)])
            self.assertTrue(target.exists())
            self.assertTrue(target.with_suffix(".json").exists())

    def test_the_ruler_frame_is_exported_by_frame_number_or_time(self):
        with tempfile.TemporaryDirectory() as root:
            video, fdir = build_case(root)
            quiet(ecf.main, [str(video), CASE, "ruler", "--frame", "40"])
            path = self.png(root, f"{CASE}_ruler_frame40.png")
            info = json.loads(path.with_suffix(".json").read_text())
            self.assertEqual((info["point"], info["frame"], info["default_first_frame"]), ("ruler", 40, None))
            idx = fl.load_index(fdir, CASE, video)
            with fl.FrameReader(video, idx) as reader:
                self.assertTrue(np.array_equal(np.asarray(Image.open(path).convert("RGB")), reader.get(40)))
            out = quiet(ecf.main, [str(video), CASE, "RULER", "--time", "00:00:01.5"])      # first frame at or after 1.5 s
            self.assertTrue(self.png(root, f"{CASE}_ruler_frame45.png").exists(), out)

    def test_the_ruler_frame_needs_a_frame_or_a_time_and_a_point_needs_neither_a_time(self):
        with tempfile.TemporaryDirectory() as root:
            video, fdir = build_case(root)
            with self.assertRaises(SystemExit) as cm:
                quiet(ecf.main, [str(video), CASE, "ruler"])
            self.assertIn("--frame", str(cm.exception.code))
            with self.assertRaises(SystemExit) as cm:
                quiet(ecf.main, [str(video), CASE, "A", "--time", "00:00:01"])
            self.assertIn("ruler", str(cm.exception.code))

    def test_clear_errors(self):
        with tempfile.TemporaryDirectory() as root:
            video, fdir = build_case(root)
            for argv, expect in (([str(video), CASE, "A", "--frame", "500"], "outside the video"),
                                 ([str(video), CASE, "A", "--frame", "-1"], "outside the video"),
                                 ([str(video), CASE, "C"], "extract_point_forces.py")):
                with self.subTest(argv=argv):
                    with self.assertRaises(SystemExit) as cm:
                        quiet(ecf.main, argv)
                    self.assertIn(expect, str(cm.exception.code))
            (fdir / f"{CASE}_points_ABCD_force.xlsx").unlink()
            with self.assertRaises(SystemExit) as cm:
                quiet(ecf.main, [str(video), CASE, "A"])
            self.assertIn("extract_point_forces.py", str(cm.exception.code))
            fl.frame_table_path(fdir, CASE).unlink()
            with self.assertRaises(SystemExit) as cm:
                quiet(ecf.main, [str(video), CASE, "A"])
            self.assertIn("index_video.py", str(cm.exception.code))


@unittest.skipUnless(av, "PyAV or Pillow is not installed")
class TestFramePicker(unittest.TestCase):
    """The stepping logic behind the scrubbing window."""

    def make(self, root, **kw):
        video, fdir = build_case(root)
        idx = fl.load_index(fdir, CASE, video)
        seg = fl.read_selection(fdir / f"{CASE}_points_ABCD_force.xlsx")["A"]
        return pcf.FramePicker(idx, seg, **kw), idx

    def test_it_starts_on_the_default_first_frame(self):
        with tempfile.TemporaryDirectory() as root:
            p, idx = self.make(root)
            self.assertEqual((p.frame, p.default_frame), (30, 30))
            self.assertTrue(p.on_default())
            self.assertEqual((p.lo, p.hi), (15, 75))                             # 0.5 s buffer before 1 s and after 2 s

    def test_steps_clamp_to_the_selected_range(self):
        with tempfile.TemporaryDirectory() as root:
            p, _ = self.make(root)
            p.step(+1)
            self.assertEqual(p.frame, 31)
            p.step(-10)
            self.assertEqual(p.frame, 21)
            p.step(-100)
            self.assertEqual(p.frame, 15)                                        # not before the buffer
            p.step(+1000)
            self.assertEqual(p.frame, 75)

    def test_seconds_use_the_stored_frame_times(self):
        with tempfile.TemporaryDirectory() as root:
            p, idx = self.make(root)
            p.step_seconds(+1)
            self.assertEqual(p.frame, 60)                                        # 2.000 s
            p.step_seconds(-1)
            self.assertEqual(p.frame, 30)

    def test_default_key_returns_to_the_first_frame(self):
        with tempfile.TemporaryDirectory() as root:
            p, _ = self.make(root)
            p.step(+25)
            self.assertFalse(p.on_default())
            p.to_default()
            self.assertEqual(p.frame, 30)

    def test_label_names_time_frame_and_position(self):
        with tempfile.TemporaryDirectory() as root:
            p, idx = self.make(root)
            self.assertIn("frame 30", p.label())
            self.assertIn("00:00:01.000", p.label())
            self.assertIn("window", p.label())
            self.assertIn("default first frame", p.label())
            p.step(-10)
            self.assertIn("buffer-before", p.label())
            self.assertIn("0.33 s before the window start", p.label())
            self.assertNotIn("default first frame", p.label())

    def test_keys_move_the_frame_and_enter_exports_it(self):
        with tempfile.TemporaryDirectory() as root:
            video, fdir = build_case(root)
            idx = fl.load_index(fdir, CASE, video)
            seg = fl.read_selection(fdir / f"{CASE}_points_ABCD_force.xlsx")["A"]
            picker = pcf.FramePicker(idx, seg)
            exported = []
            with fl.FrameReader(video, idx) as reader:
                fig, on_key, state = pcf.make_window(picker, reader, lambda k: exported.append(k) or f"frame{k}.png")
                for key, frame in (("right", 31), ("shift+left", 21), ("up", 51), ("down", 21), ("d", 30),
                                   ("left", 29), ("x", 29)):                       # an unknown key changes nothing
                    on_key(type("E", (), {"key": key})())
                    self.assertEqual(picker.frame, frame, key)
                on_key(type("E", (), {"key": "enter"})())
            self.assertEqual((exported, state["exported"], state["quit"]), ([29], "frame29.png", False))

    def test_q_quits_without_exporting(self):
        with tempfile.TemporaryDirectory() as root:
            video, fdir = build_case(root)
            idx = fl.load_index(fdir, CASE, video)
            seg = fl.read_selection(fdir / f"{CASE}_points_ABCD_force.xlsx")["A"]
            with fl.FrameReader(video, idx) as reader:
                fig, on_key, state = pcf.make_window(pcf.FramePicker(idx, seg), reader, lambda k: "never")
                on_key(type("E", (), {"key": "q"})())
            self.assertEqual((state["exported"], state["quit"]), (None, True))

    def test_closing_the_window_without_exporting_is_an_error(self):
        # no display here, so plt.show() returns at once: the same situation as closing the window early
        with tempfile.TemporaryDirectory() as root:
            video, fdir = build_case(root)
            with self.assertRaises(SystemExit) as cm:
                with contextlib.redirect_stdout(io.StringIO()):
                    pcf.main([str(video), CASE, "A"])
            self.assertIn("No frame exported", str(cm.exception.code))
            self.assertFalse((Path(root) / "Videos" / CASE / "calibration_frames").exists())

    def test_a_start_frame_outside_the_range_is_pulled_in(self):
        with tempfile.TemporaryDirectory() as root:
            p, _ = self.make(root, start_frame=2)
            self.assertEqual(p.frame, 15)


if __name__ == "__main__":
    unittest.main()
