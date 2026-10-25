"""
The camera check as mark_suture_entry.py runs it: frames decoded exactly with PyAV, registered in a child process to
the point's calibration frame, results stored in the marks, flagged frames and lasting runs reported, and a second
look in --verify. A small textured video with a zoom event stands in for the endoscope video.

Run from the repository root:
    python3 -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import camera_check as cc  # noqa: E402
import framelib as fl  # noqa: E402
import index_video as iv  # noqa: E402
from test_camera_check import H, W, scene, zoom  # noqa: E402

try:
    import av
    import mark_suture_entry as ms
except ImportError:
    av = None

N_FRAMES = 60
ZOOMED = range(30, 42)          # twelve frames at zoom 1.30: a lasting change
ONE_OFF = 50                    # a single frame at zoom 0.88
CAL_FRAME = 10


def write_video(path):
    base = scene()
    with av.open(str(path), "w") as c:
        s = c.add_stream("mpeg4", rate=30)
        s.width, s.height, s.pix_fmt = W, H, "yuv420p"
        s.options = {"qscale": "2"}
        for k in range(N_FRAMES):
            z = 1.30 if k in ZOOMED else 0.88 if k == ONE_OFF else 1.0
            f = av.VideoFrame.from_ndarray(np.stack([zoom(base, z)] * 3, axis=-1), format="rgb24")
            for pkt in s.encode(f):
                c.mux(pkt)
        for pkt in s.encode():
            c.mux(pkt)


def quiet(func, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = func(*a, **k)
    return out, buf.getvalue()


@unittest.skipUnless(av, "PyAV is not installed")
class TestCameraCheckInMarker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.video = root / "clip.mp4"
        write_video(cls.video)
        iv.BASE = root
        quiet(iv.main, [str(cls.video), "case1"])
        cls.fdir = root / "Videos" / "case1" / "force_data"
        cls.index = fl.load_index(cls.fdir, "case1", cls.video)
        with fl.FrameReader(cls.video, cls.index) as r:
            fl.save_frame_png(r.get(CAL_FRAME), root / "cal.png")           # the calibration frame, as exported
        cls.cal = {"px_per_mm": 10.0, "frame": CAL_FRAME, "image": str(root / "cal.png"), "image_stored": str(root / "cal.png")}
        cls.plan = types.SimpleNamespace(frames=list(range(N_FRAMES)))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def store(self):
        d = tempfile.mkdtemp(dir=self.tmp.name)
        return fl.MarksStore(Path(d) / "marks.json", "case1")

    def run_check(self, store, **kw):
        with fl.FrameReader(self.video, self.index) as reader:
            return quiet(ms.ensure_camera_check, reader, store, "A", self.plan, self.cal, **kw)

    def test_estimates_are_stored_for_every_planned_frame_and_the_zoomed_frames_are_flagged(self):
        store = self.store()
        check, out = self.run_check(store)
        self.assertEqual(check, {"threshold": 0.05, "min_inliers": 20})
        scales = {k: store.get_scale("A", k) for k in range(N_FRAMES)}
        self.assertTrue(all(v is not None for v in scales.values()))
        for k in ZOOMED:
            self.assertAlmostEqual(scales[k]["scale"], 1.30, delta=0.04, msg=k)
        self.assertAlmostEqual(scales[ONE_OFF]["scale"], 0.88, delta=0.04)
        for k in (0, 5, 20, 45):
            self.assertAlmostEqual(scales[k]["scale"], 1.0, delta=0.03, msg=k)
        flagged = {f["frame"] for f in cc.flag_frames(self.plan.frames, {k: v for k, v in scales.items()})}
        self.assertEqual(flagged, set(ZOOMED) | {ONE_OFF})
        meta = store.get_scale_check("A")
        self.assertEqual((meta["calibration_frame"], meta["threshold"], meta["min_inliers"]), (CAL_FRAME, 0.05, 20))
        self.assertTrue(Path(meta["calibration_image"]).name == "cal.png")

    def test_the_report_lists_flagged_frames_and_a_lasting_run(self):
        store = self.store()
        check, out = self.run_check(store)
        self.assertIn("13 of 60", out)                                      # 12 zoomed + 1 single frame
        self.assertIn("frame 50", out)                                      # the one-off frame is listed
        self.assertIn("lasting", out)
        self.assertIn(f"{ZOOMED.start} to {ZOOMED.stop - 1}", out)
        self.assertIn("skip", out.lower())

    def test_nothing_is_skipped_by_the_check(self):
        store = self.store()
        self.run_check(store)
        self.assertEqual(store.counts("A", self.plan.frames), (0, 0, N_FRAMES))        # never acts alone

    def test_a_second_run_uses_the_stored_estimates(self):
        store = self.store()
        self.run_check(store)
        real = cc.estimate_scales
        cc.estimate_scales = lambda *a, **k: self.fail("the stored estimates should have been used")
        try:
            check, out = self.run_check(store)
        finally:
            cc.estimate_scales = real
        self.assertEqual(check["threshold"], 0.05)
        self.assertIn("already checked", out)

    def test_a_new_calibration_frame_means_a_new_check(self):
        store = self.store()
        self.run_check(store)
        other = dict(self.cal, frame=11)                                    # re-calibrated on another frame
        with fl.FrameReader(self.video, self.index) as reader:
            quiet(ms.ensure_camera_check, reader, store, "A", self.plan, other)
        self.assertEqual(store.get_scale_check("A")["calibration_frame"], 11)

    def test_only_the_missing_frames_are_estimated_when_the_plan_grows(self):
        store = self.store()
        small = types.SimpleNamespace(frames=list(range(0, 20)))
        with fl.FrameReader(self.video, self.index) as reader:
            quiet(ms.ensure_camera_check, reader, store, "A", small, self.cal)
        seen = []
        real = cc.estimate_scales

        def spy(ref, frames, on_progress=None):
            frames = list(frames)
            seen.extend(k for k, _ in frames)
            return real(ref, frames, on_progress)
        cc.estimate_scales = spy
        try:
            self.run_check(store)
        finally:
            cc.estimate_scales = real
        self.assertEqual(sorted(seen), list(range(20, N_FRAMES)))

    def test_thresholds_can_be_changed(self):
        store = self.store()
        check, out = self.run_check(store, threshold=0.25, min_inliers=10)
        self.assertEqual(check, {"threshold": 0.25, "min_inliers": 10})
        flagged = {f["frame"] for f in cc.flag_frames(self.plan.frames, {k: store.get_scale("A", k) for k in range(N_FRAMES)},
                                                       0.25, 10)}
        self.assertEqual(flagged, set(ZOOMED))                              # 0.88 is within 25%

    def test_a_calibration_image_that_is_gone_means_no_check_and_a_clear_note(self):
        store = self.store()
        gone = dict(self.cal, image=None, image_stored="Videos/case1/calibration_frames/missing.png")
        with fl.FrameReader(self.video, self.index) as reader:
            check, out = quiet(ms.ensure_camera_check, reader, store, "A", self.plan, gone)
        self.assertIsNone(check)
        self.assertIn("calibration image", out)
        self.assertIn("missing.png", out)
        self.assertIsNone(store.get_scale("A", 0))

    def test_a_screenshot_sized_calibration_image_is_refused_with_the_reason(self):
        from PIL import Image
        store = self.store()
        small = Path(self.tmp.name) / "small.png"
        Image.fromarray(np.zeros((100, 120, 3), np.uint8)).save(small)
        wrong = dict(self.cal, image=str(small))
        with self.assertRaises(SystemExit) as cm:
            with fl.FrameReader(self.video, self.index) as reader:
                quiet(ms.ensure_camera_check, reader, store, "A", self.plan, wrong)
        self.assertIn("native resolution", str(cm.exception.code))

    def test_a_camera_check_process_that_dies_is_a_clear_error_not_a_traceback(self):
        store = self.store()
        real = cc.estimate_scales

        def dies(*a, **k):
            raise RuntimeError("the camera-check process stopped unexpectedly: ModuleNotFoundError: No module named 'cv2'")
        cc.estimate_scales = dies
        try:
            with self.assertRaises(SystemExit) as cm:
                self.run_check(store)
        finally:
            cc.estimate_scales = real
        self.assertIn("ERROR", str(cm.exception.code))
        self.assertIn("No module named 'cv2'", str(cm.exception.code))
        self.assertIn("--no-camera-check", str(cm.exception.code))

    def test_verify_rechecks_marked_frames_without_changing_the_marks(self):
        store = self.store()
        self.run_check(store)
        for k in (5, 31, 33):                                               # two marked frames are zoomed ones
            store.put("A", k, {"pts_s": 0.0, "left_crus_px": [0, 0], "right_crus_px": [0, 100], "distance_px": 100.0,
                               "distance_mm": 10.0, "px_per_mm": 10.0, "skipped": False, "source": "manual"})
        store.save()
        before = json.dumps(store.data, sort_keys=True)
        with fl.FrameReader(self.video, self.index) as reader:
            ok, out = quiet(ms.verify_camera, reader, store, "A", self.plan, self.cal)
        self.assertEqual(json.dumps(store.data, sort_keys=True), before)
        self.assertIn("2 of 3 marked frames", out)
        self.assertIn("31", out)
        self.assertFalse(ok)                                                # flagged marked frames: a warning status

    def test_verify_is_quiet_when_every_marked_frame_is_consistent(self):
        store = self.store()
        for k in (3, 4, 20):
            store.put("A", k, {"pts_s": 0.0, "left_crus_px": [0, 0], "right_crus_px": [0, 100], "distance_px": 100.0,
                               "distance_mm": 10.0, "px_per_mm": 10.0, "skipped": False, "source": "manual"})
        with fl.FrameReader(self.video, self.index) as reader:
            ok, out = quiet(ms.verify_camera, reader, store, "A", self.plan, self.cal)
        self.assertTrue(ok)
        self.assertIn("0 of 3 marked frames", out)


if __name__ == "__main__":
    unittest.main()
