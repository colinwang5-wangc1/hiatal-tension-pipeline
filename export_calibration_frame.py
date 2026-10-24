"""
export_calibration_frame.py — Export a point's calibration frame, exactly, from the original video.

The calibration frame of each point A-D is the FIRST frame of that point's segment: the first frame whose stored
time is at or after the window start noted in the tracking sheet (the Selection sheet that
extract_point_forces.py wrote; a frame before the start is not in the segment). Later frames may
already show the tissue deformed by pulling, which changes the landmark distance and so the px/mm scale
(on the test case the choice of frame moved the scale by 4.5% and 7.0% for two points).

This script decodes that frame from the ORIGINAL video by its number, with the pipeline's own exact decoder, and
saves it as a lossless PNG at the video's native resolution, so no screenshot (scaled, re-encoded) is needed.
Next to the PNG it writes a .json that records which frame it is and whether it is the default; calibrate_reference.py
copies that into the calibration JSON, so a point that was calibrated on another frame can be found afterwards.

Use another frame (--frame N) only when, on the default first frame, (a) the landmark is not visible, or (b) the
camera has moved between that frame and the time the forces are collected. pick_calibration_frame.py scrubs the
segment and exports the frame you choose.

Needs: index_video.py (the frame table) and extract_point_forces.py (the Selection sheet).

Usage:
    python3 export_calibration_frame.py <video> <case_id> <point> [--frame N] [--out FILE.png]

Writes (default):
    Videos/<case_id>/calibration_frames/<case_id>_<point>_frame<N>.png   and   the same name with .json

Then:
    python3 calibrate_reference.py Videos/<case_id>/calibration_frames/<case_id>_<point>_frame<N>.png <case_id> <point>
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

import framelib as fl

BASE = Path(__file__).resolve().parent


def point_segment(force_dir, case_id, label):
    """The segment of a point from the Selection sheet, with clear errors for the earlier stages."""
    workbook = Path(force_dir) / f"{case_id}_points_ABCD_force.xlsx"
    if not workbook.exists():
        sys.exit(f"ERROR: {workbook.name} not found - run extract_point_forces.py {case_id} first "
                 "(it records each point's window start)")
    segs = fl.read_selection(workbook)
    if label not in segs:
        sys.exit(f"ERROR: point {label} is not in the Selection sheet of {workbook.name} "
                 f"(points there: {', '.join(segs) or 'none'}); run extract_point_forces.py {case_id}")
    return segs[label]


def default_frame(index, seg):
    """The first frame of the segment: the first frame whose stored time is at or after the noted window start
    (a frame before the start is not in the segment). A frame within a microsecond before it counts as on it."""
    k = int(np.searchsorted(index.pts_s, seg["start_s"] - 1e-6))
    if k >= index.n:
        sys.exit(f"ERROR: the window start {seg['start_text']} is after the last frame of the video")
    return k


def export_frame(video, index, case_id, label, seg, frame, out=None):
    """Decode frame `frame` exactly, write the PNG and its .json. Returns (png path, info dict)."""
    if not 0 <= frame < index.n:
        sys.exit(f"ERROR: frame {frame} is outside the video (0 to {index.n - 1})")
    k0 = default_frame(index, seg)
    t = float(index.pts_s[frame])
    with fl.FrameReader(video, index) as reader:
        rgb = reader.get(frame)
    png = Path(out) if out else BASE / "Videos" / case_id / "calibration_frames" / f"{case_id}_{label}_frame{frame}.png"
    fl.save_frame_png(rgb, png)
    info = {
        "pipeline_version": fl.PIPELINE_VERSION, "case": case_id, "point": label, "video": Path(video).name,
        "frame": int(frame), "video_time_s": round(t, 6), "video_time": fl.fmt_time(t),
        "default_first_frame": frame == k0, "default_frame": int(k0),
        "position": fl.segment_position(seg, t),
        "seconds_from_window_start": round(t - seg["start_s"], 3),
        "window": {"start": seg["start_text"], "end": seg["end_text"], "buffer_s": seg["buffer_s"]},
        "crc32": f"{fl.frame_crc32(rgb):08x}", "width": int(rgb.shape[1]), "height": int(rgb.shape[0]),
        "exported": fl.utc_now(),
    }
    png.with_suffix(".json").write_text(json.dumps(info, indent=2))
    return png, info


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="the original video the frame table was made from")
    ap.add_argument("case_id")
    ap.add_argument("point", type=str.upper, choices=list("ABCD"))
    ap.add_argument("--frame", type=int, default=None,
                    help="raw frame number to export instead of the first frame of the segment "
                         "(only when the landmark is hidden there or the camera moved)")
    ap.add_argument("--out", default=None, help="output PNG [Videos/<case_id>/calibration_frames/...]")
    ap.add_argument("--version", action="version", version=f"%(prog)s {fl.PIPELINE_VERSION}")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    case_id, label = args.case_id, args.point
    video = Path(args.video)
    if not video.exists():
        sys.exit(f"ERROR: video not found: {video}")
    force_dir = BASE / "Videos" / case_id / "force_data"
    index = fl.load_index(force_dir, case_id, video)
    seg = point_segment(force_dir, case_id, label)
    frame = default_frame(index, seg) if args.frame is None else args.frame
    png, info = export_frame(video, index, case_id, label, seg, frame, args.out)

    print(f"Point {label}: window starts {seg['start_text']} (video time); frame {info['frame']}, "
          f"video time {info['video_time']}, {info['width']} x {info['height']}, CRC32 {info['crc32']}")
    if info["default_first_frame"]:
        print("This is the first frame of the segment (the default calibration frame).")
    else:
        print(f"This is not the default (frame {info['default_frame']}, the first frame of the segment): "
              f"{abs(info['seconds_from_window_start']):.2f} s "
              f"{'before' if info['seconds_from_window_start'] < 0 else 'after'} the window start "
              f"({info['position']}). The deviation is recorded in {png.with_suffix('.json').name}.")
    print(f"Saved: {png}")
    print(f"Next: python3 calibrate_reference.py \"{png}\" {case_id} {label}")


if __name__ == "__main__":
    main()
