"""
add_timestamp.py — Burn HH:MM:SS.mmm timestamp onto each frame of a video.

Usage:
    python3 add_timestamp.py <input.mp4>

Output is saved as <input>_timestamped.mp4 in the same folder.
"""

import sys
import cv2
from pathlib import Path

if "--version" in sys.argv[1:]:
    import framelib
    print(f"{Path(__file__).name} {framelib.PIPELINE_VERSION}")
    sys.exit(0)
if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

INPUT  = sys.argv[1]
p      = Path(INPUT)
OUTPUT = str(p.parent / (p.stem + "_timestamped.mp4"))

cap  = cv2.VideoCapture(INPUT)
fps  = cap.get(cv2.CAP_PROP_FPS)
w    = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
h    = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

writer = cv2.VideoWriter(OUTPUT, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))

print(f"Video: {w}x{h} @ {fps:.0f}fps, {total} frames ({total/fps/3600:.2f}h)")
print("Processing — this will take a while...\n")

i = 0
while True:
    ret, frame = cap.read()
    if not ret:
        break

    secs = i / fps
    hh   = int(secs // 3600)
    mm   = int((secs % 3600) // 60)
    ss   = secs % 60
    ts   = f"{hh:02d}:{mm:02d}:{ss:06.3f}"

    # Black outline + white text for readability over any background
    cv2.putText(frame, ts, (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 4)
    cv2.putText(frame, ts, (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)

    writer.write(frame)
    i += 1

    if i % 1800 == 0:  # every ~60s of video
        pct = 100 * i / total
        print(f"  {ts}  ({pct:.1f}%)", flush=True)

cap.release()
writer.release()
print(f"\nDone. {i} frames written to:\n{OUTPUT}")
