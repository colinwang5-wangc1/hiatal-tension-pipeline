"""
verify_force.py  –  OCR force values and timestamps from a screen recording
of the my.intuitive.com video player using Apple Vision.

Usage:
    python3 verify_force.py <screen_recording.mov>
"""

import argparse
import sys
import re
import os
import cv2
import tempfile
import pandas as pd
from pathlib import Path

import framelib


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="screen recording of the my.intuitive.com video player")
    ap.add_argument("--version", action="version", version=f"%(prog)s {framelib.PIPELINE_VERSION}")
    return ap.parse_args(argv)


if __name__ == "__main__":
    ARGS = parse_args()          # --help and --version work without macOS or the Vision packages

try:
    import Vision
    from Foundation import NSURL
except ImportError:
    sys.exit("verify_force.py needs macOS (Apple's Vision framework) and the packages "
             "pyobjc-framework-Cocoa and pyobjc-framework-Vision. It is an optional diagnostic and is not "
             "needed for the rest of the pipeline.")

SAMPLE_EVERY = 10
BASE = Path(__file__).resolve().parent / "Videos"


def ocr_frame(frame):
    tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    cv2.imwrite(tmp.name, frame)
    url = NSURL.fileURLWithPath_(tmp.name)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, {})
    handler.performRequests_error_([req], None)
    lines = [obs.topCandidates_(1)[0].string() for obs in req.results()]
    os.unlink(tmp.name)
    return lines


def extract_force_and_timestamp(lines):
    for i, line in enumerate(lines):
        # Look for a force value "X.XN" or "0N" on its own line
        cleaned = line.strip().replace('o', '0').replace('O', '0')
        vm = re.match(r'^(\d+\.?\d*)\s*[Nn]$', cleaned)
        if not vm:
            continue
        force = float(vm.group(1))
        # Timestamp must be on the next non-empty line
        for j in range(i + 1, min(i + 3, len(lines))):
            if not lines[j].strip():
                continue
            ts_m = re.search(r'(\d{1,2}):(\d{2}):(\d{2})', lines[j])
            if ts_m:
                hh, mm, ss = ts_m.groups()
                if int(mm) <= 59 and int(ss) <= 59:
                    return force, f"{int(hh):02d}:{mm}:{ss}"
            break
    return None, None


def main():
    video_path = ARGS.video
    case = input("Case (the case_id used for the other files, e.g. CASE001): ").strip()

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    n   = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Video: {fps:.0f}fps, {n} frames, {n/fps:.1f}s")
    print(f"Sampling every {SAMPLE_EVERY} frames\n")

    results = []
    frame_idx = 0
    last_ts = None

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % SAMPLE_EVERY == 0:
            print(f"  Processing frame {frame_idx}/{n}...", end="\r", flush=True)
            lines = ocr_frame(frame)
            force, ts = extract_force_and_timestamp(lines)

            if force is not None and ts is not None and ts != last_ts:
                print(f"\n  {ts}  {force:.1f}N")
                results.append({"Timestamp": ts, "Force (N)": force})
                last_ts = ts

        frame_idx += 1

    cap.release()

    if not results:
        print("\nNo readings extracted.")
        sys.exit(1)

    df = pd.DataFrame(results)
    out_dir  = BASE / case
    out_dir.mkdir(exist_ok=True)
    out_xlsx = out_dir / f"{case}_screen_verification.xlsx"
    out_csv  = out_dir / f"{case}_screen_verification.csv"
    df.to_excel(out_xlsx, index=False)
    df.to_csv(out_csv, index=False)
    print(f"\n{len(df)} readings extracted")
    print(f"Saved: {out_xlsx.name}")


if __name__ == "__main__":
    main()
