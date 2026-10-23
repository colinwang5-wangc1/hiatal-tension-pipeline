"""
index_video.py — Read the stored timestamp of every frame of the raw video into a frame table.

Stage 1 of the pipeline. Every frame of a video file carries a presentation timestamp (PTS) in the
file's metadata. This script reads those timestamps (it does not decode any pictures, so it takes
seconds) and writes them out, so every later stage identifies frames by their true timestamp instead
of assuming frame number / fps.

Writes (new files; the video is not modified):
    Videos/<case_id>/force_data/<case_id>_frame_times.csv    one row per frame:
        frame      frame number, starting at 0, in presentation order
        pts        the stored timestamp, in time-base ticks (an integer)
        time_s     video time in seconds; the first frame is time 0
        time_hms   the same as HH:MM:SS.mmm
        keyframe   1 for keyframes (decoding can start there)
    Videos/<case_id>/force_data/<case_id>_frame_times.json   video name and size, time base, summary

Video time is the number a media player shows for that frame when playing from the start, so
times noted while scrubbing in a normal player (e.g. QuickTime) are on this clock.

Needs PyAV (pip install av).

Usage:
    python3 index_video.py <video.mp4> <case_id>
"""

import argparse
import sys
from pathlib import Path

import numpy as np

import framelib as fl

BASE = Path(__file__).resolve().parent


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write a frame table (frame number and stored time) for a video.")
    ap.add_argument("video")
    ap.add_argument("case_id")
    ap.add_argument("--version", action="version", version=f"%(prog)s {fl.PIPELINE_VERSION}")
    args = ap.parse_args(argv)

    video = Path(args.video)
    if not video.exists():
        sys.exit(f"ERROR: video not found: {video}")
    force_dir = BASE / "Videos" / args.case_id / "force_data"
    out = fl.frame_table_path(force_dir, args.case_id)

    print(f"Reading frame timestamps from {video.name} ...")
    idx = fl.build_frame_index(video)
    idx.save(out)
    s = idx.summary()

    h, rem = divmod(int(s["duration_s"]), 3600)
    m, sec = divmod(rem, 60)
    print(f"  frames:            {s['frames']}  (numbered 0 to {s['frames'] - 1})")
    print(f"  duration:          {h:d}:{m:02d}:{sec:02d} ({s['duration_s']:.3f} s)")
    print(f"  mean frame rate:   {s['mean_fps']:.6f} fps (mean gap {s['mean_gap_ms']:.4f} ms)")
    print(f"  frame gaps:        {s['gap_min_ms']:.3f} to {s['gap_max_ms']:.3f} ms")
    print(f"  keyframes:         {s['keyframes']}")
    if idx.pts[0] != 0:
        print(f"  note: the first frame's stored timestamp is {idx.pts[0] * idx.tb_num / idx.tb_den:.6f} s; "
              "video time is measured from the first frame")
    gaps = np.diff(idx.pts_s)
    if len(gaps):
        irregular = int(np.sum(np.abs(gaps - np.median(gaps)) > 0.5 * np.median(gaps)))
        if irregular:
            print(f"  WARNING: {irregular} frame gaps differ from the typical gap by more than 50% "
                  "(dropped frames or a variable frame rate); positions in time do not follow frame number / fps")
    print(f"Saved: {out}")
    print(f"Saved: {out.with_suffix('.json')}")


if __name__ == "__main__":
    main()
