"""
index_video.py and exact decoding, on a tiny synthetic video made with PyAV (skipped if PyAV is missing).

Run from the repository root:
    python3 -m unittest discover -s tests -v
"""

import contextlib
import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import framelib as fl  # noqa: E402
import index_video as iv  # noqa: E402

try:
    import av
except ImportError:
    av = None

N_FRAMES = 90


def make_video(path, n=N_FRAMES):
    """n frames at 30 fps; frame k is a flat grey of value (3 * k) % 250 so every frame is distinguishable."""
    with av.open(str(path), "w") as c:
        s = c.add_stream("mpeg4", rate=30)
        s.width, s.height, s.pix_fmt = 64, 48, "yuv420p"
        for k in range(n):
            f = av.VideoFrame.from_ndarray(np.full((48, 64, 3), (3 * k) % 250, np.uint8), format="rgb24")
            for pkt in s.encode(f):
                c.mux(pkt)
        for pkt in s.encode():
            c.mux(pkt)


@unittest.skipUnless(av, "PyAV is not installed")
class TestIndexVideo(unittest.TestCase):
    def build(self, root):
        video = Path(root) / "clip.mp4"
        make_video(video)
        iv.BASE = Path(root)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            iv.main([str(video), "case1"])
        return video, Path(root) / "Videos" / "case1" / "force_data", buf.getvalue()

    def test_frame_table_is_written_and_complete(self):
        with tempfile.TemporaryDirectory() as root:
            video, fdir, out = self.build(root)
            table = fl.frame_table_path(fdir, "case1")
            with open(table, newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), N_FRAMES)
            self.assertEqual([int(r["frame"]) for r in rows], list(range(N_FRAMES)))
            self.assertEqual(rows[0]["time_s"], "0.000000")
            times = np.array([float(r["time_s"]) for r in rows])
            self.assertTrue(np.all(np.diff(times) > 0))
            self.assertAlmostEqual(times[1] - times[0], 1 / 30, places=3)
            idx = fl.load_index(fdir, "case1", video)
            self.assertEqual(idx.n, N_FRAMES)
            self.assertIn(f"numbered 0 to {N_FRAMES - 1}", out)
            self.assertIn("Saved:", out)

    def test_decoded_frame_is_the_frame_with_that_number(self):
        with tempfile.TemporaryDirectory() as root:
            video, fdir, _ = self.build(root)
            idx = fl.load_index(fdir, "case1", video)
            with fl.FrameReader(video, idx) as rd:
                for k in (0, 45, 89, 10, 60, 30):            # forward, then backwards seeks
                    grey = float(rd.get(k).mean())
                    self.assertAlmostEqual(grey, (3 * k) % 250, delta=8, msg=f"frame {k}")

    def test_forward_seek_and_cache_give_identical_pixels(self):
        with tempfile.TemporaryDirectory() as root:
            video, fdir, _ = self.build(root)
            idx = fl.load_index(fdir, "case1", video)
            with fl.FrameReader(video, idx) as a:
                first = [fl.frame_crc32(a.get(k)) for k in (20, 25, 80)]
                again = [fl.frame_crc32(a.get(k)) for k in (20, 80)]       # cache hits
            with fl.FrameReader(video, idx) as b:
                fresh = [fl.frame_crc32(b.get(k)) for k in (80, 25, 20)]    # opposite order, seeks only
            self.assertEqual(first, [fresh[2], fresh[1], fresh[0]])
            self.assertEqual(again, [first[0], first[2]])

    def test_missing_video_exits(self):
        with tempfile.TemporaryDirectory() as root:
            iv.BASE = Path(root)
            with self.assertRaises(SystemExit):
                iv.main([str(Path(root) / "nope.mp4"), "case1"])


if __name__ == "__main__":
    unittest.main()
