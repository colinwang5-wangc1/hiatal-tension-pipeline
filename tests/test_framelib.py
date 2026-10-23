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


class TestLayouts(unittest.TestCase):
    def test_offsets(self):
        self.assertEqual(fl.layout_offsets(15, 10, "edge"), [-15, -5, 5, 15])
        self.assertEqual(fl.layout_offsets(15, 10, "centred"), [-10, 0, 10])
        self.assertEqual(fl.layout_offsets(15, 5, "edge"), [-15, -10, -5, 0, 5, 10, 15])
        self.assertEqual(fl.layout_offsets(15, 5, "centred"), [-15, -10, -5, 0, 5, 10, 15])
        self.assertEqual(fl.layout_offsets(15, 1, "edge"), list(range(-15, 16)))
        self.assertEqual(fl.layout_offsets(0, 10, "edge"), [0])
        self.assertEqual(fl.layout_offsets(0, 10, "centred"), [0])

    def test_edge_and_centred_cover_stride5(self):
        union = set(fl.layout_offsets(15, 10, "edge")) | set(fl.layout_offsets(15, 10, "centred"))
        self.assertEqual(sorted(union), fl.layout_offsets(15, 5, "edge"))

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            fl.layout_offsets(15, 0)
        with self.assertRaises(ValueError):
            fl.layout_offsets(15, 10, "wide")


class TestSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = synthetic_index()

    def test_centre_frame_is_nearest_pts_not_index_over_fps(self):
        centre, frames = fl.sample_frames(self.idx, 8378, stride=1)
        self.assertEqual(centre, 251340)
        self.assertEqual([f.frame for f in frames], list(range(251325, 251356)))
        self.assertEqual(len(frames), 31)

    def test_stride_layouts_for_one_second(self):
        _, edge = fl.sample_frames(self.idx, 8378, stride=10, layout="edge")
        _, cen = fl.sample_frames(self.idx, 8378, stride=10, layout="centred")
        self.assertEqual([f.frame for f in edge], [251325, 251335, 251345, 251355])
        self.assertEqual([f.frame for f in cen], [251330, 251340, 251350])

    def test_boundary_frames_sit_off_the_exact_500ms(self):
        # the centre frame is a few ms before x, so the -15 frame is just past -500 ms:
        # a hard +/-500 ms PTS cut would have dropped it and kept only 30 frames.
        _, frames = fl.sample_frames(self.idx, 8378, stride=1)
        first, last = frames[0], frames[-1]
        self.assertLess(first.offset_ms, -500.0)
        self.assertLess(last.offset_ms, 500.0)
        self.assertEqual((first.offset_frames, last.offset_frames), (-15, 15))

    def test_unique_frame_counts_per_layout(self):
        expected = {  # (stride, layout) -> unique frames over A..D
            (1, "edge"): 1474, (5, "edge"): 298, (10, "centred"): 147, (10, "edge"): 151,
        }
        for (stride, layout), total in expected.items():
            got = sum(len(fl.plan_point(self.idx, secs, stride=stride, layout=layout).frames)
                      for secs in WINDOWS.values())
            self.assertEqual(got, total, (stride, layout))

    def test_per_point_counts_stride1(self):
        got = {p: len(fl.plan_point(self.idx, s, stride=1).frames) for p, s in WINDOWS.items()}
        self.assertEqual(got, {"A": 301, "B": 331, "C": 481, "D": 361})

    def test_shared_boundary_frame_measured_once(self):
        plan = fl.plan_point(self.idx, WINDOWS["A"], stride=1)
        shared = plan.membership[251355]            # +15 of 8378 and -15 of 8379
        self.assertEqual([(s, o) for s, o, _ in shared], [(8378.0, 15), (8379.0, -15)])
        self.assertEqual(plan.frames.count(251355), 1)

    def test_denser_pass_only_adds_frames(self):
        sparse = set(fl.plan_point(self.idx, WINDOWS["C"], stride=10, layout="centred").frames)
        sparse |= set(fl.plan_point(self.idx, WINDOWS["C"], stride=10, layout="edge").frames)
        dense5 = set(fl.plan_point(self.idx, WINDOWS["C"], stride=5).frames)
        self.assertEqual(sparse, dense5)

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
        self.assertEqual(len(frames), 16)


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
            first = fl.plan_point(idx, WINDOWS["A"], stride=10, layout="edge").frames
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
