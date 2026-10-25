"""
The sample-data run, end to end, in an isolated copy of the repository (so no test writes into your working copy).

It builds the synthetic sample case, runs every stage as its own command-line process, and checks the results against
the truth built into the sample. Skipped if PyAV is not installed. Takes about half a minute.

Run from the repository root:
    python3 -m unittest discover -s tests -v
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import av  # noqa: F401
except ImportError:
    av = None

ROOT = Path(__file__).resolve().parents[1]


def copy_repo(dest):
    shutil.copytree(ROOT, dest, ignore=shutil.ignore_patterns("Videos", "__pycache__", ".DS_Store", "*.xlsx", "tests", ".git"))


@unittest.skipUnless(av, "PyAV is not installed")
class TestSampleCase(unittest.TestCase):
    def run_sample(self, repo, *args):
        return subprocess.run([sys.executable, "examples/run_sample.py", *args], cwd=repo, capture_output=True, text=True)

    def test_whole_pipeline_passes_every_check_and_can_be_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            copy_repo(repo)
            first = self.run_sample(repo, "--fresh", "--quiet")
            self.assertEqual(first.returncode, 0, first.stdout[-2500:] + first.stderr[-1500:])
            self.assertIn("ALL CHECKS PASSED", first.stdout)
            self.assertNotIn("FAIL", first.stdout.replace("SOME CHECKS FAILED", ""))
            again = self.run_sample(repo, "--quiet")                       # re-running resumes and gives the same result
            self.assertEqual(again.returncode, 0, again.stdout[-2500:] + again.stderr[-1500:])
            self.assertIn("ALL CHECKS PASSED", again.stdout)
            fd = repo / "Videos" / "SAMPLE001" / "force_data"
            self.assertTrue((fd / "SAMPLE001_frame_distances.csv").exists())
            self.assertTrue((fd / "SAMPLE001_points_ABCD_force_merged.xlsx").exists())
            self.assertEqual(list(fd.glob("*moduli*")), [])                  # the pipeline no longer fits anything

    def test_refuses_to_touch_a_folder_that_is_not_a_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            copy_repo(repo)
            real = repo / "Videos" / "REAL01"
            real.mkdir(parents=True)
            (real / "keep_me.txt").write_text("real data")
            done = self.run_sample(repo, "REAL01", "--fresh", "--quiet")
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("not a sample case", done.stdout + done.stderr)
            self.assertEqual((real / "keep_me.txt").read_text(), "real data")


if __name__ == "__main__":
    unittest.main()
