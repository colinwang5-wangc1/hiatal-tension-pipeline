"""
mark_suture_entry.py — Manually mark the crural entry points on every video frame
that could correspond to each force sample, so the distance at each force second
comes with an uncertainty instead of resting on one frame.

For every selected force second (window and buffer rows from extract_point_forces.py), frames
are chosen around it by their true timestamps (see framelib.py): the centre frame is the one whose
stored timestamp is nearest the force second (+ time offsets), and the sampled frames are that frame
plus a set of frame offsets (the layout and stride set by plan_measurements.py). Each distinct
raw frame is marked once, even when neighbouring force seconds share it. Frames are decoded exactly
from the RAW video; the time shown on screen is the frame's stored timestamp. The title also says
whether each force second is a window row or a buffer row.

On each frame: click the LEFT crus entry point, then the RIGHT crus entry point.
The mark is saved at once. Marks are keyed by raw frame number, so a later run with a
denser stride only adds the frames not yet marked.

Keys
    click      left crus, then right crus   (a third click on a marked frame is ignored)
    u          undo the last click (or the last mark)
    r          redo: clear this frame and mark it again
    x          skip: frame unusable (occluded); excluded from the statistics
    ->  / space / <-   next / previous frame (nothing is recorded or lost)
    n          jump to the next frame that is not marked or skipped
    g          show / hide the previous marked frame's points as faint "ghosts"
    q          quit (everything is already saved)

Needs, in this order:
    index_video.py             the frame table of the video
    extract_point_forces.py    the force samples to measure
    plan_measurements.py       the stride for each point (the measurement plan)
    calibrate_reference.py <still.png> <case_id> <point>    px/mm for the point

Results (new files; nothing existing is overwritten):
    Videos/<case_id>/force_data/<case_id>_frame_marks.json   per-frame marks + parameters

Usage:
    python3 mark_suture_entry.py <video.mp4> <case_id> <point> [options]

Options (the measurement plan supplies the defaults; options given here override it and are recorded):
    --half-window-frames N   frames on each side of the centre frame
    --stride N               spacing of sampled frames, in frames
    --layout edge|centred    edge: -H,-H+s,..  centred: 0,+/-s,..
    --time-offset-s S        video time minus force time (clock offset)
    --window-center-shift-s S  shift the window centre (sample = bin start?)
    --list                   print the frame plan and progress, then exit
    --verify                 re-decode this point's marked frames and check their CRCs
    --no-ghost               start with ghost marks hidden

Example:
    python3 mark_suture_entry.py Videos/<case_id>/<video file>.mp4 <case_id> A
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

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


def load_px_per_mm(case_id, label):
    path = BASE / "Videos" / case_id / "force_data" / f"{case_id}_{label}_calibration.json"
    if not path.exists():
        sys.exit(f"ERROR: calibration file not found: {path}\n"
                 f"       make it with: python3 calibrate_reference.py <still.png> {case_id} {label}")
    with open(path) as f:
        return float(json.load(f)["px_per_mm"])


# --------------------------------------------------------------- session --------

class MarkSession:
    """Marking state for one point. No display code: every action autosaves."""

    def __init__(self, store, label, plan, px_per_mm, index, get_frame=None, roles=None):
        self.store, self.label, self.plan, self.px_per_mm = store, label, plan, px_per_mm
        self.index = index
        self.get_frame = get_frame            # k -> RGB array (only needed to store a CRC)
        self.roles = roles or {}              # force second -> window | buffer-before | buffer-after
        self.order = plan.frames
        self.clicks = []
        self.pos = 0
        self.message = ""
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
            "px_per_mm": self.px_per_mm, "skipped": False, "source": "manual",
            "marked_at": fl.utc_now(),
        }
        if self.get_frame is not None:
            rec["frame_crc32"] = fl.frame_crc32(self.get_frame(k))
        self.store.put(self.label, k, rec)
        self.store.save()
        self.clicks = []
        self.message = f"saved {rec['distance_mm']:.2f} mm"

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

    def skip(self):
        k = self.frame
        if self.is_marked():
            self.message = "Frame is marked - press r (redo) to clear it before skipping"
            return
        self.clicks = []
        self.store.put(self.label, k, {"pts_s": round(float(self.index.pts_s[k]), 6), "skipped": True,
                                       "source": "manual", "marked_at": fl.utc_now()})
        self.store.save()
        self.step(+1)

    def step(self, delta):
        self.clicks = []
        self.pos = int(min(max(self.pos + delta, 0), len(self.order) - 1))

    def go_to_next_unmarked(self, include_current=False):
        start = self.pos if include_current else self.pos + 1
        for p in list(range(start, len(self.order))) + list(range(0, start)):
            if self.record(self.order[p]) is None:
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


# ------------------------------------------------------------------- GUI --------

def run_gui(session, reader, label, show_ghost=True):
    import matplotlib.pyplot as plt

    plt.rcParams["toolbar"] = "None"
    for key in list(plt.rcParams):           # keep matplotlib's own shortcuts from stealing our keys
        if key.startswith("keymap."):
            plt.rcParams[key] = []

    fig = plt.figure(figsize=(12.5, 10))
    ax = fig.add_axes([0, 0, 1, 1])
    state = {"ghost": show_ghost, "done": False}

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
        ax.text(10, 10, head + "\n" + session.describe(k), fontsize=11, color="white", va="top",
                bbox=dict(facecolor="black", alpha=0.75))
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
            status = "SKIPPED as unusable  (click to mark it after all)"
        else:
            for i, (x, y) in enumerate(session.clicks):
                ax.plot(x, y, "+", color="#00FF88" if i == 0 else "#FF6600", ms=14, mew=2)
            status = "Click 1/2: LEFT crus entry point" if not session.clicks else "Click 2/2: RIGHT crus entry point"
        ax.text(10, img.shape[0] - 10, f"{status}   |   {session.message}", fontsize=11, color="white",
                va="bottom", bbox=dict(facecolor="black", alpha=0.7))
        fig.canvas.draw_idle()

    def on_click(event):
        if event.inaxes is not ax or event.xdata is None:
            return
        session.message = ""
        session.click(event.xdata, event.ydata)
        draw()

    def on_key(event):
        session.message = ""
        key = event.key
        if key in (" ", "right"):
            session.step(+1)
        elif key == "left":
            session.step(-1)
        elif key == "u":
            session.undo()
        elif key == "r":
            session.redo()
        elif key == "x":
            session.skip()
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
    ap.add_argument("--layout", choices=["edge", "centred"])
    ap.add_argument("--time-offset-s", dest="time_offset_s", type=float)
    ap.add_argument("--window-center-shift-s", dest="window_center_shift_s", type=float)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--no-ghost", action="store_true")
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
    params = fl.resolve_params(**{**(store.last_params(label) or {}), **fl.plan_point_params(measurement_plan, label),
                                  **given})
    rows = force_rows(case_id, label)
    roles = {x: role for x, role in rows}
    plan = fl.plan_point(index, [x for x, _ in rows], **params)
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

    px_per_mm = load_px_per_mm(args.case_id, label)
    if args.verify:
        with fl.FrameReader(video, index) as reader:
            sys.exit(0 if verify_marks(store, label, plan, reader) else 1)

    store.set_video(index)
    store.note_params(label, params)
    store.save()
    print_plan(params, plan, store, label, roles)
    print(f"Calibration: {px_per_mm:.4f} px/mm.  Marks are saved after every frame to {store.path.name}")

    with fl.FrameReader(video, index) as reader:
        session = MarkSession(store, label, plan, px_per_mm, index, get_frame=reader.get, roles=roles)
        run_gui(session, reader, label, show_ghost=not args.no_ghost)

    marked, skipped, remaining = store.counts(label, plan.frames)
    print(f"\nPoint {label}: marked {marked}, skipped {skipped}, not yet marked {remaining} of {len(plan.frames)}")
    print(f"Saved: {store.path}")


if __name__ == "__main__":
    main()
