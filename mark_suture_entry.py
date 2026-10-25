"""
mark_suture_entry.py — Manually mark the crural entry points on every video frame
that could correspond to each force sample, so the distance at each force second
comes with an uncertainty instead of resting on one frame.

For every selected force second (window and buffer rows from extract_point_forces.py), frames
are chosen around it by their true timestamps (see framelib.py): the centre frame is the one whose
stored timestamp is nearest the force second (+ time offsets), and the sampled frames are that frame
plus a set of frame offsets (the stride set by plan_measurements.py, always strictly fewer than
half the spacing of the force samples, so every frame belongs to one force second). Each raw
frame is marked once. Frames are decoded exactly
from the RAW video; the time shown on screen is the frame's stored timestamp. The title also says
whether each force second is a window row or a buffer row.

On each frame: click the LEFT crus entry point, then the RIGHT crus entry point (always in that order).
The mark is saved at once. Marks are keyed by raw frame number, so a later run with a
denser stride only adds the frames not yet marked.

Before the window opens, the camera check (camera_check.py) compares every planned frame with the point's
calibration frame and lists the frames whose scale differs by more than 5% or whose estimate is unreliable.
It never skips anything itself: in the window each flagged frame is shown with the calibration frame beside it
and a suggestion, and the operator decides.

Keys (always shown at the bottom of the window)
    click      left crus, then right crus   (a third click on a marked frame is ignored)
    x          skip the frame as unusable; asks why: c camera, h landmark hidden, o other,
               Enter the default (camera on a flagged frame, else other), Esc cancel
    ->  / space   next frame WITHOUT marking or skipping it (it stays "not marked")
    <-         previous frame
    u          undo the last click (or the last mark)
    r          redo: clear this frame and mark it again
    n          jump to the next frame that is not marked or skipped
    g          show / hide the previous marked frame's points as faint "ghosts"
    q          quit (everything is already saved; frames passed over without a mark or skip are listed)

Needs, in this order:
    index_video.py             the frame table of the video
    extract_point_forces.py    the force samples to measure
    plan_measurements.py       the stride for each point (the measurement plan)
    calibrate_reference.py <calibration frame.png> <case_id> <point>    px/mm for the point

Results (the marks file is created, then updated after every action):
    Videos/<case_id>/force_data/<case_id>_frame_marks.json   per-frame marks, skip reasons, the calibration frame
                                                             used, the camera-check scale of every planned frame,
                                                             and the parameters

Usage:
    python3 mark_suture_entry.py <video.mp4> <case_id> <point> [options]

Options (the measurement plan supplies the defaults; options given here override it and are recorded):
    --half-window-frames N   frames on each side of the centre frame; at most 14 at 30 fps (strictly less than
                             half the spacing of the force samples, so no frame serves two force seconds)
    --stride N               spacing of sampled frames, in frames: offsets 0, +/-N, +/-2N, ... within the half-window
    --time-offset-s S        video time minus force time (clock offset)
    --window-center-shift-s S  shift the window centre. The pipeline assumes a force sample at second x is the
                             centre of that second. If the console means the second that starts at x, the frames
                             sit half a second early and +0.5 corrects it. Not verified: see the README, "Timing
                             convention"
    --list                   print the frame plan and progress, then exit
    --verify                 re-decode this point's marked frames, check their CRCs, and run the camera check on them
    --no-ghost               start with ghost marks hidden
    --no-camera-check        do not run the camera check
    --camera-threshold F     flag frames whose scale differs from the calibration frame's by more than F [0.05]
    --camera-min-inliers N   call an in-range estimate from fewer matched features unreliable [20]

Example:
    python3 mark_suture_entry.py Videos/<case_id>/<video file>.mp4 <case_id> A
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

import camera_check as cc
import framelib as fl

BASE = Path(__file__).resolve().parent


# ---------------------------------------------------------------- inputs --------

def force_rows(case_id, label):
    """[(force second, role)] to measure for this point (from extract_point_forces.py)."""
    path = BASE / "Videos" / case_id / "force_data" / f"{case_id}_points_ABCD_force.xlsx"
    if not path.exists():
        sys.exit(f"ERROR: {path.name} not found - run extract_point_forces.py first")
    rows, legacy = fl.selected_force_rows(path, label)
    if legacy:
        print("NOTE: the force workbook has no Role column (made by an older extraction), so only its 'In Window' "
              "rows are measured. Re-run extract_point_forces.py to include the buffer rows.")
    if not rows:
        sys.exit(f"ERROR: no force rows to measure for point {label} in {path.name}")
    return sorted(rows)


def load_calibration(case_id, label):
    """This point's calibration: {px_per_mm, frame (raw frame number it was made on, or None), image (path or None if the
    file is gone), image_stored (the path as written in the calibration file)}."""
    path = BASE / "Videos" / case_id / "force_data" / f"{case_id}_{label}_calibration.json"
    if not path.exists():
        sys.exit(f"ERROR: calibration file not found: {path}\n"
                 f"       make it with: python3 calibrate_reference.py <calibration frame.png> {case_id} {label}")
    with open(path) as f:
        cal = json.load(f)
    stored = cal.get("calibration_frame")
    return {"px_per_mm": float(cal["px_per_mm"]), "frame": (cal.get("frame_info") or {}).get("frame"),
            "image": fl.resolve_image(stored, BASE) if stored else None, "image_stored": stored}


def load_px_per_mm(case_id, label):
    return load_calibration(case_id, label)["px_per_mm"]


# --------------------------------------------------------------- session --------

class MarkSession:
    """Marking state for one point. No display code: every action autosaves."""

    def __init__(self, store, label, plan, px_per_mm, index, get_frame=None, roles=None, calibration_frame=None,
                 check=None):
        self.store, self.label, self.plan, self.px_per_mm = store, label, plan, px_per_mm
        self.index = index
        self.get_frame = get_frame            # k -> RGB array (only needed to store a CRC)
        self.roles = roles or {}              # force second -> window | buffer-before | buffer-after
        self.calibration_frame = calibration_frame     # raw frame number the px/mm came from (None if unknown)
        self.check = check or {}              # camera check settings ({threshold, min_inliers}); empty: no check was run
        self.order = plan.frames
        self.clicks = []
        self.pos = 0
        self.message = ""
        self.left_open = set()                # frames stepped away from with no mark and no skip
        self.flipped = []                     # frames whose left/right click order differs from the previous marked frame
        self.go_to_next_unmarked(include_current=True)

    # -- state
    @property
    def frame(self):
        return self.order[self.pos]

    def record(self, k=None):
        return self.store.get(self.label, self.frame if k is None else k)

    def is_marked(self, k=None):
        r = self.record(k)
        return r is not None and not r.get("skipped")

    def is_skipped(self, k=None):
        r = self.record(k)
        return r is not None and bool(r.get("skipped"))

    def counts(self):
        return self.store.counts(self.label, self.order)

    def ghost(self):
        """The nearest earlier marked frame's record, for the faint reference points."""
        for p in range(self.pos - 1, -1, -1):
            r = self.record(self.order[p])
            if r is not None and not r.get("skipped"):
                return self.order[p], r
        return None

    def passed_over(self):
        """Frames that were moved past (space, right arrow or n) with neither a mark nor a skip, and still have neither.
        Stepping back to look at an earlier frame does not count, and neither does the frame you are on."""
        return sorted(k for k in self.left_open if k != self.frame and self.store.get(self.label, k) is None)

    # -- camera check (see camera_check.py)
    def estimate(self, k=None):
        return self.store.get_scale(self.label, self.frame if k is None else k)

    def camera_flag(self, k=None):
        if not self.check:
            return None
        return cc.frame_flag(self.estimate(k), self.check.get("threshold", cc.DEFAULT_THRESHOLD),
                             self.check.get("min_inliers", cc.DEFAULT_MIN_INLIERS))

    def camera_reason(self, k=None):
        est = self.estimate(k)
        if est is not None and est.get("scale") is not None:
            return f"camera: scale {est['scale']:.2f} vs calibration"
        return "camera"

    def camera_text(self, k=None):
        """One line for the window: what the camera check found on this frame ('' when no check was run)."""
        if not self.check:
            return ""
        est = self.estimate(k)
        if est is None:
            return "camera check: no estimate for this frame"
        flag = self.camera_flag(k)
        if flag == "scale":
            thr = self.check.get("threshold", cc.DEFAULT_THRESHOLD)
            if est.get("inliers", 0) < self.check.get("min_inliers", cc.DEFAULT_MIN_INLIERS):
                return (f"camera check: scale {est['scale']:.2f} from only {est.get('inliers', 0)} matched features, more than "
                        f"{thr:.0%} off the calibration frame but a rough estimate: look at the frame yourself (x, Enter skips it)")
            return (f"CAMERA: scale {est['scale']:.2f} vs the calibration frame, more than {thr:.0%} off. "
                    "Suggest skipping it: press x, then Enter")
        if flag == "unreliable":
            shown = "no estimate" if est.get("scale") is None else f"scale {est['scale']:.2f}"
            return (f"camera check: unreliable ({shown}, {est.get('inliers', 0)} matched features); "
                    "look at the frame yourself")
        return f"camera check: scale {est['scale']:.2f} (consistent with the calibration frame)"

    # -- actions
    def click(self, x, y):
        k = self.frame
        if self.is_marked():
            self.message = "Frame already marked - press r to redo it"
            return False
        if self.is_skipped():
            self.store.delete(self.label, k)
            self.store.save()
        self.clicks.append((round(float(x), 1), round(float(y), 1)))
        if len(self.clicks) == 2:
            self._store_mark(k)
        return True

    def _store_mark(self, k):
        (lx, ly), (rx, ry) = self.clicks
        d_px = float(np.hypot(rx - lx, ry - ly))
        rec = {
            "pts_s": round(float(self.index.pts_s[k]), 6),
            "left_crus_px": [lx, ly], "right_crus_px": [rx, ry],
            "distance_px": round(d_px, 2), "distance_mm": round(d_px / self.px_per_mm, 4),
            "px_per_mm": self.px_per_mm, "calibration_frame": self.calibration_frame,
            "skipped": False, "source": "manual", "marked_at": fl.utc_now(),
        }
        if self.get_frame is not None:
            rec["frame_crc32"] = fl.frame_crc32(self.get_frame(k))
        flip = self._order_flipped(lx, rx)
        self.store.put(self.label, k, rec)
        self.store.save()
        self.left_open.discard(k)
        self.clicks = []
        self.message = f"saved {rec['distance_mm']:.2f} mm"
        if flip is not None:
            self.flipped.append(k)
            self.message += (f"  |  WARNING: left/right order flipped compared with frame {flip}: the left click is now on "
                             "the other side of the screen. The distance is unchanged; press r to redo if two clicks were swapped")

    def _order_flipped(self, lx, rx):
        """The previous marked frame's number when this pair's on-screen order (which click is further left) differs
        from it, else None."""
        g = self.ghost()
        now = np.sign(rx - lx)
        if g is None or now == 0:
            return None
        before = np.sign(g[1]["right_crus_px"][0] - g[1]["left_crus_px"][0])
        return None if before == 0 or before == now else g[0]

    def undo(self):
        k = self.frame
        if self.clicks:
            self.clicks.pop()
        elif self.is_marked():
            r = self.record()
            self.store.delete(self.label, k)
            self.store.save()
            self.clicks = [tuple(r["left_crus_px"])]
        elif self.is_skipped():
            self.store.delete(self.label, k)
            self.store.save()

    def redo(self):
        self.clicks = []
        if self.record() is not None:
            self.store.delete(self.label, self.frame)
            self.store.save()

    def skip(self, reason="other"):
        """Skip the frame as unusable, with a reason (camera, landmark hidden, other)."""
        k = self.frame
        if self.is_marked():
            self.message = "Frame is marked - press r (redo) to clear it before skipping"
            return
        self.clicks = []
        self.store.put(self.label, k, {"pts_s": round(float(self.index.pts_s[k]), 6), "skipped": True,
                                       "skip_reason": reason, "source": "manual", "marked_at": fl.utc_now()})
        self.store.save()
        self.left_open.discard(k)
        self.step(+1)

    def _leave(self):
        """Note that the current frame is being left; warn if it has neither a mark nor a skip."""
        if self.record() is None:
            self.left_open.add(self.frame)
            self.message = (f"frame {self.frame} left without a mark or skip (n comes back to the next open frame, "
                            "x skips)")

    def step(self, delta):
        before = self.pos
        target = int(min(max(self.pos + delta, 0), len(self.order) - 1))
        if target > before:
            self._leave()
        self.clicks = []
        self.pos = target

    def go_to_next_unmarked(self, include_current=False):
        start = self.pos if include_current else self.pos + 1
        for p in list(range(start, len(self.order))) + list(range(0, start)):
            if self.record(self.order[p]) is None:
                if p != self.pos:
                    self._leave()
                self.pos, self.clicks = p, []
                return True
        return False

    def describe(self, k):
        t = self.index.pts_s[k]
        mem = ", ".join(
            f"force s {s:.0f}{' (' + self.roles[s] + ')' if s in self.roles else ''}: {o:+d} f ({ms:+.1f} ms)"
            for s, o, ms in self.plan.membership[k])
        return f"frame {k}  video time {fl.fmt_time(t)}  |  {mem}"


# --------------------------------------------------------------- actions --------

def print_plan(params, plan, store, label, roles=None):
    roles = roles or {}
    marked, skipped, remaining = store.counts(label, plan.frames)
    print(f"Point {label}: {len(plan.samples)} force seconds, {len(plan.frames)} distinct frames to measure "
          f"(marked {marked}, skipped {skipped}, remaining {remaining})")
    print(f"  parameters: {json.dumps(params)}")
    for x, (centre, frames) in plan.samples.items():
        role = f" [{roles[x]}]" if x in roles else ""
        if centre is None:
            print(f"  force s {x:.3f}{role}: outside the video")
            continue
        offs = " ".join(f"{sf.offset_frames:+d}" for sf in frames)
        print(f"  force s {x:.3f}{role}: centre frame {centre}  offsets [{offs}]  "
              f"(first {frames[0].offset_ms:+.1f} ms, last {frames[-1].offset_ms:+.1f} ms)")


def verify_marks(store, label, plan, reader):
    bad = checked = 0
    for k in plan.frames:
        r = store.get(label, k)
        if r is None or r.get("skipped") or "frame_crc32" not in r:
            continue
        checked += 1
        if fl.frame_crc32(reader.get(k)) != r["frame_crc32"]:
            bad += 1
            print(f"  MISMATCH frame {k}")
    print(f"Verified {checked} marked frames of point {label}: {bad} mismatches")
    return bad == 0


# --------------------------------------------------------------- camera check --------

def to_gray(rgb):
    """Grey levels of an RGB frame (the same weights OpenCV uses), as uint8."""
    return np.rint(rgb[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)).astype(np.uint8)


def ensure_camera_check(reader, store, label, plan, calibration, threshold=cc.DEFAULT_THRESHOLD,
                        min_inliers=cc.DEFAULT_MIN_INLIERS, say=print):
    """Estimate each planned frame's scale relative to the point's calibration frame (see camera_check.py) and keep the
    estimates in the marks. Frames already estimated against the same calibration image are not done again. Nothing is
    skipped here: flagged frames are reported, and the marking window suggests skipping them. Returns the check settings,
    or None when no check could be made."""
    image = calibration.get("image")
    if image is None:
        say("NOTE: the camera check was not run: the calibration image was not found "
            f"({calibration.get('image_stored')}). Re-export it with export_calibration_frame.py or "
            "pick_calibration_frame.py and calibrate again.")
        return None
    meta = store.get_scale_check(label) or {}
    key = {"calibration_image": str(image), "calibration_frame": calibration.get("frame"),
           "calibration_size": Path(image).stat().st_size}
    same = all(meta.get(k) == v for k, v in key.items())
    todo = [k for k in plan.frames if not same or store.get_scale(label, k) is None]
    if todo:
        say(f"Camera check: comparing {len(todo)} frames with the calibration frame (a few seconds per point) ...")
        try:
            estimates = cc.estimate_scales(image, ((k, to_gray(reader.get(k))) for k in todo),
                                           on_progress=lambda n: say(f"  {n} of {len(todo)}") if n % 50 == 0 else None)
        except ValueError as e:
            sys.exit(f"ERROR: {e}")
        except RuntimeError as e:
            sys.exit(f"ERROR: {e}\n       The camera check could not run; to mark without it, add --no-camera-check.")
        for k, e in estimates.items():
            store.set_scale(label, k, e["scale"], e["inliers"])
    else:
        say(f"Camera check: all {len(plan.frames)} frames were already checked against this calibration frame.")
    store.set_scale_check(label, **key, threshold=threshold, min_inliers=min_inliers, frames=len(plan.frames))
    store.save()
    report_camera_check(store, label, plan, threshold, min_inliers, say=say)
    return {"threshold": threshold, "min_inliers": min_inliers}


def report_camera_check(store, label, plan, threshold, min_inliers, say=print, limit=20):
    estimates = {k: store.get_scale(label, k) for k in plan.frames}
    estimates = {k: v for k, v in estimates.items() if v is not None}
    flagged = cc.flag_frames(plan.frames, estimates, threshold, min_inliers)
    n = len(plan.frames)
    say(f"Camera check: {len(flagged)} of {n} frames flagged (scale more than {threshold:.0%} from the calibration frame's, "
        f"or an estimate from fewer than {min_inliers} matched features). Nothing was skipped: the marking window shows "
        "each flagged frame beside the calibration frame and suggests skipping it.")
    for f in flagged[:limit]:
        what = ("no scale estimate" if f["scale"] is None else f"scale {f['scale']:.2f}")
        solid = f["flag"] == "scale" and f["inliers"] >= min_inliers
        say(f"  frame {f['frame']}: {what} ({f['inliers']} matched features)"
            f"{'  -> suggest skipping' if solid else '  -> rough or unreliable estimate, check by eye'}")
    if len(flagged) > limit:
        say(f"  ... and {len(flagged) - limit} more")
    for run in cc.lasting_runs(plan.frames, estimates, threshold, min_inliers):
        say(f"  A lasting change: frames {run['first']} to {run['last']} ({run['n']} frames) are all at about scale "
            f"{run['scale']:.2f}. Skipping them one by one works, but they need their own calibration frame to be measured "
            "(this version applies one px/mm to a whole point, so for now skip them with x).")


def verify_camera(reader, store, label, plan, calibration, say=print):
    """The camera check again, on the MARKED frames only, without changing the marks. Returns False when a marked frame
    is flagged (a warning, not an error: it is the operator's call whether to keep it)."""
    image = calibration.get("image")
    marked = [k for k in plan.frames if store.get(label, k) is not None and not store.get(label, k).get("skipped")]
    if image is None:
        say(f"NOTE: the camera check was not run: the calibration image was not found ({calibration.get('image_stored')}).")
        return True
    meta = store.get_scale_check(label) or {}
    threshold = meta.get("threshold", cc.DEFAULT_THRESHOLD)
    min_inliers = meta.get("min_inliers", cc.DEFAULT_MIN_INLIERS)
    try:
        estimates = cc.estimate_scales(image, ((k, to_gray(reader.get(k))) for k in marked))
    except ValueError as e:
        sys.exit(f"ERROR: {e}")
    except RuntimeError as e:
        sys.exit(f"ERROR: {e}\n       The camera check could not run; to verify without it, add --no-camera-check.")
    flagged = cc.flag_frames(marked, estimates, threshold, min_inliers)
    say(f"Camera check on marked frames: {len(flagged)} of {len(marked)} marked frames of point {label} are flagged "
        f"(scale more than {threshold:.0%} from the calibration frame's, or an unreliable estimate).")
    for f in flagged:
        what = "no scale estimate" if f["scale"] is None else f"scale {f['scale']:.2f}"
        say(f"  frame {f['frame']}: {what} ({f['inliers']} matched features)")
    changed = [k for k in marked if store.get_scale(label, k) is not None and estimates[k]["scale"] is not None
               and store.get_scale(label, k)["scale"] is not None
               and abs(store.get_scale(label, k)["scale"] - estimates[k]["scale"]) > 0.02]
    if changed:
        say(f"  NOTE: {len(changed)} marked frames now give a different scale than the stored one (the calibration frame "
            "or the video changed?).")
    return not flagged


# ------------------------------------------------------------------- GUI --------

KEY_LINE = ("click LEFT crus, then RIGHT crus   |   x skip as unusable (asks why)   |   space or -> next, WITHOUT recording "
            "or skipping   |   <- back   |   u undo   r redo   n next open frame   g ghost   q quit")
SKIP_PROMPT = ("Skip reason:  c = camera   h = landmark hidden   o = other   Enter = {default}   Esc = cancel")


def run_gui(session, reader, label, show_ghost=True, calibration_image=None):
    """The marking window. calibration_image: path of this point's calibration frame, shown beside the frame being
    marked together with the camera check's finding for it."""
    import matplotlib.pyplot as plt

    plt.rcParams["toolbar"] = "None"
    for key in list(plt.rcParams):           # keep matplotlib's own shortcuts from stealing our keys
        if key.startswith("keymap."):
            plt.rcParams[key] = []

    fig = plt.figure(figsize=(12.5, 10))
    panel = calibration_image is not None
    ax = fig.add_axes([0, 0.04, 0.80 if panel else 1.0, 0.96])
    if panel:
        ax_cal = fig.add_axes([0.805, 0.60, 0.19, 0.32])
        ax_cal.axis("off")
        ax_cal.imshow(fl.load_rgb(calibration_image))
        cal_no = f" {session.calibration_frame}" if session.calibration_frame is not None else ""
        ax_cal.set_title(f"Calibration frame{cal_no}\nthe scale of this point", fontsize=9)
    fig.text(0.005, 0.012, KEY_LINE, fontsize=9, color="#222")
    state = {"ghost": show_ghost, "done": False, "asking": False}

    def draw():
        ax.cla()
        ax.axis("off")
        k = session.frame
        try:
            img = reader.get(k)
        except RuntimeError as e:
            ax.text(0.5, 0.5, str(e), transform=ax.transAxes, color="red", ha="center")
            fig.canvas.draw_idle()
            return
        ax.imshow(img)
        marked, skipped, remaining = session.counts()
        head = (f"Point {label}  |  frame {session.pos + 1}/{len(session.order)}  |  "
                f"marked {marked}  skipped {skipped}  left {remaining}")
        flag = session.camera_flag(k)
        camera = session.camera_text(k)
        ax.text(10, 10, head + "\n" + session.describe(k) + (("\n" + camera) if camera else ""), fontsize=11,
                color="#ff6666" if flag == "scale" else "white", va="top", bbox=dict(facecolor="black", alpha=0.75))
        r = session.record()
        if state["ghost"] and r is None:
            g = session.ghost()
            if g is not None:
                gk, gr = g
                for pt, col in ((gr["left_crus_px"], "#00FF88"), (gr["right_crus_px"], "#FF6600")):
                    ax.plot(pt[0], pt[1], "o", mfc="none", mec=col, ms=16, mew=1.5, alpha=0.55)
                ax.text(10, img.shape[0] - 40, f"ghost = marks from frame {gk}", color="#cccccc",
                        fontsize=9, va="bottom", bbox=dict(facecolor="black", alpha=0.5))
        if r is not None and not r.get("skipped"):
            pl, pr = r["left_crus_px"], r["right_crus_px"]
            ax.plot(pl[0], pl[1], "+", color="#00FF88", ms=14, mew=2)
            ax.plot(pr[0], pr[1], "+", color="#FF6600", ms=14, mew=2)
            ax.plot([pl[0], pr[0]], [pl[1], pr[1]], "--", color="white", lw=1.5, alpha=0.8)
            ax.text((pl[0] + pr[0]) / 2, (pl[1] + pr[1]) / 2 - 15, f"{r['distance_mm']:.2f} mm",
                    color="white", fontsize=10, ha="center", bbox=dict(facecolor="black", alpha=0.7))
            status = "MARKED  (r = redo, u = undo, -> = next)"
        elif r is not None:
            why = f": {r['skip_reason']}" if r.get("skip_reason") else ""
            status = f"SKIPPED as unusable{why}  (click to mark it after all)"
        else:
            for i, (x, y) in enumerate(session.clicks):
                ax.plot(x, y, "+", color="#00FF88" if i == 0 else "#FF6600", ms=14, mew=2)
            status = "Click 1/2: LEFT crus entry point" if not session.clicks else "Click 2/2: RIGHT crus entry point"
        if state["asking"]:
            default = session.camera_reason(k) if flag == "scale" else "other"
            status = SKIP_PROMPT.format(default=default.split(":")[0])
        ax.text(10, img.shape[0] - 10, f"{status}   |   {session.message}", fontsize=11, color="white",
                va="bottom", bbox=dict(facecolor="black", alpha=0.7))
        fig.canvas.draw_idle()

    def on_click(event):
        if event.inaxes is not ax or event.xdata is None:
            return
        state["asking"] = False
        session.message = ""
        session.click(event.xdata, event.ydata)
        draw()

    def on_key(event):
        session.message = ""
        key = event.key
        if state["asking"]:                  # the next key after x chooses the skip reason
            state["asking"] = False
            if key == "escape":
                session.message = "skip cancelled"
            elif key in ("c", "h", "o", "enter"):
                if key == "c":
                    reason = session.camera_reason()
                elif key == "h":
                    reason = "landmark hidden"
                elif key == "o":
                    reason = "other"
                else:
                    reason = session.camera_reason() if session.camera_flag() == "scale" else "other"
                session.skip(reason)
            else:
                state["asking"] = True
                session.message = "press c, h, o, Enter or Esc"
            draw()
            return
        if key in (" ", "right"):
            session.step(+1)
        elif key == "left":
            session.step(-1)
        elif key == "u":
            session.undo()
        elif key == "r":
            session.redo()
        elif key == "x":
            if session.is_marked():
                session.message = "Frame is marked - press r (redo) to clear it before skipping"
            else:
                state["asking"] = True
        elif key == "n":
            if not session.go_to_next_unmarked():
                session.message = "every frame is marked or skipped"
        elif key == "g":
            state["ghost"] = not state["ghost"]
        elif key == "q":
            plt.close(fig)
            return
        draw()

    fig.canvas.mpl_connect("button_press_event", on_click)
    fig.canvas.mpl_connect("key_press_event", on_key)
    try:
        plt.get_current_fig_manager().full_screen_toggle()
    except Exception:
        pass
    draw()
    plt.show()


# ------------------------------------------------------------------ main --------

def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Mark crural entry points on every frame around each force sample.")
    ap.add_argument("video")
    ap.add_argument("case_id")
    ap.add_argument("point")
    ap.add_argument("--half-window-frames", dest="half_window_frames", type=int)
    ap.add_argument("--stride", type=int)
    ap.add_argument("--time-offset-s", dest="time_offset_s", type=float)
    ap.add_argument("--window-center-shift-s", dest="window_center_shift_s", type=float)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--no-ghost", action="store_true")
    ap.add_argument("--no-camera-check", action="store_true", dest="no_camera_check",
                    help="do not run the camera check")
    ap.add_argument("--camera-threshold", type=float, default=cc.DEFAULT_THRESHOLD, dest="camera_threshold",
                    help="flag frames whose scale differs from the calibration frame's by more than this [0.05]")
    ap.add_argument("--camera-min-inliers", type=int, default=cc.DEFAULT_MIN_INLIERS, dest="camera_min_inliers",
                    help="an in-range estimate from fewer matched features is called unreliable [20]")
    ap.add_argument("--version", action="version", version=f"%(prog)s {fl.PIPELINE_VERSION}")
    return ap.parse_args(argv)


def prepare(video, case_id, label, overrides=None):
    """Everything a marking session needs for one point: the frame table, the marks store, the sampling
    parameters (command line > measurement plan > this point's previous run > defaults), the frame plan
    and the role of each force second. Stops with a clear message if an earlier stage has not been run."""
    force_dir = BASE / "Videos" / case_id / "force_data"
    index = fl.load_index(force_dir, case_id, video)
    measurement_plan = fl.load_plan(force_dir, case_id)
    if measurement_plan is None:
        sys.exit(f"ERROR: no measurement plan - run plan_measurements.py {case_id} first")
    store = fl.MarksStore(force_dir / f"{case_id}_frame_marks.json", case_id)
    prev = store.data.get("video")
    if prev and prev.get("frames") not in (None, index.n):
        sys.exit(f"ERROR: existing marks were made on a video with {prev['frames']} frames, this one has "
                 f"{index.n}. Use a different case folder or move the old marks.")
    given = {k: v for k, v in (overrides or {}).items() if v is not None}
    params = fl.resolve_params(index, **{**(store.last_params(label) or {}),
                                         **fl.plan_point_params(measurement_plan, label), **given})
    rows = force_rows(case_id, label)
    roles = {x: role for x, role in rows}
    try:
        plan = fl.plan_point(index, [x for x, _ in rows], **params)
    except ValueError as e:
        sys.exit(f"ERROR: {e}")
    if not plan.frames:
        sys.exit("ERROR: no frames fall inside the video for this point's force seconds")
    return index, store, params, plan, roles


def main(argv=None):
    args = parse_args(argv)
    label = args.point.upper()
    video = Path(args.video)
    if not video.exists():
        sys.exit(f"ERROR: video not found: {video}")

    index, store, params, plan, roles = prepare(video, args.case_id, label,
                                                {k: getattr(args, k) for k in fl.PARAM_DEFAULTS})
    if args.list:
        print_plan(params, plan, store, label, roles)
        return

    calibration = load_calibration(args.case_id, label)
    px_per_mm = calibration["px_per_mm"]
    if args.verify:
        with fl.FrameReader(video, index) as reader:
            ok = verify_marks(store, label, plan, reader)
            if not args.no_camera_check:
                verify_camera(reader, store, label, plan, calibration)
            sys.exit(0 if ok else 1)

    store.set_video(index)
    store.note_params(label, params)
    store.save()
    print_plan(params, plan, store, label, roles)
    note = f" (calibration frame {calibration['frame']})" if calibration["frame"] is not None else ""
    print(f"Calibration: {px_per_mm:.4f} px/mm{note}.  Marks are saved after every frame to {store.path.name}")

    with fl.FrameReader(video, index) as reader:
        check = None if args.no_camera_check else ensure_camera_check(
            reader, store, label, plan, calibration, args.camera_threshold, args.camera_min_inliers)
        session = MarkSession(store, label, plan, px_per_mm, index, get_frame=reader.get, roles=roles,
                              calibration_frame=calibration["frame"], check=check)
        run_gui(session, reader, label, show_ghost=not args.no_ghost,
                calibration_image=calibration["image"] if check else None)

    marked, skipped, remaining = store.counts(label, plan.frames)
    print(f"\nPoint {label}: marked {marked}, skipped {skipped}, not yet marked {remaining} of {len(plan.frames)}")
    passed = session.passed_over()
    if passed:
        print(f"WARNING: {len(passed)} frames were passed over with neither a mark nor a skip (space and the arrow keys "
              f"only move; x skips): {', '.join(str(k) for k in passed[:30])}{' ...' if len(passed) > 30 else ''}")
        print("         They stay 'not marked'. Run this command again and press n to come back to them.")
    if session.flipped:
        print(f"WARNING: the left/right click order flipped on {len(session.flipped)} frames "
              f"({', '.join(str(k) for k in session.flipped[:20])}). Distances are unaffected; the left_x/right_x columns "
              "of the per-frame table are inconsistent on those frames. Redo them (r) if two clicks were swapped.")
    print(f"Saved: {store.path}")


if __name__ == "__main__":
    main()
