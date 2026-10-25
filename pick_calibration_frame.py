"""
pick_calibration_frame.py — Scrub through a point's window and buffer and export the exact frame to calibrate on.

This is the normal step before calibrating each point. The point's px/mm is measured on ONE frame and applied to every
frame of the point, so the frame has to be a good one: the two landmark vessels visible and the same ones as on the
previous point, the camera steady and as it is for the measured frames, and the tissue not yet deformed by pulling.
The scale also changes inside a segment when the camera moves (on the test case one point gave 10.46 px/mm on the
first frame of the buffer and 13.29 on the window start, 5 s later), so look before choosing.

The window opens on the first frame of the buffer (the first frame at or after the window start minus the buffer; the
window start when there is no buffer). It shows the frame you are on, labelled with its raw frame number, its stored video
time (the same clock as time_s in the frame table) and whether it lies in the window or the buffer. Beside it are the
default frame (the start of the buffer), so camera movement is easy to see, and the previous point's calibration frame
enlarged around its two landmark clicks (point A shows the ruler frame), so you can see whether the same vessels are
visible. You can move through the window and its buffer only.

Keys
    left / right        previous / next frame
    shift+left / right  10 frames back / forward
    down / up           1 second back / forward (by the stored frame times)
    d                   back to the default frame (the start of the buffer)
    enter               export this frame and quit
    q or escape         quit without exporting (the command then exits with an error)

The export is the same as export_calibration_frame.py --frame N: a lossless PNG at the video's native resolution plus a
.json that records the frame and whether it is the default. calibrate_reference.py copies that record into the
calibration JSON.

Needs: index_video.py and extract_point_forces.py.

Usage:
    python3 pick_calibration_frame.py <video> <case_id> <point> [--frame N]
    --frame N   open on this raw frame instead of the start of the buffer
"""

import argparse
import sys
from pathlib import Path

import export_calibration_frame as ecf
import framelib as fl

BASE = Path(__file__).resolve().parent


class FramePicker:
    """Which frame is shown, within the point's window and buffer. No display needed."""

    def __init__(self, index, seg, start_frame=None):
        self.index, self.seg = index, seg
        self.lo, self.hi = fl.segment_frame_range(index, seg)      # inside the buffered window at both ends
        self.default_frame = ecf.default_frame(index, seg)
        self.window_start_frame = fl.first_frame_at_or_after(index, seg["start_s"])
        self.frame = self._clamp(self.default_frame if start_frame is None else int(start_frame))

    def _frame_at(self, t):
        k = self.index.nearest(t)
        if k is None:
            return 0 if t < self.index.pts_s[0] else self.index.n - 1
        return k

    def _clamp(self, k):
        return int(min(max(k, self.lo), self.hi))

    def step(self, frames):
        self.frame = self._clamp(self.frame + int(frames))

    def step_seconds(self, seconds):
        self.frame = self._clamp(self._frame_at(float(self.index.pts_s[self.frame]) + seconds))

    def to_default(self):
        self.frame = self.default_frame

    def on_default(self):
        return self.frame == self.default_frame

    def time_s(self, k=None):
        return float(self.index.pts_s[self.frame if k is None else k])

    def label(self):
        t = self.time_s()
        dt = t - self.seg["start_s"]
        pos = fl.segment_position(self.seg, t)
        if self.on_default():
            where = f"default: start of the buffer ({pos})"
        elif self.frame == self.window_start_frame:
            where = f"at the window start ({pos})"
        else:
            where = f"{abs(dt):.2f} s {'before' if dt < 0 else 'after'} the window start ({pos})"
        return f"frame {self.frame}   video time {fl.fmt_time(t)}   {where}"


def make_window(picker, reader, export, previous=None):
    """The figure and its key handler. export(frame) is called on Enter and returns the saved PNG path.

    previous: the previous point's calibration frame as returned by framelib.previous_reference, or None."""
    import matplotlib.pyplot as plt

    state = {"exported": None, "quit": False}
    fig = plt.figure(figsize=(14, 8))
    ax = fig.add_axes([0.01, 0.10, 0.70, 0.82])
    ax_def = fig.add_axes([0.73, 0.64, 0.26, 0.28])
    for a in (ax, ax_def):
        a.axis("off")
    ax_def.imshow(reader.get(picker.default_frame))
    ax_def.set_title(f"Default frame {picker.default_frame} (start of the buffer)\nvideo time "
                     f"{fl.fmt_time(picker.time_s(picker.default_frame))}", fontsize=9)
    if previous is not None:
        panel = (0.73, 0.10, 0.26, 0.46)
        if previous["image"] is None:
            ax_prev = fig.add_axes(panel)
            ax_prev.axis("off")
            ax_prev.set_title(f"Previous reference: {previous['name']}", fontsize=9)
            ax_prev.text(0.5, 0.5, f"image not found:\n{previous['missing']}", ha="center", va="center", fontsize=8,
                         transform=ax_prev.transAxes)
        else:
            fl.draw_landmark_crop(fig, panel, fl.load_rgb(previous["image"]), previous["p1"], previous["p2"],
                                  f"Previous reference: {previous['name']}\nsame vessels visible? (enlarged)")
    shown = ax.imshow(reader.get(picker.frame))
    title = ax.set_title("", fontsize=12)
    fig.text(0.01, 0.03, "left/right: 1 frame   shift+left/right: 10 frames   down/up: 1 s   d: default frame   "
                         "enter: export this frame   q: quit without exporting", fontsize=9, color="#444")

    def draw():
        shown.set_data(reader.get(picker.frame))
        title.set_text(picker.label())
        title.set_color("#1e8449" if picker.on_default() else "#b9770e")
        fig.canvas.draw_idle()

    def on_key(event):
        key = event.key
        if key == "right":
            picker.step(+1)
        elif key == "left":
            picker.step(-1)
        elif key == "shift+right":
            picker.step(+10)
        elif key == "shift+left":
            picker.step(-10)
        elif key == "up":
            picker.step_seconds(+1)
        elif key == "down":
            picker.step_seconds(-1)
        elif key == "d":
            picker.to_default()
        elif key == "enter":
            state["exported"] = export(picker.frame)
            plt.close(fig)
            return
        elif key in ("q", "escape"):
            state["quit"] = True
            plt.close(fig)
            return
        else:
            return
        draw()

    fig.canvas.mpl_connect("key_press_event", on_key)
    draw()
    return fig, on_key, state


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="the original video the frame table was made from")
    ap.add_argument("case_id")
    ap.add_argument("point", type=str.upper, choices=list("ABCD"))
    ap.add_argument("--frame", type=int, default=None, help="open on this raw frame instead of the start of the buffer")
    ap.add_argument("--version", action="version", version=f"%(prog)s {fl.PIPELINE_VERSION}")
    args = ap.parse_args(argv)

    video = Path(args.video)
    if not video.exists():
        sys.exit(f"ERROR: video not found: {video}")
    force_dir = ecf.BASE / "Videos" / args.case_id / "force_data"
    index = fl.load_index(force_dir, args.case_id, video)
    seg = ecf.point_segment(force_dir, args.case_id, args.point)
    picker = FramePicker(index, seg, args.frame)
    previous = fl.previous_reference(args.case_id, args.point, ecf.BASE)
    print(f"Point {args.point}: window {seg['start_text']} to {seg['end_text']}, buffer {seg['buffer_s']:g} s: frames "
          f"{picker.lo} to {picker.hi}. Default frame (start of the buffer): {picker.default_frame}.")

    import matplotlib.pyplot as plt
    with fl.FrameReader(video, index) as reader:
        def export(frame):
            png, info = ecf.export_frame(video, index, args.case_id, args.point, seg, frame)
            print(f"Exported frame {frame} ({info['video_time']}, "
                  f"{'the default frame' if info['is_default_frame'] else 'not the default'}): {png}")
            return png
        fig, on_key, state = make_window(picker, reader, export, previous)
        plt.show()
    if state["exported"] is None:
        sys.exit("No frame exported: the window was closed without pressing Enter.")
    print(f"Next: python3 calibrate_reference.py \"{state['exported']}\" {args.case_id} {args.point}")


if __name__ == "__main__":
    main()
