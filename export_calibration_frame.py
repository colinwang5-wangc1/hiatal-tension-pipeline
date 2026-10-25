"""
export_calibration_frame.py — Export a point's calibration frame, exactly, from the original video.

Each point A-D is calibrated on ONE frame, and that frame's px/mm is applied to every frame of the point. Which frame
is a judgement: the two landmark vessels must be visible, the camera must be steady and as it is for the measured
frames, and the tissue should not yet be deformed by pulling (that changes the landmark distance and so the px/mm
scale). The scale also changes inside a segment when the camera moves: on the test case the same operator, landmarks
and point gave 10.46 px/mm on the first frame of the buffer and 13.29 on the window start, 5 s later.

pick_calibration_frame.py is the normal tool: it scrubs the point's window and buffer and exports the frame you
choose. This script is the non-interactive version. Without --frame it exports the DEFAULT frame, the first frame of
the buffer: the first frame whose stored time is at or after the window start minus the buffer (the window start
itself when there is no buffer), taken from the Selection sheet that extract_point_forces.py wrote.

It decodes the frame from the ORIGINAL video by its number, with the pipeline's own exact decoder, and saves it as a
lossless PNG at the video's native resolution, so no screenshot (scaled, re-encoded) is needed. Next to the PNG it
writes a .json that records which frame it is and whether it is the default (is_default_frame); calibrate_reference.py
copies that into the calibration JSON (frame_info), so the frame each point was calibrated on can be found afterwards.

The same tool exports the RULER frame of the full calibration (the frame in which a ruler of known length lies in the
field): use the point name "ruler" and give its frame number (--frame N) or its video time (--time HH:MM:SS, the first frame at
or after it). There is no default frame for it.

Needs: index_video.py (the frame table) and, for points A-D, extract_point_forces.py (the Selection sheet).

Usage:
    python3 export_calibration_frame.py <video> <case_id> <point> [--frame N] [--out FILE.png]
    python3 export_calibration_frame.py <video> <case_id> ruler (--frame N | --time HH:MM:SS) [--out FILE.png]

Writes (default):
    Videos/<case_id>/calibration_frames/<case_id>_<point>_frame<N>.png   and   the same name with .json

Then:
    python3 calibrate_reference.py Videos/<case_id>/calibration_frames/<case_id>_<point>_frame<N>.png <case_id> <point>
"""

import argparse
import json
import sys
from pathlib import Path

import framelib as fl

BASE = Path(__file__).resolve().parent
RULER = "RULER"


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
    """The first frame of the buffer: the first frame whose stored time is at or after the window start minus the buffer
    (a frame before it is outside the selected range). A frame within a microsecond before it counts as on it."""
    k = fl.segment_frame_range(index, seg)[0]
    if k >= index.n:
        sys.exit(f"ERROR: the start of the buffer ({seg['start_text']} minus {seg['buffer_s']:g} s) is after the last "
                 "frame of the video")
    return k


def export_frame(video, index, case_id, label, seg, frame, out=None):
    """Decode frame `frame` exactly, write the PNG and its .json. Returns (png path, info dict)."""
    if not 0 <= frame < index.n:
        sys.exit(f"ERROR: frame {frame} is outside the video (0 to {index.n - 1})")
    k0 = default_frame(index, seg) if seg else None
    t = float(index.pts_s[frame])
    with fl.FrameReader(video, index) as reader:
        rgb = reader.get(frame)
    png = Path(out) if out else BASE / "Videos" / case_id / "calibration_frames" / f"{case_id}_{label}_frame{frame}.png"
    fl.save_frame_png(rgb, png)
    info = {
        "pipeline_version": fl.PIPELINE_VERSION, "case": case_id, "point": label, "video": Path(video).name,
        "frame": int(frame), "video_time_s": round(t, 6), "video_time": fl.fmt_time(t),
        "is_default_frame": None if seg is None else frame == k0,
        "default_frame": None if seg is None else int(k0),
        "position": None if seg is None else fl.segment_position(seg, t),
        "seconds_from_window_start": None if seg is None else round(t - seg["start_s"], 3),
        "window": None if seg is None else {"start": seg["start_text"], "end": seg["end_text"],
                                            "buffer_s": seg["buffer_s"]},
        "crc32": f"{fl.frame_crc32(rgb):08x}", "width": int(rgb.shape[1]), "height": int(rgb.shape[0]),
        "exported": fl.utc_now(),
    }
    png.with_suffix(".json").write_text(json.dumps(info, indent=2))
    return png, info


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="the original video the frame table was made from")
    ap.add_argument("case_id")
    ap.add_argument("point", type=str.upper, choices=list("ABCD") + [RULER],
                    help="A-D: that point's calibration frame; ruler: the ruler frame of the full calibration")
    ap.add_argument("--frame", type=int, default=None,
                    help="raw frame number to export instead of the default, the first frame of the buffer "
                         "(ruler: required unless --time)")
    ap.add_argument("--time", default=None, type=str,
                    help="ruler only: video time HH:MM:SS(.mmm); the first frame at or after it is exported")
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
    if label == RULER:
        label = "ruler"
        if (args.frame is None) == (args.time is None):
            sys.exit("ERROR: for the ruler frame give exactly one of --frame N (a frame number) or --time HH:MM:SS")
        if args.time is not None:
            try:
                frame = fl.first_frame_at_or_after(index, fl.parse_hms(args.time))
            except ValueError as e:
                sys.exit(f"ERROR: {e}")
        else:
            frame = args.frame
        png, info = export_frame(video, index, case_id, label, None, frame, args.out)
        print(f"Ruler frame: frame {info['frame']}, video time {info['video_time']}, {info['width']} x {info['height']}, "
              f"CRC32 {info['crc32']}")
        print(f"Saved: {png}")
        print(f"Next: python3 calibrate_reference.py \"{png}\" {case_id}")
        return
    if args.time is not None:
        sys.exit("ERROR: --time is only for the ruler frame; use --frame N to choose a frame of a point")
    seg = point_segment(force_dir, case_id, label)
    frame = default_frame(index, seg) if args.frame is None else args.frame
    png, info = export_frame(video, index, case_id, label, seg, frame, args.out)

    print(f"Point {label}: window starts {seg['start_text']} (video time); frame {info['frame']}, "
          f"video time {info['video_time']}, {info['width']} x {info['height']}, CRC32 {info['crc32']}")
    if info["is_default_frame"]:
        print("This is the first frame of the buffer (the default calibration frame).")
    else:
        print(f"This is not the default (frame {info['default_frame']}, the first frame of the buffer): "
              f"{abs(info['seconds_from_window_start']):.2f} s "
              f"{'before' if info['seconds_from_window_start'] < 0 else 'after'} the window start "
              f"({info['position']}). The deviation is recorded in {png.with_suffix('.json').name}.")
    print(f"Saved: {png}")
    print(f"Next: python3 calibrate_reference.py \"{png}\" {case_id} {label}")


if __name__ == "__main__":
    main()
