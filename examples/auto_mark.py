"""
auto_mark.py — A stand-in for the operator, for trying the pipeline on the synthetic sample case.

mark_suture_entry.py needs a person to click the left and right crus entry points on every planned frame.
This script does the same job for the sample case, where the "entry points" are two bright dots: it decodes
each planned frame, finds the two dots, and records the marks through exactly the same code the interactive
tool uses (MarkSession: same plan, same frame table, same storage, same checksums). Use it ONLY on the
sample case. It cannot mark real endoscope images.

Usage:
    python3 examples/auto_mark.py <video.mp4> <case_id> <point>
"""

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import framelib as fl  # noqa: E402
import mark_suture_entry as ms  # noqa: E402


def detect_dots(rgb):
    """[(x, y) of the left dot, (x, y) of the right dot] as intensity-weighted centroids, in pixels."""
    gray = rgb.astype(float).mean(axis=2)
    background = np.median(gray)
    found = []
    for lo, hi in ((0, gray.shape[1] // 2), (gray.shape[1] // 2, gray.shape[1])):
        half = gray[:, lo:hi]
        y, x = np.unravel_index(np.argmax(half), half.shape)
        y0, y1, x0, x1 = max(y - 8, 0), y + 9, max(x - 8, 0), x + 9
        w = np.clip(half[y0:y1, x0:x1] - background, 0, None)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        found.append((lo + float((w * xx).sum() / w.sum()), float((w * yy).sum() / w.sum())))
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mark the sample case automatically (stand-in for the operator).")
    ap.add_argument("video")
    ap.add_argument("case_id")
    ap.add_argument("point")
    ap.add_argument("--version", action="version", version=f"%(prog)s {fl.PIPELINE_VERSION}")
    args = ap.parse_args(argv)
    label = args.point.upper()
    video = Path(args.video)
    if not video.exists():
        sys.exit(f"ERROR: video not found: {video}")

    index, store, params, plan, roles = ms.prepare(video, args.case_id, label)
    px_per_mm = ms.load_px_per_mm(args.case_id, label)
    store.set_video(index)
    store.note_params(label, params)
    store.save()

    n = 0
    with fl.FrameReader(video, index) as reader:
        session = ms.MarkSession(store, label, plan, px_per_mm, index, get_frame=reader.get, roles=roles)
        for pos in range(len(session.order)):
            session.pos, session.clicks = pos, []
            if session.is_marked():
                continue
            (lx, ly), (rx, ry) = detect_dots(reader.get(session.order[pos]))
            session.click(lx, ly)
            session.click(rx, ry)
            n += 1
    marked, skipped, remaining = store.counts(label, plan.frames)
    print(f"Point {label}: marked {n} new frames ({marked} marked, {skipped} skipped, {remaining} not yet marked "
          f"of {len(plan.frames)}) at {px_per_mm:g} px/mm")


if __name__ == "__main__":
    main()
