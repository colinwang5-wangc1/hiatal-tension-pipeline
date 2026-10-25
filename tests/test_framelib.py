"""
Tests for framelib.py (frame selection, mark storage, time formatting).

Run from the repository root:
    python3 -m unittest discover -s tests -v

The synthetic video has a 1/153600 time base and a mean frame gap of 33.33332 ms
(30.000011 fps) with the small +/-2 tick wobble seen in real h264 files, so frame
timestamps are NOT on an exact 1/30 s grid.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import framelib as fl  # noqa: E402

TB_DEN = 153600
N_FRAMES = 260_000


def synthetic_index(n=N_FRAMES):
    k = np.arange(n)
    pts = np.floor(k * 5119.99817).astype(np.int64) + np.array([0, 2, -2])[k % 3]
    return fl.FrameIndex(pts, k % 300 == 0, 1, TB_DEN, "synthetic.mp4", 0, 0)


# contiguous force seconds in four windows
WINDOWS = {
    "A": range(8378, 8388),
    "B": range(8413, 8424),
    "C": range(8453, 8469),
    "D": range(8490, 8502),
}


CFR = {  # constant-frame-rate videos: name -> (time base denominator, ticks per frame)
    "30": (60000, 2000), "29.97": (60000, 2002), "25": (60000, 2400),
    "24": (60000, 2500), "60": (60000, 1000), "59.94": (60000, 1001),
}


def cfr_index(name, n=6000):
    den, step = CFR[name]
    k = np.arange(n)
    return fl.FrameIndex(k * step, k % 300 == 0, 1, den, f"cfr{name}.mp4", 0, 0)


class TestLayouts(unittest.TestCase):
    def test_offsets_are_multiples_of_the_stride_around_the_centre(self):
        self.assertEqual(fl.layout_offsets(14, 10), [-10, 0, 10])
        self.assertEqual(fl.layout_offsets(14, 5), [-10, -5, 0, 5, 10])
        self.assertEqual(fl.layout_offsets(14, 1), list(range(-14, 15)))
        self.assertEqual(fl.layout_offsets(0, 10), [0])
        self.assertEqual(fl.layout_offsets(9, 10), [0])

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            fl.layout_offsets(14, 0)
        with self.assertRaises(ValueError):
            fl.layout_offsets(-1, 10)

    def test_the_edge_layout_is_gone(self):
        # under the limit it would give lopsided offsets (-14, -4, +6 at stride 10)
        with self.assertRaises(ValueError):
            fl.resolve_params(layout="edge")
        with self.assertRaises(ValueError):
            fl.sample_frames(synthetic_index(2000), 20, layout="edge")


class TestHalfWindowLimit(unittest.TestCase):
    """No frame may serve two force seconds: every offset is strictly less than half the force-sample spacing."""
    LIMITS = {"30": 14, "29.97": 14, "25": 12, "24": 11, "60": 29, "59.94": 29}

    @classmethod
    def setUpClass(cls):
        cls.idx = synthetic_index()

    def test_limit_follows_the_frame_rate(self):
        for name, limit in self.LIMITS.items():
            self.assertEqual(fl.max_half_window_frames(cfr_index(name)), limit, name)
        self.assertEqual(fl.max_half_window_frames(synthetic_index(2000)), 14)     # 30.000011 fps

    def test_default_half_window_is_the_limit(self):
        _, frames = fl.sample_frames(self.idx, 8378, stride=1)
        self.assertEqual((frames[0].offset_frames, frames[-1].offset_frames, len(frames)), (-14, 14, 29))
        for stride, offsets in ((10, [-10, 0, 10]), (5, [-10, -5, 0, 5, 10])):
            _, f = fl.sample_frames(self.idx, 8378, stride=stride)
            self.assertEqual([x.offset_frames for x in f], offsets)

    def test_a_half_window_over_the_limit_is_refused_at_the_limit_it_is_not(self):
        for h in (15, 20, 30):
            with self.assertRaises(ValueError) as cm:
                fl.sample_frames(self.idx, 8378, half_window_frames=h)
            self.assertIn("14", str(cm.exception))
        _, frames = fl.sample_frames(self.idx, 8378, half_window_frames=14, stride=1)
        self.assertEqual(len(frames), 29)

    def test_no_frame_serves_two_force_seconds_at_any_stride_and_frame_rate(self):
        for name in self.LIMITS:
            idx = cfr_index(name)
            for stride in (1, 5, 10):
                plan = fl.plan_point(idx, range(5, 60), stride=stride)
                self.assertEqual(plan.shared_frames(), [], (name, stride))
                slots = sum(len(f) for _, f in plan.samples.values())
                self.assertEqual(len(plan.frames), slots, (name, stride))      # every slot is its own frame
        for stride in (1, 5, 10):                                                # and on the real-looking timestamps
            for secs in WINDOWS.values():
                self.assertEqual(fl.plan_point(self.idx, secs, stride=stride).shared_frames(), [])

    def test_sharing_is_detected_when_force_seconds_are_too_close(self):
        plan = fl.plan_point(self.idx, [8378.0, 8378.4], stride=1)               # 12 frames apart
        self.assertTrue(plan.shared_frames())


class TestSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = synthetic_index()

    def test_centre_frame_is_nearest_pts_not_index_over_fps(self):
        centre, frames = fl.sample_frames(self.idx, 8378, stride=1)
        self.assertEqual(centre, 251340)
        self.assertEqual([f.frame for f in frames], list(range(251326, 251355)))
        self.assertEqual(len(frames), 29)

    def test_stride_offsets_for_one_second(self):
        _, s10 = fl.sample_frames(self.idx, 8378, stride=10)
        _, s5 = fl.sample_frames(self.idx, 8378, stride=5)
        self.assertEqual([f.frame for f in s10], [251330, 251340, 251350])
        self.assertEqual([f.frame for f in s5], [251330, 251335, 251340, 251345, 251350])

    def test_every_frame_is_within_half_a_second_of_its_force_second(self):
        _, frames = fl.sample_frames(self.idx, 8378, stride=1)
        self.assertTrue(all(abs(f.offset_ms) < 500.0 for f in frames))
        self.assertEqual((frames[0].offset_frames, frames[-1].offset_frames), (-14, 14))

    def test_unique_frame_counts_per_stride(self):
        expected = {1: 1421, 5: 245, 10: 147}          # 49 force seconds x 29, 5, 3 frames: none shared
        for stride, total in expected.items():
            got = sum(len(fl.plan_point(self.idx, secs, stride=stride).frames) for secs in WINDOWS.values())
            self.assertEqual(got, total, stride)

    def test_per_point_counts_stride1(self):
        got = {p: len(fl.plan_point(self.idx, s, stride=1).frames) for p, s in WINDOWS.items()}
        self.assertEqual(got, {"A": 290, "B": 319, "C": 464, "D": 348})

    def test_denser_pass_only_adds_frames(self):
        sparse = set(fl.plan_point(self.idx, WINDOWS["C"], stride=10).frames)
        dense5 = set(fl.plan_point(self.idx, WINDOWS["C"], stride=5).frames)
        dense1 = set(fl.plan_point(self.idx, WINDOWS["C"], stride=1).frames)
        self.assertTrue(sparse < dense5 < dense1)

    def test_time_offset_and_centre_shift(self):
        c0, _ = fl.sample_frames(self.idx, 8378)
        c_shift, _ = fl.sample_frames(self.idx, 8378, window_center_shift_s=0.5)
        c_off, _ = fl.sample_frames(self.idx, 8378, time_offset_s=-1.0)
        self.assertEqual(c_shift - c0, 15)
        self.assertEqual(c0 - c_off, 30)

    def test_outside_video(self):
        self.assertEqual(fl.sample_frames(self.idx, 99999), (None, []))
        self.assertEqual(fl.sample_frames(self.idx, -5), (None, []))

    def test_window_clipped_at_start(self):
        centre, frames = fl.sample_frames(self.idx, 0.0, stride=1)
        self.assertEqual(centre, 0)
        self.assertEqual(frames[0].frame, 0)
        self.assertEqual(len(frames), 15)


class TestIndexFile(unittest.TestCase):
    def test_roundtrip_and_staleness(self):
        with tempfile.TemporaryDirectory() as d:
            video = Path(d) / "v.mp4"
            video.write_bytes(b"x" * 100)
            src = synthetic_index(1000)
            src.source_size = video.stat().st_size
            f = fl.frame_table_path(d, "case1")
            src.save(f)
            self.assertEqual(f.name, "case1_frame_times.csv")
            back = fl.load_index(d, "case1", video)
            self.assertTrue(np.array_equal(back.pts, src.pts))
            self.assertTrue(np.array_equal(back.key, src.key))
            self.assertTrue(np.allclose(back.pts_s, src.pts_s))
            video.write_bytes(b"y" * 200)
            with self.assertRaises(SystemExit):
                fl.load_index(d, "case1", video)

    def test_csv_is_readable_and_numbered_from_zero(self):
        with tempfile.TemporaryDirectory() as d:
            f = fl.frame_table_path(d, "case1")
            synthetic_index(40).save(f)
            lines = f.read_text().splitlines()
            self.assertEqual(lines[0], "frame,pts,time_s,time_hms,keyframe")
            first, second = lines[1].split(","), lines[2].split(",")
            self.assertEqual((first[0], first[1], first[2], first[3], first[4]), ("0", "0", "0.000000", "00:00:00.000", "1"))
            self.assertEqual(second[0], "1")
            self.assertAlmostEqual(float(second[2]), synthetic_index(40).pts_s[1], places=6)
            self.assertEqual(len(lines), 41)
            meta = json.loads(f.with_suffix(".json").read_text())
            self.assertEqual(meta["frames"], 40)
            self.assertEqual(meta["pipeline_version"], fl.PIPELINE_VERSION)
            self.assertIn("mean_fps", meta)

    def test_missing_table_says_to_run_index_video(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit) as cm:
                fl.load_index(d, "case1")
            self.assertIn("index_video.py", str(cm.exception))


class TestHalfWindow(unittest.TestCase):
    def test_seconds_to_frames_follows_the_frame_rate(self):
        idx30 = synthetic_index(2000)
        self.assertEqual(fl.half_window_frames_from_seconds(idx30, 0.5), 15)
        k = np.arange(2000)
        idx60 = fl.FrameIndex(k * 2560, k % 300 == 0, 1, TB_DEN, "v60.mp4", 0, 0)      # 60 fps
        self.assertEqual(fl.half_window_frames_from_seconds(idx60, 0.5), 30)
        self.assertEqual(fl.half_window_frames_from_seconds(idx30, 0), 0)
        with self.assertRaises(ValueError):
            fl.half_window_frames_from_seconds(idx30, -1)


class TestVersioning(unittest.TestCase):
    def test_copies_of_the_scripts_without_the_VERSION_file_stop_with_a_clear_message(self):
        import subprocess
        import shutil
        root = Path(fl.__file__).parent
        with tempfile.TemporaryDirectory() as d:
            shutil.copy(root / "framelib.py", d)
            r = subprocess.run([sys.executable, "-c", "import framelib"], cwd=d, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("VERSION", r.stderr)
            self.assertIn("whole folder", r.stderr)
            shutil.copy(root / "VERSION", d)
            ok = subprocess.run([sys.executable, "-c", "import framelib; print(framelib.PIPELINE_VERSION)"],
                                cwd=d, capture_output=True, text=True)
            self.assertEqual(ok.stdout.strip(), (root / "VERSION").read_text().strip())

    def test_version_file_is_read(self):
        self.assertRegex(fl.PIPELINE_VERSION, r"^\d+\.\d+\.\d+$")
        self.assertEqual(fl.PIPELINE_VERSION, (Path(fl.__file__).parent / "VERSION").read_text().strip())

    def test_major_version_mismatch_is_refused(self):
        major = int(fl.PIPELINE_VERSION.split(".")[0])
        fl.check_major_version(f"{major}.9.9", "same major")             # accepted
        fl.check_major_version(None, "unstamped")                        # accepted
        with self.assertRaises(SystemExit):
            fl.check_major_version(f"{major + 1}.0.0", "other major")

    def test_marks_file_is_stamped_and_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "marks.json"
            s = fl.MarksStore(p, "case")
            s.save()
            self.assertEqual(json.loads(p.read_text())["pipeline_version"], fl.PIPELINE_VERSION)
            data = json.loads(p.read_text())
            data["pipeline_version"] = f"{int(fl.PIPELINE_VERSION.split('.')[0]) + 1}.0.0"
            p.write_text(json.dumps(data))
            with self.assertRaises(SystemExit):
                fl.MarksStore(p, "case")


class TestSelectedRows(unittest.TestCase):
    def make(self, d, with_role):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Point A"
        ws.append(["Timestamp", "Seconds", "USM1", "In Window"] + (["Role"] if with_role else []))
        rows = [(98, "", "buffer-before"), (99, "", "buffer-before"), (100, "YES", "window"), (101, "YES", "window"),
                (102, "", "buffer-after")]
        for x, yes, role in rows:
            ws.append([fl.fmt_time(x), float(x), 1.0, yes] + ([role] if with_role else []))
        path = Path(d) / "force.xlsx"
        wb.save(path)
        return path

    def test_roles_are_read(self):
        with tempfile.TemporaryDirectory() as d:
            rows, legacy = fl.selected_force_rows(self.make(d, True), "A")
            self.assertFalse(legacy)
            self.assertEqual(rows, [(98.0, "buffer-before"), (99.0, "buffer-before"), (100.0, "window"),
                                    (101.0, "window"), (102.0, "buffer-after")])

    def test_legacy_workbook_uses_in_window_rows_only(self):
        with tempfile.TemporaryDirectory() as d:
            rows, legacy = fl.selected_force_rows(self.make(d, False), "A")
            self.assertTrue(legacy)
            self.assertEqual(rows, [(100.0, "window"), (101.0, "window")])

    def test_missing_sheet(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                fl.selected_force_rows(self.make(d, True), "B")


class TestMarksStore(unittest.TestCase):
    def rec(self, d=26.0):
        return {"pts_s": 1.0, "left_crus_px": [1, 2], "right_crus_px": [3, 4], "distance_px": d * 10,
                "distance_mm": d, "px_per_mm": 10.0, "skipped": False, "source": "manual"}

    def test_resume_after_kill(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "marks.json"
            s = fl.MarksStore(p, "case")
            s.put("A", 100, self.rec())
            s.save()
            s.put("A", 110, self.rec(27.0))
            s.save()
            # a crash mid-write leaves a stray temp file; the real file must stay valid
            (Path(d) / "marks.json.tmp").write_text("{ broken")
            s2 = fl.MarksStore(p, "case")
            self.assertEqual(s2.counts("A", [100, 110, 120]), (2, 0, 1))
            self.assertEqual(s2.get("A", 110)["distance_mm"], 27.0)
            self.assertTrue((Path(d) / "marks.json.bak").exists())

    def test_skip_delete_and_counts(self):
        with tempfile.TemporaryDirectory() as d:
            s = fl.MarksStore(Path(d) / "m.json", "case")
            s.put("B", 5, self.rec())
            s.put("B", 6, {"skipped": True, "pts_s": 0.2, "source": "manual"})
            self.assertEqual(s.counts("B", [5, 6, 7]), (1, 1, 1))
            s.delete("B", 5)
            self.assertEqual(s.counts("B", [5, 6, 7]), (0, 1, 2))

    def test_params_history_only_on_change(self):
        with tempfile.TemporaryDirectory() as d:
            s = fl.MarksStore(Path(d) / "m.json", "case")
            p = fl.resolve_params()
            s.note_params("A", p)
            s.note_params("A", p)
            self.assertEqual(len(s.point("A")["params_history"]), 1)
            s.note_params("A", fl.resolve_params(stride=5))
            self.assertEqual(len(s.point("A")["params_history"]), 2)
            self.assertEqual(s.last_params("A")["stride"], 5)

    def test_denser_pass_leaves_existing_marks(self):
        idx = synthetic_index()
        with tempfile.TemporaryDirectory() as d:
            s = fl.MarksStore(Path(d) / "m.json", "case")
            first = fl.plan_point(idx, WINDOWS["A"], stride=10).frames
            for k in first:
                s.put("A", k, self.rec())
            dense = fl.plan_point(idx, WINDOWS["A"], stride=5).frames
            marked, skipped, remaining = s.counts("A", dense)
            self.assertEqual((marked, skipped), (len(first), 0))
            self.assertEqual(remaining, len(dense) - len(first))
            self.assertTrue(set(first) <= set(dense))


class TestTimeFormat(unittest.TestCase):
    def test_no_sixty_second_artifact(self):
        self.assertEqual(fl.fmt_time(59.9996), "00:01:00.000")
        self.assertEqual(fl.fmt_time(8377.996934), "02:19:37.997")
        self.assertEqual(fl.fmt_time(0), "00:00:00.000")


if __name__ == "__main__":
    unittest.main()
