"""
camera_check.py: the flag rules, the lasting-run detection, and the scale estimate by direct registration to the
calibration frame (run in a child process, as in the pipeline), on synthetic textured images with a known zoom.

Run from the repository root:
    python3 -m unittest discover -s tests -v
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import camera_check as cc  # noqa: E402

H, W = 480, 640


def scene(seed=3):
    """A textured grey scene: a few hundred bright and dark blobs and rectangles on noise, so ORB finds many corners."""
    rng = np.random.RandomState(seed)
    img = rng.normal(110, 6, (H, W))
    yy, xx = np.mgrid[0:H, 0:W]
    for _ in range(220):
        cy, cx, r = rng.randint(0, H), rng.randint(0, W), rng.randint(4, 14)
        img += rng.choice([-1, 1]) * rng.randint(30, 80) * np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2.0 * r * r)))
    for _ in range(60):
        y0, x0 = rng.randint(0, H - 30), rng.randint(0, W - 30)
        img[y0:y0 + rng.randint(6, 28), x0:x0 + rng.randint(6, 28)] += rng.choice([-1, 1]) * rng.randint(25, 60)
    return np.clip(img, 0, 255).astype(np.uint8)


def zoom(img, s):
    """The same scene seen at scale s about the image centre (s > 1 zooms in)."""
    im = Image.fromarray(img)
    if s >= 1:
        cw, ch = W / s, H / s
        box = ((W - cw) / 2, (H - ch) / 2, (W + cw) / 2, (H + ch) / 2)
        return np.asarray(im.resize((W, H), Image.BICUBIC, box=box))
    out = Image.new("L", (W, H), 110)
    small = im.resize((int(W * s), int(H * s)), Image.BICUBIC)
    out.paste(small, ((W - small.width) // 2, (H - small.height) // 2))
    return np.asarray(out)


class TestFlags(unittest.TestCase):
    def test_a_frame_is_flagged_when_its_scale_is_more_than_the_threshold_from_one(self):
        ok = {"scale": 1.04, "inliers": 80}
        self.assertIsNone(cc.frame_flag(ok))
        self.assertEqual(cc.frame_flag({"scale": 1.06, "inliers": 80}), "scale")
        self.assertEqual(cc.frame_flag({"scale": 0.94, "inliers": 80}), "scale")
        self.assertIsNone(cc.frame_flag({"scale": 0.951, "inliers": 80}))
        self.assertEqual(cc.frame_flag({"scale": 1.04, "inliers": 80}, threshold=0.03), "scale")

    def test_an_estimate_with_few_inliers_or_none_at_all_is_unreliable(self):
        self.assertEqual(cc.frame_flag({"scale": 1.0, "inliers": 19}), "unreliable")
        self.assertIsNone(cc.frame_flag({"scale": 1.0, "inliers": 20}))
        self.assertEqual(cc.frame_flag({"scale": None, "inliers": 4}), "unreliable")
        self.assertEqual(cc.frame_flag({"scale": 1.0, "inliers": 10}, min_inliers=5) or "ok", "ok")

    def test_a_clearly_off_scale_is_flagged_even_from_a_rough_estimate(self):
        # 14 matched features is rough, but a scale of 1.29 from them is far more likely a real zoom than a good frame
        self.assertEqual(cc.frame_flag({"scale": 1.29, "inliers": 14}), "scale")
        self.assertEqual(cc.frame_flag({"scale": 1.29, "inliers": cc.ROUGH_FLOOR}), "scale")
        # below the floor nothing can be trusted, whatever the scale says
        self.assertEqual(cc.frame_flag({"scale": 1.29, "inliers": cc.ROUGH_FLOOR - 1}), "unreliable")
        # an in-range scale from a rough estimate cannot confirm the frame is fine
        self.assertEqual(cc.frame_flag({"scale": 1.01, "inliers": 12}), "unreliable")

    def test_no_estimate_means_no_flag(self):
        self.assertIsNone(cc.frame_flag(None))

    def test_the_defaults_are_the_operators(self):
        self.assertEqual((cc.DEFAULT_THRESHOLD, cc.DEFAULT_MIN_INLIERS), (0.05, 20))

    def test_flag_frames_lists_the_flagged_in_plan_order(self):
        est = {1: {"scale": 1.00, "inliers": 90}, 2: {"scale": 0.76, "inliers": 50}, 3: {"scale": 1.01, "inliers": 12},
               4: {"scale": 1.07, "inliers": 60}}
        got = cc.flag_frames([1, 2, 3, 4, 5], est)                          # 5 has no estimate
        self.assertEqual([(g["frame"], g["flag"]) for g in got], [(2, "scale"), (3, "unreliable"), (4, "scale")])

    def test_a_lasting_run_is_consecutive_frames_flagged_at_about_one_scale(self):
        est = {k: {"scale": 0.76 + 0.002 * (k % 3), "inliers": 60} for k in range(10, 20)}      # frames 10 to 19
        est[20] = {"scale": 1.0, "inliers": 80}
        runs = cc.lasting_runs(list(range(5, 25)), est)
        self.assertEqual([(r["first"], r["last"], r["n"]) for r in runs], [(10, 19, 10)])
        self.assertAlmostEqual(runs[0]["scale"], 0.76, delta=0.01)

    def test_a_lasting_run_tolerates_estimation_noise_around_its_median(self):
        # point B of the real test case: 13 consecutive frames between 0.763 and 0.795 (total spread 0.031) are one lasting zoom
        scales = [0.7766, 0.7821, 0.7837, 0.7659, 0.7729, 0.7786, 0.7789, 0.7861, 0.7818, 0.7945, 0.7694, 0.7779, 0.7632]
        est = {100 + i: {"scale": s, "inliers": 100} for i, s in enumerate(scales)}
        runs = cc.lasting_runs(list(range(90, 120)), est)
        self.assertEqual([(r["first"], r["last"], r["n"]) for r in runs], [(100, 112, 13)])

    def test_short_or_scattered_flags_are_not_a_lasting_run(self):
        est = {k: {"scale": 0.76, "inliers": 60} for k in (10, 11, 12)}                         # only three frames
        self.assertEqual(cc.lasting_runs(list(range(5, 25)), est), [])
        est = {k: {"scale": 0.7 + 0.1 * (k % 2), "inliers": 60} for k in range(10, 20)}         # scales do not agree
        self.assertEqual(cc.lasting_runs(list(range(5, 25)), est), [])
        est = {k: {"scale": 0.76, "inliers": 60} for k in range(10, 20) if k != 14}             # a good frame in between
        self.assertEqual(cc.lasting_runs(list(range(5, 25)), est), [])


class TestMask(unittest.TestCase):
    def test_the_mask_keeps_the_scene_and_drops_the_consoles_bars(self):
        m = cc.ui_mask(1024, 1280)                      # as in the prototype: rows 60 to 939 are the scene
        self.assertEqual(m.shape, (1024, 1280))
        self.assertTrue((m[:60] == 0).all() and (m[940:] == 0).all())
        self.assertTrue((m[60:940] == 255).all())

    def test_the_mask_scales_with_the_frame(self):
        m = cc.ui_mask(480, 640)
        self.assertTrue((m[:int(480 * cc.UI_TOP)] == 0).all() and (m[int(480 * cc.UI_BOTTOM):] == 0).all())
        self.assertTrue((m[int(480 * cc.UI_TOP):int(480 * cc.UI_BOTTOM)] == 255).all())


class TestRegistration(unittest.TestCase):
    """The estimate is made by a child process that never imports PyAV (see camera_check.py)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ref = scene()
        cls.ref_path = Path(cls.tmp.name) / "ref.png"
        Image.fromarray(cls.ref).save(cls.ref_path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def estimate(self, frames):
        return cc.estimate_scales(self.ref_path, [(i, f) for i, f in enumerate(frames)])

    def test_the_known_zoom_is_recovered(self):
        factors = [1.00, 1.30, 0.80, 1.06, 0.93]
        got = self.estimate([zoom(self.ref, s) for s in factors])
        for i, s in enumerate(factors):
            self.assertIsNotNone(got[i]["scale"], (s, got[i]))
            self.assertAlmostEqual(got[i]["scale"], s, delta=0.02 * s, msg=f"zoom {s}: {got[i]}")
            self.assertGreaterEqual(got[i]["inliers"], cc.DEFAULT_MIN_INLIERS)

    def test_the_estimate_is_against_the_calibration_frame_not_the_previous_frame(self):
        # a chain would multiply small errors; direct registration gives each frame its own estimate
        factors = [1.0 + 0.01 * k for k in range(25)]
        got = self.estimate([zoom(self.ref, s) for s in factors])
        errs = [abs(got[i]["scale"] - s) / s for i, s in enumerate(factors) if got[i]["scale"] is not None]
        self.assertEqual(len(errs), len(factors))
        self.assertLess(max(errs), 0.02)

    def test_a_featureless_frame_gets_no_estimate_and_is_flagged_unreliable(self):
        blank = np.full((H, W), 128, np.uint8)
        got = self.estimate([blank])
        self.assertIsNone(got[0]["scale"])
        self.assertEqual(cc.frame_flag(got[0]), "unreliable")

    def test_an_unrelated_scene_is_unreliable_not_a_confident_wrong_scale(self):
        got = self.estimate([scene(seed=99)])
        self.assertEqual(cc.frame_flag(got[0]), "unreliable")

    @staticmethod
    def with_console_bars(img, seed=11):
        """The scene with the console's bars on top: screen-fixed, full of high-contrast text-like blocks, so they do not
        zoom with the scene."""
        rng = np.random.RandomState(seed)
        out = img.copy()
        for rows in (slice(0, int(H * 0.05)), slice(int(H * 0.935), H)):
            n = out[rows].shape[0]
            blocks = rng.randint(0, 2, (n // 4 + 1, W // 4)).astype(np.uint8) * 255
            out[rows] = np.kron(blocks, np.ones((4, 4), np.uint8))[:n, :W]
        return out

    def test_the_consoles_screen_fixed_bars_are_masked_out(self):
        # the scene zooms by 1.3 but the bars stay put: unmasked, the bars' many matches at scale 1.0 would hide the zoom
        ref_path = Path(self.tmp.name) / "ref_with_bars.png"
        Image.fromarray(self.with_console_bars(self.ref)).save(ref_path)
        frame = self.with_console_bars(zoom(self.ref, 1.30))
        got = cc.estimate_scales(ref_path, [(0, frame)])
        self.assertIsNotNone(got[0]["scale"])
        self.assertAlmostEqual(got[0]["scale"], 1.30, delta=0.03, msg=str(got[0]))

    def test_a_frame_of_another_size_than_the_calibration_image_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.estimate([self.ref[:240, :320]])
        self.assertIn("native resolution", str(cm.exception))

    def test_a_missing_calibration_image_is_a_clear_error(self):
        with self.assertRaises(ValueError) as cm:
            cc.estimate_scales(Path(self.tmp.name) / "nope.png", [(0, self.ref)])
        self.assertIn("cannot read", str(cm.exception))

    def test_the_same_frames_always_give_the_same_estimates(self):
        # RANSAC is random; the worker seeds it, so a borderline frame cannot flip between two runs
        frames = [zoom(self.ref, s) for s in (1.04, 1.06, 0.94, 1.3)] + [scene(seed=99)]
        first = cc.estimate_scales(self.ref_path, list(enumerate(frames)))
        for _ in range(3):
            self.assertEqual(cc.estimate_scales(self.ref_path, list(enumerate(frames))), first)

    def test_the_child_does_not_load_pyav(self):
        # the whole point of the child process: OpenCV and PyAV never share a process
        code = ("import sys, camera_check; camera_check.estimate_scales(sys.argv[1], []); "
                "print('av' in sys.modules, 'cv2' in sys.modules)")
        out = subprocess.run([sys.executable, "-c", code, str(self.ref_path)], capture_output=True, text=True,
                             cwd=str(Path(__file__).resolve().parents[1]))
        self.assertEqual(out.stdout.split(), ["False", "False"], out.stdout + out.stderr)   # the parent has neither


if __name__ == "__main__":
    unittest.main()
