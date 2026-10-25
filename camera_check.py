"""
camera_check.py — Flag frames whose camera view differs from the point's calibration frame.

The pixel-to-millimetre scale of a point is measured on ONE frame, its calibration frame, and applied to every frame of the
point. If the endoscope zooms or moves inside the segment, the same distance in pixels is a different distance in
millimetres. On the real test case the camera zoomed about 30% in 0.4 s inside one point's buffer, and nothing noticed.

For every planned frame this module estimates the SCALE of the scene relative to the calibration frame, by direct
registration of that frame to the calibration frame (ORB features matched between the two, with the console's top and
bottom user-interface bars masked, then a RANSAC similarity transform; the scale is the transform's scale). It is never
chained from frame to frame, because a chain drifts (on the test case it drifted to 0.74 to 0.79 with no camera
activity). A scale of 1.00 means the same zoom as the calibration frame.

It only FLAGS. A frame is flagged
    * for SCALE when its scale differs from 1 by more than the threshold (default 5%). A rough estimate counts: a scale
      of 1.29 from 14 matched features is more likely a real zoom than a good frame;
    * as UNRELIABLE when no estimate could be made (or fewer than 8 features agree, which nothing can be trusted
      on), or when the scale is in range but rests on fewer than the minimum inliers (default 20), for example when
      instruments fill the view: the frame is not confirmed to be fine, so look at it yourself.
mark_suture_entry.py lists the flagged frames before marking, shows each one beside the calibration frame with its
scale, and suggests skipping it. The operator decides; nothing is skipped without a key press. A lasting change (a long
run of consecutive flagged frames at about the same scale) is reported as a run, because skipping it frame by frame
would not help: it needs its own calibration frame.

OpenCV runs in a CHILD PROCESS. PyAV (which decodes the frames) and OpenCV each bundle their own FFmpeg libraries, and
importing both in one process prints a macOS "implemented in both" warning and can be unstable, so no script of this
pipeline imports both. The parent sends each decoded frame to the child as raw grey pixels and reads one line of JSON
back. This file is that child when run as `python3 camera_check.py --worker <calibration image>`: it is not a
command for users.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

DEFAULT_THRESHOLD = 0.05      # a frame is flagged when its scale differs from the calibration frame's by more than this
DEFAULT_MIN_INLIERS = 20      # an in-range scale from fewer matched features than this is called unreliable
ROUGH_FLOOR = 8               # below this many matched features no scale is trusted, in range or not
LASTING_MIN_FRAMES = 6        # this many consecutive flagged frames at about one scale: a lasting change, not a blip
LASTING_SPREAD = 0.04         # ... and every scale lies within this of the run's median (estimates are noisy)
MIN_MATCHES = 15              # below this many feature matches no transform is attempted
UI_TOP, UI_BOTTOM = 0.0586, 0.9180      # rows kept (fractions of the height): the console's bars are 60 and 84 px of 1024


def ui_mask(h, w):
    """255 where the scene is, 0 on the console's top and bottom bars (60 and 84 px of a 1280 x 1024 frame)."""
    mask = np.zeros((h, w), np.uint8)
    mask[int(UI_TOP * h):int(UI_BOTTOM * h), :] = 255
    return mask


# ----------------------------------------------------------------- flags -------

def frame_flag(estimate, threshold=DEFAULT_THRESHOLD, min_inliers=DEFAULT_MIN_INLIERS):
    """None when the frame is consistent with the calibration frame, else 'scale' or 'unreliable'.

    estimate: {'scale': float or None, 'inliers': int} as stored in the marks, or None when no check was made."""
    if estimate is None:
        return None
    scale, inliers = estimate.get("scale"), estimate.get("inliers", 0)
    if scale is None or inliers < ROUGH_FLOOR:
        return "unreliable"
    if abs(scale - 1.0) > threshold:
        return "scale"
    return "unreliable" if inliers < min_inliers else None


def flag_frames(frames, estimates, threshold=DEFAULT_THRESHOLD, min_inliers=DEFAULT_MIN_INLIERS):
    """[{frame, scale, inliers, flag}] for the flagged frames, in the order of `frames`.

    estimates: {frame: {'scale', 'inliers'}}. Frames without an estimate are not flagged here."""
    out = []
    for k in frames:
        est = estimates.get(k)
        flag = frame_flag(est, threshold, min_inliers)
        if flag:
            out.append({"frame": k, "scale": est.get("scale"), "inliers": est.get("inliers", 0), "flag": flag})
    return out


def lasting_runs(frames, estimates, threshold=DEFAULT_THRESHOLD, min_inliers=DEFAULT_MIN_INLIERS,
                 min_frames=LASTING_MIN_FRAMES, spread=LASTING_SPREAD):
    """Runs of consecutive planned frames that are all flagged for scale at about the same value: a lasting zoom.

    Returns [{first, last, n, scale}] (scale = the median of the run). A run like this should get its own
    calibration frame instead of being skipped frame by frame."""
    runs, current = [], []

    def close():
        if len(current) >= min_frames:
            s = [e["scale"] for e in current]
            if max(abs(v - float(np.median(s))) for v in s) <= spread:
                runs.append({"first": current[0]["frame"], "last": current[-1]["frame"], "n": len(current),
                             "scale": float(np.median(s))})
        current.clear()

    for k in frames:
        est = estimates.get(k)
        if frame_flag(est, threshold, min_inliers) == "scale":
            current.append({"frame": k, "scale": est["scale"]})
        else:
            close()
    close()
    return runs


# ------------------------------------------------- registration (child process) ---

def estimate_scales(reference_path, frames, on_progress=None):
    """Scale of each frame's scene relative to the calibration image: {frame_id: {"scale": float or None, "inliers": int}}.

    frames: iterable of (frame_id, grey 2-D uint8 array) at the calibration image's resolution. The estimate is made
    by a child process running this file, so OpenCV is never imported here (see the module docstring). Raises
    ValueError if the calibration image cannot be read or the frames are not at its resolution."""
    errlog = tempfile.TemporaryFile()
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", str(reference_path)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errlog)
    out = {}
    try:
        ready = _read_reply(proc, errlog)
        if ready.get("error"):
            raise ValueError(ready["error"])
        h, w = ready["shape"]
        for n, (frame_id, gray) in enumerate(frames, 1):
            gray = np.ascontiguousarray(gray, dtype=np.uint8)
            if gray.shape != (h, w):
                raise ValueError(f"the calibration image is {w} x {h} px but the video frames are {gray.shape[1]} x "
                                 f"{gray.shape[0]} px: calibrate on a frame exported at the video's native resolution "
                                 "(export_calibration_frame.py or pick_calibration_frame.py), not a screenshot")
            proc.stdin.write(f"F {int(frame_id)} {h} {w}\n".encode() + gray.tobytes())
            proc.stdin.flush()
            reply = _read_reply(proc, errlog)
            out[frame_id] = {"scale": reply["scale"], "inliers": int(reply["inliers"])}
            if on_progress:
                on_progress(n)
        proc.stdin.write(b"Q\n")
        proc.stdin.flush()
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        proc.wait(timeout=60)
        proc.stdout.close()
        errlog.close()
    return out


def _read_reply(proc, errlog):
    line = proc.stdout.readline()
    if not line:
        errlog.seek(0)
        raise RuntimeError("the camera-check process stopped unexpectedly: "
                           + errlog.read().decode(errors="replace").strip()[-600:])
    return json.loads(line)


def _worker(reference_path):
    """Child process: read the calibration image, then register each frame sent on stdin and reply with one JSON line."""
    import cv2

    def reply(obj):
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    ref = cv2.imread(str(reference_path), cv2.IMREAD_GRAYSCALE)
    if ref is None:
        reply({"error": f"cannot read the calibration image: {reference_path}"})
        return 1
    h, w = ref.shape
    mask = ui_mask(h, w)
    cv2.setRNGSeed(12345)                     # the same frames always give the same estimates
    orb = cv2.ORB_create(4000)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    kp_ref, des_ref = orb.detectAndCompute(ref, mask)
    reply({"ready": True, "shape": [h, w], "reference_features": 0 if des_ref is None else len(des_ref)})
    stdin = sys.stdin.buffer
    while True:
        header = stdin.readline().split()
        if not header or header[0] == b"Q":
            return 0
        _, frame_id, fh, fw = header
        gray = np.frombuffer(stdin.read(int(fh) * int(fw)), np.uint8).reshape(int(fh), int(fw))
        scale, inliers = None, 0
        kp, des = orb.detectAndCompute(gray, mask)
        if des is not None and des_ref is not None:
            pairs = matcher.knnMatch(des_ref, des, k=2)
            good = [a for a, b in (p for p in pairs if len(p) == 2) if a.distance < 0.75 * b.distance]
            inliers = len(good)
            if len(good) >= MIN_MATCHES:
                src = np.float32([kp_ref[m.queryIdx].pt for m in good])
                dst = np.float32([kp[m.trainIdx].pt for m in good])
                M, inl = cv2.estimateAffinePartial2D(src, dst, ransacReprojThreshold=4)
                if M is not None:
                    scale, inliers = round(float(np.hypot(M[0, 0], M[1, 0])), 4), int(inl.sum())
        reply({"frame": int(frame_id), "scale": scale, "inliers": inliers})


def main(argv=None):
    import framelib
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--worker", metavar="CALIBRATION_IMAGE",
                    help="internal: run as the child process that registers frames sent on stdin to this image")
    ap.add_argument("--version", action="version", version=f"%(prog)s {framelib.PIPELINE_VERSION}")
    args = ap.parse_args(argv)
    if args.worker is None:
        ap.print_help()
        return 0
    return _worker(args.worker)


if __name__ == "__main__":
    sys.exit(main())
