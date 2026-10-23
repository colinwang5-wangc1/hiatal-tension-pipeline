"""
make_sample_case.py — Build a synthetic sample case (no patient data) for trying the pipeline in a new environment.

Everything is invented and known by construction:
    - a short video (480 x 270, 29.97 fps, so frame times are NOT on a 1/30 s grid) in which two bright dots
      stand in for the left and right crural entry points. The gap between them closes during each of four
      "suture placement" windows (Points A to D) and reopens in between, and the pixel scale (px/mm) changes
      from point to point, as camera depth does in a real case;
    - a force log in the same format as the da Vinci console export (about 1 Hz, with some seconds missing),
      in which force rises in proportion to how far the gap has closed (total modulus 6 N);
    - the tracking spreadsheet with the Point A-D start and end times (whole seconds, as an operator would note);
    - the calibration files that calibrate_reference.py would write after an operator clicked a ruler and landmarks;
    - ground_truth.json with the true gap at every second, so results can be checked.

Writes under Videos/<case_id>/ (the repository's .gitignore keeps Videos/ out of version control):
    <case_id>_video.mp4
    sample_tracking_sheet.xlsx
    ground_truth.json
    force_data/<case_id>_force_raw.json
    force_data/<case_id>_calibration.json and <case_id>_<A-D>_calibration.json

Usage:
    python3 examples/make_sample_case.py [case_id]        (default SAMPLE001)
Then run the whole pipeline on it with:  python3 examples/run_sample.py
"""

import json
import random
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WIDTH, HEIGHT = 480, 270
FPS = Fraction(30000, 1001)
DURATION_S = 150.0
WINDOW_STARTS = {"A": 15, "B": 50, "C": 85, "D": 120}     # whole seconds, video time
WINDOW_LEN = 10
PX_PER_MM = {"A": 8.0, "B": 7.5, "C": 7.0, "D": 6.5}
OPEN_GAP_MM, CLOSED_GAP_MM = 40.0, 12.0
HOLD_S, REOPEN_S = 6, 6
E_USM1, E_USM3 = 4.0, 2.0                                   # N per unit strain; total 6 N


def gap_knots():
    knots = [(0.0, OPEN_GAP_MM)]
    for p, s in WINDOW_STARTS.items():
        e = s + WINDOW_LEN
        knots += [(s, OPEN_GAP_MM), (e, CLOSED_GAP_MM), (e + HOLD_S, CLOSED_GAP_MM), (e + HOLD_S + REOPEN_S, OPEN_GAP_MM)]
    knots.append((DURATION_S + 1, OPEN_GAP_MM))
    return knots


def gap_mm(t, knots=None):
    k = knots or gap_knots()
    return float(np.interp(t, [a for a, _ in k], [b for _, b in k]))


def scale_px_per_mm(t):
    """The scale of the point whose window is nearest in time (the jump happens while the gap is open)."""
    starts = sorted(WINDOW_STARTS.items(), key=lambda kv: kv[1])
    for (p, s), (q, s_next) in zip(starts, starts[1:]):
        if t < (s + WINDOW_LEN + HOLD_S + REOPEN_S + s_next - 5) / 2:
            return PX_PER_MM[p]
    return PX_PER_MM[starts[-1][0]]


def force_n(t, e_arm):
    return e_arm * max(0.0, (OPEN_GAP_MM - gap_mm(t)) / OPEN_GAP_MM)


def render_frame(t, rng):
    """RGB frame at video time t: dark noisy background and two Gaussian dots separated by the true gap."""
    img = 24.0 + rng.normal(0.0, 1.5, (HEIGHT, WIDTH))
    sep = gap_mm(t) * scale_px_per_mm(t)
    cy = HEIGHT / 2
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
    for cx in (WIDTH / 2 - sep / 2, WIDTH / 2 + sep / 2):
        x0, x1 = int(cx) - 12, int(cx) + 13
        y0, y1 = int(cy) - 12, int(cy) + 13
        patch = 210.0 * np.exp(-(((xx[y0:y1, x0:x1] - cx) ** 2) + ((yy[y0:y1, x0:x1] - cy) ** 2)) / (2 * 2.0 ** 2))
        img[y0:y1, x0:x1] += patch
    g = np.clip(img, 0, 255).astype(np.uint8)
    return np.stack([g, g, g], axis=-1)


def write_video(path):
    import av
    n = int(DURATION_S * float(FPS))
    rng = np.random.default_rng(2026)
    with av.open(str(path), "w") as c:
        s = c.add_stream("mpeg4", rate=FPS)
        s.width, s.height, s.pix_fmt = WIDTH, HEIGHT, "yuv420p"
        s.bit_rate = 1_500_000
        for k in range(n):
            t = k / float(FPS)
            frame = av.VideoFrame.from_ndarray(render_frame(t, rng), format="rgb24")
            for pkt in s.encode(frame):
                c.mux(pkt)
        for pkt in s.encode():
            c.mux(pkt)
    return n


def hms(seconds):
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def build(case_id="SAMPLE001", root=ROOT, quiet=False):
    import openpyxl
    root = Path(root)
    case_dir = root / "Videos" / case_id
    fd = case_dir / "force_data"
    fd.mkdir(parents=True, exist_ok=True)
    video = case_dir / f"{case_id}_video.mp4"

    if not quiet:
        print(f"Writing the synthetic video ({DURATION_S:.0f} s at {float(FPS):.3f} fps) ...")
    n_frames = write_video(video)

    # force log: about 1 Hz with some whole seconds missing (a sparse log, like the real one). A second is either
    # logged for both arms or not at all, because a missing arm reading is counted as zero force when the arms
    # are added to give the total.
    rnd = random.Random(7)
    force = {"USM1": [], "USM2": [], "USM3": [], "USM4": []}
    for x in range(1, int(DURATION_S)):
        if rnd.random() < 0.88:
            for arm, e in (("USM1", E_USM1), ("USM3", E_USM3)):
                force[arm].append({"x": x, "y": round(force_n(x, e), 4),
                                   "z": {"sensitivity": "Medium", "instrument": "sample instrument"}})
    (fd / f"{case_id}_force_raw.json").write_text(json.dumps(force))

    # tracking sheet, as an operator would fill it in (whole seconds, video time)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Study ID"] + [f"Point {p} {side}" for p in "ABCD" for side in ("start", "end")])
    ws.append([case_id] + [hms(WINDOW_STARTS[p] + (WINDOW_LEN if side == "end" else 0))
                           for p in "ABCD" for side in ("start", "end")])
    wb.save(case_dir / "sample_tracking_sheet.xlsx")

    # calibration files, in the format calibrate_reference.py writes
    def cal(clip, ppm, mode):
        return {"case": case_id, "clip": clip, "calibration_frame": "(synthetic)", "mode": mode,
                "px_per_mm": ppm, "mm_per_px": round(1 / ppm, 6), "landmark_px": round(10.0 * ppm, 2),
                "landmark_mm": 10.0, "stands_in_for": "an operator clicking a ruler and two landmarks"}
    (fd / f"{case_id}_calibration.json").write_text(json.dumps(cal("calibration", PX_PER_MM["A"], "ruler"), indent=2))
    for p, ppm in PX_PER_MM.items():
        (fd / f"{case_id}_{p}_calibration.json").write_text(json.dumps(cal(p, ppm, "landmark_only"), indent=2))

    truth = {
        "case_id": case_id, "video": {"file": video.name, "frames": n_frames, "fps": float(FPS),
                                      "width": WIDTH, "height": HEIGHT},
        "gap_knots_s_mm": gap_knots(), "px_per_mm": PX_PER_MM, "window_starts_s": WINDOW_STARTS,
        "window_length_s": WINDOW_LEN, "total_modulus_N": E_USM1 + E_USM3,
        "note": "force = modulus * (open gap - gap) / open gap; the gap closes linearly across each window",
    }
    (case_dir / "ground_truth.json").write_text(json.dumps(truth, indent=1))
    if not quiet:
        print(f"Sample case written to {case_dir}")
    return truth


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "SAMPLE001")
