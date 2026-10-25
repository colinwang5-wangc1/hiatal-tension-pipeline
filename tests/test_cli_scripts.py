"""
Command-line behaviour of the scripts: --help prints usage, --version prints the pipeline version, and an
unreadable input stops with an error and a non-zero exit status instead of reporting success.

The scripts run as separate processes (the way a user runs them) in an empty temporary folder.

Run from the repository root:
    python3 -m unittest discover -s tests -v
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from test_index_video import make_video       # a small video made with PyAV
except ImportError:
    make_video = None

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text().strip()
ALL_SCRIPTS = ["add_timestamp", "calibrate_reference", "camera_check", "export_calibration_frame", "extract_point_forces",
               "index_video", "mark_suture_entry", "measure_suture", "make_tracking_sheet",
               "merge_distance_force", "parse_force_api", "pick_calibration_frame", "plan_measurements",
               "verify_force"]
HELP_SCRIPTS = ["add_timestamp", "calibrate_reference", "camera_check", "export_calibration_frame", "make_tracking_sheet",
                "measure_suture", "parse_force_api", "pick_calibration_frame", "verify_force"]


def run(script, *args, cwd):
    env = {**os.environ, "MPLBACKEND": "Agg", "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(ROOT / f"{script}.py"), *args], capture_output=True, text=True,
                          cwd=cwd, env=env, timeout=120)


class TestHelpAndVersion(unittest.TestCase):
    def test_help_prints_usage_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            for script in HELP_SCRIPTS:
                with self.subTest(script=script):
                    r = run(script, "--help", cwd=d)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    self.assertTrue(r.stdout.lstrip().startswith("usage:"), r.stdout[:200])
                    self.assertNotIn("Traceback", r.stdout + r.stderr)
                    self.assertEqual(list(Path(d).iterdir()), [])                 # --help writes nothing

    def test_every_script_reports_the_pipeline_version(self):
        with tempfile.TemporaryDirectory() as d:
            for script in ALL_SCRIPTS:
                with self.subTest(script=script):
                    r = run(script, "--version", cwd=d)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    self.assertEqual((r.stdout + r.stderr).split()[-1], VERSION)


class TestAddTimestamp(unittest.TestCase):
    """B4: add_timestamp.py used to say 'Done. 0 frames written' and exit 0 for a video it could not read."""

    def test_a_missing_or_unreadable_video_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "text.mp4").write_text("this is not a video")
            for name in ("missing.mp4", "text.mp4"):
                with self.subTest(video=name):
                    r = run("add_timestamp", str(Path(d) / name), cwd=d)
                    self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                    self.assertIn("cannot read", r.stdout + r.stderr)
                    self.assertNotIn("Done", r.stdout)
                    self.assertFalse((Path(d) / (Path(name).stem + "_timestamped.mp4")).exists())

    @unittest.skipIf(make_video is None or not hasattr(os, "geteuid") or os.geteuid() == 0,
                     "needs PyAV and a user whose file permissions are enforced")
    def test_an_output_that_cannot_be_written_is_an_error(self):
        # the same silent success happened where OpenCV has no mp4 writer (opencv-python on Python 3.9 on macOS)
        with tempfile.TemporaryDirectory() as d:
            ro = Path(d) / "readonly"
            ro.mkdir()
            make_video(ro / "clip.mp4")
            os.chmod(ro, 0o555)
            try:
                r = run("add_timestamp", str(ro / "clip.mp4"), cwd=d)
            finally:
                os.chmod(ro, 0o755)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("cannot write", r.stdout + r.stderr)
            self.assertNotIn("Done", r.stdout)

    def test_a_readable_video_still_works(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "tiny.mp4"
            w = cv2.VideoWriter(str(src), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (64, 48))
            if not w.isOpened():
                self.skipTest("this OpenCV build cannot write mp4v")
            for i in range(6):
                w.write(np.full((48, 64, 3), 10 * i, np.uint8))
            w.release()
            r = run("add_timestamp", str(src), cwd=d)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("6 frames written", r.stdout)
            self.assertTrue((Path(d) / "tiny_timestamped.mp4").exists())


class TestImageScripts(unittest.TestCase):
    def test_an_unreadable_image_is_an_error_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            cases = {"measure_suture": ["missing.png"]}
            for script, args in cases.items():
                with self.subTest(script=script):
                    r = run(script, *args, cwd=d)
                    self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                    self.assertNotIn("Traceback", r.stdout + r.stderr)
                    self.assertTrue("cannot read" in r.stdout + r.stderr or "not found" in r.stdout + r.stderr,
                                    r.stdout + r.stderr)


class TestParseForceApi(unittest.TestCase):
    def test_it_names_every_file_it_writes_with_its_folder(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "case1_force_raw.json").write_text(json.dumps({
                "USM1": [{"x": 5, "y": 1.5, "z": {"sensitivity": "Medium", "instrument": "driver"}}, {"x": 6, "y": 0.0, "z": None}],
                "USM2": [], "USM3": [], "USM4": []}))
            r = run("parse_force_api", str(Path(d) / "case1_force_raw.json"), "case1", cwd=d)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            for name in ("case1_USM1_force.xlsx", "case1_USM1_force.csv", "case1_all_arms_force.xlsx"):
                self.assertIn(str(Path(d) / name), r.stdout, name)


    def test_missing_input_is_still_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            r = run("parse_force_api", str(Path(d) / "nope.json"), cwd=d)
            self.assertEqual(r.returncode, 1)
            self.assertIn("not found", r.stdout + r.stderr)

    def test_no_arguments_prints_usage_and_fails(self):
        with tempfile.TemporaryDirectory() as d:
            r = run("parse_force_api", cwd=d)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("usage:", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
