"""
Headless tests for the marking logic in mark_suture_entry.py (no display, no video).

Run from the repository root:
    python3 -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import framelib as fl  # noqa: E402
import mark_suture_entry as ms  # noqa: E402
from test_framelib import WINDOWS, synthetic_index  # noqa: E402


def fake_frame(k):
    return np.full((4, 4, 3), k % 251, dtype=np.uint8)


class TestMarkSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = synthetic_index()

    def make(self, d, **params):
        store = fl.MarksStore(Path(d) / "marks.json", "case")
        plan = fl.plan_point(self.idx, WINDOWS["A"], **params)
        return store, plan, ms.MarkSession(store, "A", plan, 10.0, self.idx, get_frame=fake_frame)

    def test_two_clicks_store_a_mark_and_save_it(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            k = s.frame
            s.click(100, 100)
            self.assertFalse(s.is_marked())
            s.click(130, 140)
            rec = store.get("A", k)
            self.assertEqual(rec["distance_px"], 50.0)
            self.assertEqual(rec["distance_mm"], 5.0)
            self.assertEqual(rec["source"], "manual")
            self.assertEqual(rec["frame_crc32"], fl.frame_crc32(fake_frame(k)))
            self.assertAlmostEqual(rec["pts_s"], float(self.idx.pts_s[k]), places=6)
            self.assertTrue((Path(d) / "marks.json").exists())          # saved at once

    def test_extra_click_on_marked_frame_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            s.click(10, 10), s.click(20, 10)
            before = dict(store.get("A", s.frame))
            self.assertFalse(s.click(500, 500))
            self.assertEqual(store.get("A", s.frame), before)
            self.assertIn("redo", s.message)

    def test_undo_then_remark_and_redo(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            k = s.frame
            s.click(0, 0), s.click(30, 40)
            s.undo()                                   # un-marks, keeps the left click pending
            self.assertIsNone(store.get("A", k))
            self.assertEqual(s.clicks, [(0.0, 0.0)])
            s.click(60, 80)
            self.assertEqual(store.get("A", k)["distance_px"], 100.0)
            s.redo()
            self.assertIsNone(store.get("A", k))
            self.assertEqual(s.clicks, [])
            s.click(1, 1)
            s.undo()                                   # undo a pending click
            self.assertEqual(s.clicks, [])

    def test_skip_excludes_frame_and_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            first = s.frame
            s.skip()
            self.assertTrue(store.get("A", first)["skipped"])
            self.assertNotEqual(s.frame, first)        # moved on
            self.assertEqual(s.counts()[:2], (0, 1))
            s.step(-1)
            s.click(0, 0), s.click(0, 10)
            self.assertFalse(store.get("A", first)["skipped"])
            self.assertEqual(store.get("A", first)["distance_mm"], 1.0)

    def test_skip_refuses_on_marked_frame(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            s.click(0, 0), s.click(0, 10)
            k = s.frame
            s.skip()
            self.assertFalse(store.get("A", k).get("skipped"))
            self.assertIn("redo", s.message.lower())

    def test_navigation_and_next_unmarked(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            s.step(-5)
            self.assertEqual(s.pos, 0)
            s.step(+3)
            s.click(0, 0), s.click(0, 10)              # frame 3 marked
            s.step(-3)
            self.assertTrue(s.go_to_next_unmarked())
            self.assertEqual(s.pos, 1)                 # frames 1, 2 are still open; 0 was passed over
            s.pos = len(s.order) - 1
            s.step(+9)
            self.assertEqual(s.pos, len(s.order) - 1)

    def test_ghost_is_nearest_earlier_marked_frame(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            self.assertIsNone(s.ghost())
            s.click(5, 5), s.click(5, 15)
            first = s.frame
            s.step(+1)
            s.skip()                                   # skipped frames are not ghosts
            k, rec = s.ghost()
            self.assertEqual(k, first)
            self.assertEqual(rec["left_crus_px"], [5.0, 5.0])

    def test_kill_and_resume(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            done = []
            for _ in range(3):
                done.append(s.frame)
                s.click(0, 0), s.click(0, 20)
                s.step(+1)
            s.click(50, 50)                            # a half-finished frame is lost, nothing else is
            del s, store                               # "kill" the program
            store2 = fl.MarksStore(Path(d) / "marks.json", "case")
            s2 = ms.MarkSession(store2, "A", plan, 10.0, self.idx, get_frame=fake_frame)
            self.assertEqual(s2.counts(), (3, 0, len(plan.frames) - 3))
            self.assertEqual(s2.frame, plan.frames[3])
            self.assertEqual([store2.get("A", k)["distance_mm"] for k in done], [2.0, 2.0, 2.0])

    def test_denser_pass_resumes_at_new_frames_only(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d, stride=10)
            for _ in range(len(plan.frames)):
                s.click(0, 0), s.click(0, 10)
                s.step(+1)
            n_first = len(plan.frames)
            self.assertEqual(s.counts()[2], 0)
            plan5 = fl.plan_point(self.idx, WINDOWS["A"], stride=5)
            s5 = ms.MarkSession(store, "A", plan5, 10.0, self.idx, get_frame=fake_frame)
            marked, skipped, remaining = s5.counts()
            self.assertEqual((marked, skipped), (n_first, 0))
            self.assertEqual(remaining, len(plan5.frames) - n_first)
            self.assertFalse(s5.is_marked())           # started on a not-yet-marked frame
            s5.click(0, 0), s5.click(0, 30)
            self.assertEqual(store.get("A", s5.order[0])["distance_mm"], 1.0)   # existing mark untouched

    def test_describe_names_the_force_second_and_the_offset(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d, stride=1)
            text = s.describe(251354)                       # the last frame of force second 8378: +14
            self.assertIn("8378", text)
            self.assertIn("+14 f", text)
            self.assertNotIn("8379", text)                  # no other force second uses this frame

    def test_describe_lists_every_force_second_when_a_frame_is_shared(self):
        # cannot happen at the default limit; two samples 0.4 s apart force it
        with tempfile.TemporaryDirectory() as d:
            store = fl.MarksStore(Path(d) / "marks.json", "case")
            plan = fl.plan_point(self.idx, [8378.0, 8378.4], stride=1)
            s = ms.MarkSession(store, "A", plan, 10.0, self.idx, get_frame=fake_frame)
            text = s.describe(plan.shared_frames()[0])
            self.assertEqual(text.count("force s "), 2)     # both force seconds are named


if __name__ == "__main__":
    unittest.main()
