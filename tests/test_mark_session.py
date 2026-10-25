"""
Headless tests for the marking logic in mark_suture_entry.py (no display, no video).

Run from the repository root:
    python3 -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import framelib as fl  # noqa: E402
import mark_suture_entry as ms  # noqa: E402
from test_framelib import WINDOWS, synthetic_index  # noqa: E402


def fake_frame(k):
    return np.full((4, 4, 3), k % 251, dtype=np.uint8)



def setUpModule():
    # plt.show() under the headless Agg backend warns that it cannot show the window: expected here, not a failure
    warnings.filterwarnings("ignore", message="FigureCanvasAgg is non-interactive")


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


class TestSkipReasonsAndWarnings(unittest.TestCase):
    """Skip reasons, the camera flag, frames passed over, and the left/right order warning."""

    @classmethod
    def setUpClass(cls):
        cls.idx = synthetic_index()

    def make(self, d, **kw):
        store = fl.MarksStore(Path(d) / "marks.json", "case")
        plan = fl.plan_point(self.idx, WINDOWS["A"], stride=10)
        return store, plan, ms.MarkSession(store, "A", plan, 10.0, self.idx, get_frame=fake_frame, **kw)

    def test_a_skip_records_its_reason(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            k = s.frame
            s.skip("landmark hidden")
            self.assertEqual(store.get("A", k)["skip_reason"], "landmark hidden")
            self.assertTrue(store.get("A", k)["skipped"])
            k2 = s.frame
            s.skip()                                                   # no reason given: recorded as "other"
            self.assertEqual(store.get("A", k2)["skip_reason"], "other")

    def test_a_mark_records_the_calibration_frame_it_used(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d, calibration_frame=251423)
            k = s.frame
            s.click(0, 0), s.click(0, 50)
            self.assertEqual(store.get("A", k)["calibration_frame"], 251423)

    def test_the_camera_flag_and_the_reason_for_skipping_a_flagged_frame(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d, check={"threshold": 0.05, "min_inliers": 20})
            f0, f1, f2 = plan.frames[0], plan.frames[1], plan.frames[2]
            store.set_scale("A", f0, 0.76, 50)
            store.set_scale("A", f1, 1.01, 80)
            store.set_scale("A", f2, None, 3)
            self.assertEqual((s.camera_flag(f0), s.camera_flag(f1), s.camera_flag(f2)), ("scale", None, "unreliable"))
            self.assertEqual(s.camera_reason(f0), "camera: scale 0.76 vs calibration")
            self.assertEqual(s.camera_reason(f2), "camera")
            self.assertIn("0.76", s.camera_text(f0))
            self.assertIn("suggest", s.camera_text(f0).lower())
            self.assertIn("unreliable", s.camera_text(f2))
            self.assertEqual(s.camera_text(f1), "camera check: scale 1.01 (consistent with the calibration frame)")

    def test_a_rough_estimate_is_flagged_but_not_confidently(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d, check={"threshold": 0.05, "min_inliers": 20})
            k = plan.frames[0]
            store.set_scale("A", k, 0.94, 8)                                   # 8 matched features: a rough estimate
            self.assertEqual(s.camera_flag(k), "scale")
            text = s.camera_text(k)
            self.assertIn("0.94", text)
            self.assertIn("8 matched features", text)
            self.assertIn("look at the frame", text)
            self.assertNotIn("Suggest skipping", text)                         # only a solid estimate gets that suggestion
            store.set_scale("A", k, 0.76, 60)
            self.assertIn("Suggest skipping", s.camera_text(k))

    def test_without_a_camera_check_nothing_is_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            store.set_scale("A", plan.frames[0], 0.5, 90)
            self.assertIsNone(s.camera_flag(plan.frames[0]))
            self.assertEqual(s.camera_text(plan.frames[0]), "")

    def test_leaving_a_frame_without_a_mark_or_skip_is_noticed(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            first = s.frame
            s.step(+1)
            self.assertIn("without a mark or skip", s.message)
            self.assertEqual(s.passed_over(), [first])
            s.step(-1)                                                  # go back and deal with it
            s.skip("other")
            self.assertEqual(s.passed_over(), [])

    def test_a_marked_or_skipped_frame_is_not_passed_over(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            s.click(0, 0), s.click(0, 50)
            s.step(+1)
            s.skip("camera")
            s.step(-1)
            self.assertEqual(s.passed_over(), [])

    def test_n_also_counts_as_leaving_the_frame(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            first = s.frame
            s.go_to_next_unmarked()
            self.assertIn(first, s.passed_over())

    def test_a_flip_of_the_left_and_right_order_is_warned_about(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            s.click(100, 50), s.click(300, 50)                         # left click on the screen's left
            s.step(+1)
            s.click(110, 50), s.click(310, 50)
            self.assertNotIn("flipped", s.message)
            s.step(+1)
            s.click(320, 50), s.click(120, 50)                         # now the "left" click is on the screen's right
            self.assertIn("flipped", s.message)
            self.assertEqual(s.flipped, [plan.frames[2]])
            self.assertAlmostEqual(store.get("A", plan.frames[2])["distance_mm"], 20.0)   # the distance is unchanged

    def test_the_first_marked_frame_has_nothing_to_flip_against(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            s.click(320, 50), s.click(120, 50)
            self.assertNotIn("flipped", s.message)
            self.assertEqual(s.flipped, [])


class TestMarkWindow(unittest.TestCase):
    """The marking window, driven headlessly: matplotlib's plt.show is replaced by injected key presses."""

    @classmethod
    def setUpClass(cls):
        cls.idx = synthetic_index()

    def drive(self, session, keys, calibration_image=None):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backend_bases import KeyEvent
        real_show = plt.show
        seen = {}

        class Reader:
            def get(self, k):
                return np.full((60, 80, 3), k % 251, dtype=np.uint8)

        def fake_show(*a, **k):
            fig = plt.gcf()
            seen["text"] = " ".join(t.get_text() for a_ in fig.axes for t in a_.texts) + " " + " ".join(
                t.get_text() for t in fig.texts)
            for key in keys:
                fig.canvas.callbacks.process("key_press_event", KeyEvent("key_press_event", fig.canvas, key))
            seen["after"] = " ".join(t.get_text() for a_ in fig.axes for t in a_.texts) + " " + " ".join(
                t.get_text() for t in fig.texts)
            seen["titles"] = [a_.get_title() for a_ in fig.axes]
            seen["n_axes"] = len(fig.axes)

        plt.show = fake_show
        try:
            ms.run_gui(session, Reader(), "A", show_ghost=True, calibration_image=calibration_image)
        finally:
            plt.show = real_show
        return seen

    def make(self, d, **kw):
        store = fl.MarksStore(Path(d) / "marks.json", "case")
        plan = fl.plan_point(self.idx, WINDOWS["A"], stride=10)
        return store, plan, ms.MarkSession(store, "A", plan, 10.0, self.idx, get_frame=fake_frame, **kw)

    def test_the_keys_are_always_on_screen_and_space_is_explained(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            seen = self.drive(s, [])
            for needle in ("click", "x skip", "space", "next", "u undo", "r redo", "n next open", "g ghost", "q quit"):
                self.assertIn(needle, seen["text"], needle)
            self.assertIn("without recording", seen["text"].lower())             # what space does: it does not skip

    def test_x_asks_for_a_reason_and_the_next_key_chooses_it(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            k0, k1, k2 = plan.frames[0], plan.frames[1], plan.frames[2]
            seen = self.drive(s, ["x"])
            self.assertIn("Skip reason", seen["after"])
            self.assertIsNone(store.get("A", k0))                               # nothing recorded until a reason is chosen
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            k0, k1, k2 = plan.frames[0], plan.frames[1], plan.frames[2]
            self.drive(s, ["x", "h", "x", "c", "x", "o"])
            self.assertEqual([store.get("A", k)["skip_reason"] for k in (k0, k1, k2)],
                             ["landmark hidden", "camera", "other"])

    def test_enter_and_escape_at_the_prompt(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d)
            k0, k1 = plan.frames[0], plan.frames[1]
            self.drive(s, ["x", "escape", "x", "enter"])                        # cancel, then the default reason
            self.assertEqual(store.get("A", k0)["skip_reason"], "other")
            self.assertIsNone(store.get("A", k1))

    def test_enter_on_a_camera_flagged_frame_skips_it_as_a_camera_frame(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d, check={"threshold": 0.05, "min_inliers": 20})
            k0 = plan.frames[0]
            store.set_scale("A", k0, 0.76, 60)
            self.drive(s, ["x", "enter"])
            self.assertEqual(store.get("A", k0)["skip_reason"], "camera: scale 0.76 vs calibration")

    def test_the_camera_flag_is_shown_with_the_calibration_frame(self):
        with tempfile.TemporaryDirectory() as d:
            store, plan, s = self.make(d, check={"threshold": 0.05, "min_inliers": 20}, calibration_frame=999)
            store.set_scale("A", plan.frames[0], 0.76, 60)
            img = Path(d) / "cal.png"
            from PIL import Image
            Image.fromarray(np.full((60, 80, 3), 200, np.uint8)).save(img)
            seen = self.drive(s, [], calibration_image=str(img))
            self.assertIn("0.76", seen["text"])
            self.assertTrue(any("calibration frame" in t.lower() for t in seen["titles"]), seen["titles"])
            self.assertGreaterEqual(seen["n_axes"], 2)


if __name__ == "__main__":
    unittest.main()
