# Hiatal Tension Pipeline

**Version 3.0.0** (development copy, not yet released; see [CHANGELOG.md](CHANGELOG.md)).

A pipeline that **measures the crural gap on every chosen frame of a robotic hiatal hernia repair video and pairs each
measurement with the force the da Vinci 5 console recorded at that moment**, to support in vivo measurement of crural closure
tension. It needs no extra instrumentation: it uses the per-arm force the console already records and the endoscope video
already captured during the procedure.

## What goes in, and what comes out

**In:** the raw force `.json` and the raw endoscope video for a case (both downloaded from the Intuitive website), and the
operator's start and end video time for each suture point (A to D) in a tracking sheet.

**Out:** **one table with one row per measured frame**: that frame's crural distance and the force paired with it
(`<case_id>_frame_distances.csv`, and the same table as the `Frames` sheet of `<case_id>_points_ABCD_force_merged.xlsx`). Every
column is defined in [The per-frame table](#the-per-frame-table) below.

That table is where the pipeline ends. Strain, force-strain curves, constitutive-model fits and the choice of zero-strain
reference are **not** part of the pipeline: the analyst calculates them by hand from the table, as described in the methods paper
[PLACEHOLDER: citation for the associated manuscript, to be added upon publication].

## Quick start for non-programmers (Mac)

Written for an Apple-silicon MacBook Air and an Intel MacBook Pro. Everything is typed into the Terminal app.

1. **Check your macOS version** (Apple menu, About This Mac). Apple silicon (M1 and later) needs **macOS 13 Ventura or newer**.
   An Intel Mac needs **macOS 14 Sonoma or newer**. On an older Mac the install in step 5 fails with
   `No matching distribution found for av>=15` (Apple silicon) or `No matching distribution found for opencv-python>=5.0`
   (Intel). The fix is to update macOS.
2. **Install Python 3.13 from python.org** (the "universal2" installer works on both chips). Do not use the `python3` that macOS
   offers to install from Apple's developer tools. After installing, open a new Terminal window and type `python3 --version`;
   it should print `Python 3.13` something.
3. **Download the pipeline** as a ZIP from the repository page (Releases, or the green Code button, Download ZIP) and unzip it
   into your **home folder** (for example `/Users/<you>/hiatal-tension-pipeline`). Do not keep it in Desktop or Documents if iCloud
   syncs those: iCloud can move large files off the computer and the pipeline then cannot read them.
4. **Open Terminal** (Applications, Utilities). Type `cd ` (with a space after it), drag the pipeline folder from Finder into
   the Terminal window, and press Enter.
5. **Create the environment and install** (about 100 MB to download and about 0.4 GB of disk, five minutes; see Dependencies):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python3 -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
6. **Check it works:** `python3 examples/run_sample.py` should finish in under a minute with `ALL CHECKS PASSED`. It builds a
   synthetic case (no patient data) and runs every stage on it.
7. **In every new Terminal window**, do `cd ` plus the folder again and then `source .venv/bin/activate`. Without it you
   will see errors such as `No module named numpy`.
8. **Paths with spaces:** drag a file from Finder into the Terminal window instead of typing its path. Terminal types it for you.

## Pipeline stages

In run order:

| Script | Purpose |
|---|---|
| `make_tracking_sheet.py` | Creates the tracking spreadsheet with the exact column headers (one row per case ID). Never overwrites an existing file |
| `index_video.py` | Reads the stored timestamp of every frame of the raw video into a frame table (`<case_id>_frame_times.csv`: frame number, stored time) |
| `parse_force_api.py` | Parses the raw `forceTimeline` JSON from the Intuitive website into per-arm and combined force time series (Excel/CSV) |
| `extract_point_forces.py` | Selects the force samples to measure: those between each point's noted start and end, plus a buffer before and after, each labelled with its role. Records the selection |
| `plan_measurements.py` | Reports how many force values and how many frames are available, then sets the stride for each point and saves the measurement plan |
| `export_calibration_frame.py` | Exports the ruler frame, or a point's default calibration frame, exactly and losslessly at the video's native resolution, with a record of which frame it is |
| `pick_calibration_frame.py` | Scrub a point's window and buffer, compare frames, and export the frame to calibrate on |
| `calibrate_reference.py` | Interactive pixel-to-millimetre calibration: a full ruler calibration, then a landmark-only calibration per point. Shows the previous point's frame, enlarged, as a guide |
| `mark_suture_entry.py` | Interactive tool for marking the left and right crus entry points on every planned frame, converting the pixel distance to millimetres. Runs the camera check first and suggests skipping frames whose camera view has moved |
| `merge_distance_force.py` | **Writes the per-frame table**: every planned frame's distance, the force paired with it, its stored timestamp, status and camera scale |
| `camera_check.py` | The camera check (frame registration to the calibration frame). Used by `mark_suture_entry.py`; not run directly |
| `framelib.py` | Shared helpers (frame table, window selection, exact decoding, mark storage); not run directly |
| `add_timestamp.py` | Optional and not part of the workflow. Burns a time label into a re-encoded copy of the video (about 4x the source size), for anyone who wants a labelled copy for viewing |
| `measure_suture.py` | Secondary calibration utility: estimates px/mm from the known physical diameter of visible suture material |
| `verify_force.py` | Utility for spot-checking parsed force data against source values. macOS-only: uses Apple's Vision framework for OCR |

Every command-line script prints its version with `--version` and its usage with `--help`. The files made by the stages record the
version that wrote them, and files written by another **major** version are refused (see CHANGELOG.md).

## Try it first with sample data

The repository includes a synthetic sample case so you can confirm that the pipeline works on your computer before you use
real data. It contains no patient data: everything is generated, and the true answers are known.

```bash
python3 -m venv .venv
source .venv/bin/activate                  # Windows: .venv\Scripts\activate
python3 -m pip install --upgrade pip       # needed on Python 3.9, whose environment ships a pip too old for current packages
pip install -r requirements.txt
python3 -m unittest discover -s tests      # unit tests (roughly one to four minutes, depending on the computer)
python3 examples/run_sample.py             # the whole pipeline on the sample case (under a minute)
```

`examples/run_sample.py` builds a 150 s video at 29.97 fps (a static textured scene in which two bright dots stand in for the
crural entry points and close during four "suture" windows, with a different pixel scale for each, and in which the camera zooms in
by 30% for three seconds inside point B's buffer), a force log in the console's format (some seconds with one arm only), a tracking
spreadsheet and the calibration files. It then runs every stage as its own command, exactly as you would, and checks the results
against the known truth: the frame rate read from the stored timestamps, the selected force samples, each point's calibration
frame, the camera check finding the zoom (and leaving every steady frame alone), every measured distance (within 0.05 mm), the
stored timestamps behind `time_s`, and the force paired with every frame. It prints `ALL CHECKS PASSED` and exits with code 0 if
everything is right. `examples/auto_mark.py` plays the operator, because the real `mark_suture_entry.py` needs a person to click on
every frame; the sample's dots are easy for a program to find, real images are not. The sample is written to `Videos/SAMPLE001/`
(ignored by git). `--fresh` rebuilds it, and the script refuses to delete or overwrite any folder that is not a sample.

## Getting the input data

Get the raw force `.json` and the raw endoscope video for the case from the Intuitive website. How to download them is described
in a separate guide [PLACEHOLDER: link to the download guide]; this pipeline starts from the two files.

**The one manual step.** Make the case's folder inside the pipeline folder and put the force file in it under this exact name
(`<case_id>` is any code you choose, not a name or record number, and it is the same everywhere):

```
Videos/<case_id>/force_data/<case_id>_force_raw.json
```

In Finder: make a folder `Videos`, inside it a folder named `<case_id>`, inside that a folder `force_data`, and copy the JSON in with
the new name. In Terminal: `mkdir -p Videos/<case_id>/force_data`. No script creates these folders. A mistake here shows up
later as `force JSON not found`. The video can stay wherever it is: its path is given to `index_video.py`, `export_calibration_frame.py`,
`pick_calibration_frame.py` and `mark_suture_entry.py` (drag the file into Terminal to type the path).

The JSON has the following structure:

```json
{
  "USM1": [
    {"x": 433, "y": 2.1, "z": {"sensitivity": "Medium", "instrument": "..."}},
    {"x": 434, "y": 0.0, "z": null}
  ],
  "USM2": [],
  "USM3": [ ... ],
  "USM4": [ ... ]
}
```

| Field | Meaning |
|---|---|
| `x` | Seconds from case start (integer) |
| `y` | Force in Newtons (float) |
| `z` | `{"sensitivity": "Low"\|"Medium"\|"High"\|"Off", "instrument": "<name>"}`, or `null` if no instrument is docked |

### What the force log looks like

- **The log is sparse, not a continuous 1 Hz stream.** In the real test case one arm has about 500 entries over five hours,
  with gaps of more than two hours, and nonzero force occurs only while the instruments are in use. `extract_point_forces.py` keeps only
  the samples that exist.
- **An arm can be empty.** Only arms with data get a column (`USM1` to `USM4`), and the per-frame table has one force column for each.
- **Buffer seconds can have no sample.** A point can have fewer buffer rows than twice the buffer length; every window second
  that the log has is kept.
- **A blank reading counts as 0 N** in `Total Force (N)`. A blank row can therefore look like a zero-force row when an arm
  was simply not logged. The arm columns keep a blank as a blank.

## The tracking spreadsheet

`extract_point_forces.py` reads a spreadsheet named `Hiatal tension patients.xlsx` in the pipeline folder. It is intentionally **not**
included (it is per-patient tracking data). Create it with `python3 make_tracking_sheet.py <case_id> [<case_id> ...]`, which writes
the exact header row and one empty row per case and never overwrites an existing file. Open it in any spreadsheet app that saves
`.xlsx` (Excel, LibreOffice; Apple Numbers only through File, Export To, Excel). Or make your own with a header row containing at least:

| Column | Meaning |
|---|---|
| `Study ID` | Case identifier, must match `<case_id>` used elsewhere (e.g. `CASE001`). Any text works; use a code, not a name or record number |
| `Point A start`, `Point A end` | `HH:MM:SS` start and end of the period during which point A's suture is tied (see below) |
| `Point B start`, `Point B end` | Same, for point B |
| `Point C start`, `Point C end` | Same, for point C |
| `Point D start`, `Point D end` | Same, for point D |

Type the times as text (`2:21:07` and `02:21:07` both work) or as Excel time cells: both are read correctly. One row per case. Points with
no start and end filled in are skipped. `extract_point_forces.py` names any required column that is missing and stops with an error
(exit status 1) when a named case produces no output (the case is not in the sheet, has no force JSON, or has no points defined).
Use `--tracking-sheet FILE` to read a differently named or located sheet. Nothing in the pipeline writes to this sheet.

**Where the start and end times come from.** The operator scrubs through the video in any media player
(for example QuickTime) and writes down when each point's suture is being tied. Whole seconds (`HH:MM:SS`)
are enough; fractions (`HH:MM:SS.mmm`) are accepted. These are **video times**, the time the player shows from the start of
the video, which is the same clock as `time_s` in the frame table. Frame-exact times are not needed: the window only selects
which whole-second force samples are measured, and the exact frames around each are found from the frame table.

## Usage

Each script is run independently and takes a case identifier and/or file paths as arguments; run any of them with `--help` for its
usage. All scripts resolve paths relative to their own location and expect a `Videos/<case_id>/` folder for per-case inputs and
outputs.

**Every new terminal:** activate the virtual environment (`source .venv/bin/activate`, Windows `.venv\Scripts\activate`) and
work from the pipeline folder. The paths in the commands below are relative to it.

A typical end-to-end run for a new case:

```bash
python3 make_tracking_sheet.py <case_id>                  # once, if you have no tracking sheet yet
mkdir -p "Videos/<case_id>/force_data"
# copy the force JSON to Videos/<case_id>/force_data/<case_id>_force_raw.json (see Getting the input data)

python3 index_video.py "<video file>.mp4" <case_id>
python3 parse_force_api.py "Videos/<case_id>/force_data/<case_id>_force_raw.json" <case_id>

# scrub the video in your own player, note each point's start and end (HH:MM:SS), and enter
# them in Hiatal tension patients.xlsx

python3 extract_point_forces.py <case_id>
python3 plan_measurements.py <case_id>

# the full calibration needs a frame with a ruler in the field (see Calibration)
python3 export_calibration_frame.py "<video file>.mp4" <case_id> ruler --time <HH:MM:SS of a frame that shows the ruler>
python3 calibrate_reference.py "Videos/<case_id>/calibration_frames/<case_id>_ruler_frame<N>.png" <case_id>

# per point (A-D): choose the calibration frame by scrubbing, then calibrate on it
python3 pick_calibration_frame.py "<video file>.mp4" <case_id> A
python3 calibrate_reference.py "Videos/<case_id>/calibration_frames/<case_id>_A_frame<N>.png" <case_id> A
# repeat for B, C, D

# mark every planned frame of a point (camera check first; autosaves; run again to resume)
python3 mark_suture_entry.py "<video file>.mp4" <case_id> A
# repeat for B, C, D

python3 merge_distance_force.py <case_id>       # the per-frame table
```

## Calibration

The pixel-to-millimetre scale is measured on one frame per point and applied to every frame of that point, so which frame it is
measured on matters.

**Full calibration (once per case).** It needs one frame in which a ruler of known length lies in the field (for example a
centimetre ruler across the hiatus), and the two blood-vessel landmarks. **Place a ruler in the field during the case and note that
it was used.** Without a frame that shows a ruler there is no ruler calibration, and the per-point calibrations cannot be done because
they take the landmark distance from it. Export that frame exactly, at the video's native resolution (never a scaled screenshot):
`python3 export_calibration_frame.py "<video>" <case_id> ruler --time HH:MM:SS` (the first frame at or after that video time) or
`--frame N`. It saves `Videos/<case_id>/calibration_frames/<case_id>_ruler_frame<N>.png`, and `calibrate_reference.py` runs on it.
The full calibration writes `<case_id>_calibration.json` only.

**Each point's calibration frame is chosen by scrubbing**, not fixed to a rule:

```bash
python3 pick_calibration_frame.py "<video file>.mp4" <case_id> A
```

opens the point's window and buffer on the **first frame of the buffer** (the first frame at or after the window start minus
the buffer). You move through the window and its buffer and press Enter on the frame to calibrate on. A good frame has the two
landmark vessels visible and the same ones as on the previous point, a steady camera that is as it is for the measured frames,
and tissue that is not yet deformed by pulling. The scale also changes inside a segment whenever the camera moves: on the real
test case the same operator, landmarks and point gave 10.46 px/mm on the first frame of the buffer and 13.29 on the window start,
5 s later, and operator-chosen frames gave a consistent 12.5 to 13.0 px/mm across four points (landmarks 127 to 132 px apart)
where fixed buffer-start frames gave 10.46 to 16.53. Look before you choose.

The window shows the frame you are on (its raw frame number, stored video time, and whether it is in the window or the buffer),
the default frame (the start of the buffer) beside it so camera movement is visible, and **the previous point's calibration frame
enlarged around its two landmark clicks** (point A shows the ruler frame), so you can see whether the same vessels are visible.
Keys: left/right one frame, shift+left/right ten frames, down/up one second, `d` back to the default frame, Enter exports the frame,
`q` quits without exporting. The export is a lossless PNG at the video's native resolution decoded from the original video by its
number, with a `.json` next to it that records the frame and whether it is the default.
(`export_calibration_frame.py <video> <case_id> <point>` exports the default frame without scrubbing;
`--frame N` exports any frame.) Then:

```bash
python3 calibrate_reference.py "Videos/<case_id>/calibration_frames/<case_id>_A_frame<N>.png" <case_id> A
```

The calibration JSON copies the export's record as `frame_info`, so the frame each point was calibrated on is always known (a still
made by hand has `frame_info: null`), and every mark stores the calibration frame its px/mm came from.

**Landmark clicks, point by point.** In the per-point calibration window a panel on the right shows the previous reference frame,
enlarged to a square around its two landmark marks (with a small thumbnail of the whole frame and the square outlined), the marks
numbered in the order they were clicked: point A shows the ruler frame, B shows A's, C shows B's and D shows C's; when the previous
point has not been calibrated yet, the ruler frame is shown. Click the same two vessels in the same order. The panel sits beside
the frame, so it never covers the area being clicked. The command exits with an error and writes nothing unless both landmarks were
clicked ("No calibration saved").

## The camera check

The scale of a point is measured on one frame, so a frame on which the endoscope has zoomed or moved is converted with the wrong
scale. On the real test case the camera zoomed about 30% in 0.4 s inside one point's buffer and nothing noticed it. `mark_suture_entry.py`
therefore checks every planned frame before marking:

- For each frame it estimates the **scale of the scene relative to the point's calibration frame** by direct registration (ORB features
  matched between the two frames, with the console's top and bottom bars masked, then a RANSAC similarity transform). It is never
  chained from frame to frame, because a chain drifts (on the test case to 0.74 to 0.79 with no camera activity). A scale of 1.00 is the
  same zoom as the calibration frame. The estimate is stored in the marks and written to the per-frame table as `scale_vs_calibration`.
- It **flags but never acts alone.** A frame is flagged when its scale differs from 1 by more than 5% (`--camera-threshold`), even from a
  rough estimate, and as *unreliable* when no estimate could be made or fewer than 20 matched features (`--camera-min-inliers`) support an
  in-range scale (for example when instruments fill the view): look at those yourself. The flagged frames are listed before marking, and
  in the marking window each is shown with the calibration frame beside it and its scale, with a suggestion to skip it.
- To accept a suggestion press `x`, then Enter: the frame is recorded as skipped with the reason `camera: scale 0.76 vs calibration`.
  To keep it, mark it as usual. Nothing is skipped without a key press.
- **A lasting change** (six or more consecutive planned frames flagged at about the same scale) is reported as such, because skipping
  it frame by frame is the only option this version has: it applies one px/mm to a whole point, so a stretch at another zoom cannot be
  measured without its own calibration frame.
- `mark_suture_entry.py --verify` re-decodes the marked frames, checks they are the frames that were shown, and runs the camera check
  again on them, listing any marked frame that is flagged (a warning, not an error). `--no-camera-check` skips the check.
- Optional hint, da Vinci only: the console overlay highlights the arm-2 (endoscope) panel at the bottom of the frame while the camera is
  being moved. The check does not use it, because the registration is the test.

The check runs in a **child process**: PyAV (which decodes the frames) and OpenCV (which registers them) each bundle their own FFmpeg
libraries, and importing both in one process prints a macOS "implemented in both" warning and can be unstable, so no script of this
pipeline imports both.

## Frame table

`index_video.py` reads the timestamp stored for every frame of the video (it does not decode pictures, so it takes
seconds) and writes `Videos/<case_id>/force_data/<case_id>_frame_times.csv`:

| Column | Meaning |
|---|---|
| `frame` | frame number, starting at 0, in presentation order |
| `pts` | the stored timestamp, in time-base ticks (an integer) |
| `time_s` | video time in seconds; the first frame is time 0 |
| `time_hms` | the same as `HH:MM:SS.mmm` |
| `keyframe` | 1 for keyframes |

A small `.json` next to it records the video's name and size, its time base and a summary (frame count, mean frame rate, gaps).
Real frame timestamps are not on an exact nominal-fps grid: the average rate of a file can differ slightly from its nominal rate, and
individual gaps wobble. Every later stage uses these stored times, never `frame number / fps`. The tool warns if the video has dropped
frames or a variable frame rate.

## Windows, buffer and roles

`extract_point_forces.py <case_id> [--buffer-s 5] [--time-offset-s 0]` keeps every force sample from the point's start minus
the buffer to its end plus the buffer. Each kept row is labelled in a `Role` column:

| Role | Meaning |
|---|---|
| `window` | between the noted start and end (these rows also have `In Window = YES`) |
| `buffer-before` | in the buffer before the start |
| `buffer-after` | in the buffer after the end |

All kept rows are measured. Window rows are coloured gold and buffer rows light blue in the workbook, so the two are easy to tell
apart, and the role is carried through to the per-frame table. A `Selection` sheet in the workbook records what was selected: each
point's start and end as entered, the buffer, the time offset and the row counts. Buffer rows exist only where the force log has a sample.

`--time-offset-s` is the video time minus the force time. The noted windows are video times, and a force sample `x` is at video
time `x + offset`. It is 0 unless the two clocks are known to differ; it is recorded in the `Selection` sheet and used by every later stage.
To work it out, find one event that is visible in both (for example an instrument docking, or a sharp rise in force when a
grasper closes) and subtract: the offset is the time the player shows for the event minus the force log's `x` for it. Force samples
are a second apart, so this is good to about a second at best; it is not verified automatically, and 0 is the default.

If a point's first selected row already has force on it (leftover force from earlier activity at the start of the buffer),
`extract_point_forces.py` prints a warning naming the arms. It changes nothing; check that row if your analysis looks for a zero-force
row before the rise.

### Timing convention (an assumption that has not been verified)

The pipeline treats a force sample at integer second `x` as the **centre** of that second: it describes the video from `x - 0.5 s`
to `x + 0.5 s` (after the offset), and the frames around `x` are measured. If the console instead means the second that starts at
`x` (10.000 to 10.999), every measured frame sits half a second early, and `--window-center-shift-s 0.5` (accepted by
`plan_measurements.py`, `mark_suture_entry.py` and `merge_distance_force.py`) corrects it. The force JSON gives integer seconds
only, so the data cannot say which is meant, and a half-second error cannot be told apart from a clock offset. The default is 0.
To settle it, use the console's documentation or ask the vendor; a video check of a sharp force step can only narrow it down.

## Measurement plan and stride

`plan_measurements.py <case_id>` reads the frame table and the selected force rows. It prints, per point and in total, the number
of force values (window and buffer), the maximum number of frames available (stride 1), and the frames and clicks other strides
would need. It then asks for the stride of each point. Strides can also be given as `--stride 10` (all points) or
`--stride A=10 B=1`, and `--yes` accepts the default (10). The choice is saved in `<case_id>_measurement_plan.json`.

**Frames per force second.** Force samples are one second apart, which is 30 frames at 30 fps. Each sample is measured on the
frames around its centre frame, the frame whose stored time is nearest the sample's time. A frame 15 frames from the centre is
exactly half a second away, which is exactly halfway to the neighbouring sample. It would belong to both samples, and the same
distance measurement would feed two points of a force-strain curve, so neighbouring points would depend on each other. The
pipeline therefore keeps **strictly fewer than 15 frames on either side of the centre frame** (at most 14, about 0.47 s), so every
frame belongs to one force second. The offsets are 0, +/-stride, +/-2 stride, ... within that limit: stride 10 measures offsets
-10, 0 and +10 (about 0.33 s either side), stride 5 measures -10 to +10 by 5, and stride 1 measures -14 to +14 (29 frames). The
limit follows the video's frame rate (14 at 30 and 29.97 fps, 29 at 60 fps) and is always strictly less than half the spacing of
the force samples. All of this assumes that a force sample's time is the centre of its second and not its start (see Timing convention).

**Stride is adjustable.** The stride is the number of frames between measured frames. A stride of 1 measures every frame inside the
limit, and larger values measure fewer: stride 10 gives 3 frames per force second, stride 5 gives 5, stride 1 gives 29. Set it for
all points with `--stride 10`, or per point with `--stride A=10 B=5`. `plan_measurements.py` first prints the frames and clicks each
stride would need. Marks are stored by frame number, so you can start sparse and re-run with a smaller stride later; only frames not
yet marked are added.

| Option | Meaning | Default |
|---|---|---|
| `--half-window-s S` | half-window around each force second, in seconds (converted to frames with the video's frame rate). A value that would allow 15 frames (0.5 s at 30 fps) or more is **refused**, because a frame would serve two force seconds | the largest allowed (14 frames at 30 fps) |
| `--window-center-shift-s S` | shift the window centre, for example +0.5 if the console's `x` means the second that starts at `x` (see Timing convention) | 0 |

`mark_suture_entry.py` and `merge_distance_force.py` apply the same limit to `--half-window-frames`. A plan with a half-window of 15
frames (made by version 2.0.0) is refused with a message to run `plan_measurements.py` again, and so is a plan or marks file
written by another major version.

**How frames are chosen.** For a force second `x`, the centre frame is the frame whose stored timestamp is nearest
`x + time_offset_s + window_center_shift_s`, and the measured frames are the centre frame plus the offsets above. The window is built
in frames, not as a hard time cut, so the same number of frames is chosen wherever the centre frame falls within its frame slot.
The true millisecond offset of every frame is recorded. A sensible check is a sparse pass on every point plus a full pass
(`--stride 1`) on one point, to confirm that the sparse mean and SD match the dense ones.

## Marking

`mark_suture_entry.py <video> <case_id> <point>` takes its parameters from the measurement plan (options given on its command
line override the plan and are recorded). The video is decoded exactly from the original file and the time on screen is each
frame's stored timestamp. The window shows the frame number, its video time, and for each force second that uses the frame its
role (window or buffer) and offset, the camera check's finding for the frame, and the point's calibration frame. `--list` prints the
frame plan and progress without opening a window.

**The keys are always on screen.** Click the left crus entry point, then the right; `x` skips the frame as unusable and asks for
a reason (`c` camera, `h` landmark hidden, `o` other, Enter the default, Esc cancels); **`space` or the right arrow only moves to the
next frame, WITHOUT marking or skipping it** (the frame stays "not marked"); the left arrow goes back; `u` undoes a click (or the
last mark); `r` redoes (clears this frame so it can be marked again); `n` jumps to the next frame that is neither marked nor skipped;
`g` shows or hides faint "ghost" marks from the previous marked frame; `q` quits. Every action is saved at once, and relaunching the
tool resumes at the first open frame. Leaving a frame without a mark or skip prints a note, and on quitting the tool lists the frames
that were passed over that way.

**Skip reasons** are stored with the skip and written to the `skip_reason` column of the per-frame table.

**What to click: the crus entry point.** The crus entry point is where the suture needle enters the edge of a crus: the stitch
entry on the left crus and on the right crus (the "left crus suture entry point" and "right crus suture entry point" of the
Methods). On a frame where the needle is mid-pass, mark the point where it entered that crus. If the entry point cannot be seen
(covered by an instrument, the needle or thread, or smoke), skip the frame with the reason `h` (landmark hidden) rather than guess. If
the clicks move toward the middle of the hiatus because the needle is mid-pass and the instrument grips the thread, the gap you
measure is the suture, not the crura: decide for the whole case what you mark and keep to it.

**Left and right.** The distance is the straight-line distance between the two clicks, so a flipped pair changes no distance. But
the table's `left_x`, `left_y`, `right_x`, `right_y` and the ghost marks assume the left crus is always clicked first. The tool warns
when the on-screen order of the pair flips between consecutive marked frames (which click is further left), and lists the frames at
the end. (In the real test case the left crus appeared on the right side of the screen. Which side it is does not matter; consistency
does.)

## The per-frame table

`merge_distance_force.py <case_id>` writes the product of the pipeline into `Videos/<case_id>/force_data/`:

- `<case_id>_frame_distances.csv`: **one row per planned frame** of every selected force second (window and buffer), in the order point,
  force second, frame;
- `<case_id>_points_ABCD_force_merged.xlsx`: the same table as the **`Frames`** sheet, plus the `Summary <point> (from Frames)` sheets
  (one row per force second: mean, SD, N, min, max, median of its marked frames' distances and a straight-line fit; derived from the
  Frames sheet and secondary), the `Selection` sheet and a `Merge info` sheet (version, time base, counts, how to read the columns).

| Column | Meaning |
|---|---|
| `case_id`, `point` | case ID and suture point (A to D) |
| `role` | `window`, `buffer-before` or `buffer-after`: where the force second lies relative to the noted window |
| `force_second`, `force_time_hms` | the force sample's time in the force log (seconds, and `HH:MM:SS`) |
| `frame` | raw frame number in the video (0 = first frame, in presentation order) |
| `pts` | the frame's **stored presentation timestamp**, an integer in time-base ticks, exactly as read from the file |
| `time_s` | (`pts` minus the first frame's `pts`) x time base: the video time a player shows, in seconds. The time base and the first `pts` are on the `Merge info` sheet, so `time_s` can be recomputed from `pts` |
| `time_hms` | the same as `HH:MM:SS.mmm` |
| `offset_frames`, `offset_ms` | the frame's distance from the force second's centre frame, in frames and in ms (frame time minus the force sample's target time) |
| `status` | `marked`, `skipped` or `not marked` |
| `skip_reason` | why a skipped frame was skipped (`camera: scale 0.76 vs calibration`, `landmark hidden`, `other`); empty otherwise |
| `distance_mm`, `distance_px` | the crural distance in millimetres and in pixels (empty unless marked) |
| `left_x`, `left_y`, `right_x`, `right_y` | the two clicks in pixels, left crus first |
| `px_per_mm` | the scale the distance was converted with (empty unless marked) |
| `calibration_frame` | the raw frame number of the calibration frame that scale came from (empty if it was a hand-made still) |
| `scale_vs_calibration` | the camera check: the scene's scale on this frame relative to the calibration frame (1.00 = same zoom; empty if no check was made or no estimate was possible) |
| `USM1` to `USM4` | the force of each logged arm in N, as in the force log; **blank where the log has no sample** |
| `Total Force (N)` | the sum of the arms, **where a blank arm counts as 0 N** |

**How to read the spread.** The frames of one force second are up to about 0.47 s apart (14 frames at 30 fps either side), and the
gap can change by several millimetres per second, so the spread of distance across a force second's frames mixes real tissue motion,
click noise and timing ambiguity. It is a conservative uncertainty of the distance at the nominal sample time, not pure measurement
error. With only three or four frames per force second any SD is a rough estimate, and more frames per force second give an
uncertainty on each force second but do not add force values: there is still one force sample per second (buffer rows add some). To
estimate click noise alone, re-mark a subset of frames on another occasion and compare.

## Other outputs

All under `Videos/<case_id>/` (nothing is overwritten except by re-running the stage that makes it):

| File | Made by | Contents |
|---|---|---|
| `force_data/<case_id>_frame_times.csv`, `.json` | `index_video.py` | the frame table and its summary |
| `force_data/<case_id>_points_ABCD_force.xlsx` | `extract_point_forces.py` | the selected force rows per point with their roles, and the `Selection` record |
| `calibration_frames/<case_id>_<point>_frame<N>.png`, `.json` | `export_calibration_frame.py`, `pick_calibration_frame.py` | a calibration frame and the record of which frame it is |
| `force_data/<case_id>_calibration.json`, `<case_id>_<point>_calibration.json` | `calibrate_reference.py` | px/mm, the landmark clicks, the frame used (`frame_info`) and the version |
| `force_data/<case_id>_measurement_plan.json` | `plan_measurements.py` | the parameters and the stride per point, with force and frame counts |
| `force_data/<case_id>_frame_marks.json` | `mark_suture_entry.py` | every marked or skipped frame, keyed by frame number, with its timestamp, clicks, distance, calibration frame, skip reason and a checksum of the frame shown; the camera-check scale of every planned frame; the parameters used |
| `force_data/<case_id>_frame_distances.csv`, `<case_id>_points_ABCD_force_merged.xlsx` | `merge_distance_force.py` | **the per-frame table** (see above) |

## Dependencies

**Python 3.9 or newer.** For version 3.0.0 the full test suite, including the sample-data run, passed in fresh virtual
environments (nothing inherited) installed from `requirements.txt` alone, on Python 3.9, 3.10, 3.12 and 3.14 (macOS, Apple
silicon). The Python 3.9 environment resolves to exactly the minimum versions in the table below (numpy 2.0.2, matplotlib 3.9.4,
pandas 2.3.3, av 15.1.0, pillow 11.3.0, opencv-python 5.0.0.93), so the minimums are tested; one test is skipped there because the
OpenCV build for that Python has no mp4 writer (see below). Other platforms have not been tested, and the clicking windows have been
driven headlessly only.

**Minimum macOS** (checked with `pip download --only-binary=:all:` for each chip and macOS version; nothing was installed):

| Mac | Minimum macOS | What an older Mac shows |
|---|---|---|
| Apple silicon (M1 and later) | **13 Ventura** | below 13: `No matching distribution found for av>=15` |
| Intel | **14 Sonoma** | on 13 or older: `No matching distribution found for opencv-python>=5.0` |

The fix is to update macOS. (`requirements-tested.txt` pins `av==19.0.2`, whose Apple-silicon wheel needs macOS 14; on macOS 13 install
from `requirements.txt`, which resolves to av 15.1.) **Size:** about 95 to 112 MB to download (depending on the chip) and about 370 MB (0.4 GB) of disk once installed.

```bash
python3 -m pip install --upgrade pip               # first: on Python 3.9 the environment's own pip (20.2) cannot read current
                                                   # wheel names, tries to build from source and fails
pip install -r requirements.txt                    # everything the pipeline needs
pip install -r requirements-optional-macos.txt     # only for verify_force.py, on macOS
```

| Package | Minimum tested | Needed by | What for |
|---|---|---|---|
| `numpy` | 2.0 | every stage | arrays and statistics |
| `openpyxl` | 3.1 | `extract_point_forces`, `plan_measurements`, `merge_distance_force`, `make_tracking_sheet` | reading and writing the Excel workbooks |
| `matplotlib` | 3.9 | `mark_suture_entry`, `calibrate_reference`, `pick_calibration_frame`, `measure_suture` | the interactive windows |
| `av` (PyAV) | 15 | `index_video`, `mark_suture_entry`, `export_calibration_frame`, `pick_calibration_frame`, the sample case | reading each frame's stored timestamp and decoding frames exactly. Bundles FFmpeg's libraries, so no separate FFmpeg install is needed |
| `pillow` | 11.3 | `export_calibration_frame`, `pick_calibration_frame`, `framelib` | the lossless PNG of an exact frame, and reading reference images (matplotlib already needs it) |
| `opencv-python` | 5.0 | `calibrate_reference`, `camera_check`, `measure_suture`, `add_timestamp`, `verify_force` | reading images, and the feature matching of the camera check |
| `pandas` | 2.3 | `parse_force_api`, `verify_force` | tables |
| `pyobjc-framework-Cocoa`, `pyobjc-framework-Vision` | latest | `verify_force` only (macOS only, optional) | Apple's Vision framework for OCR |

Three files list them: `requirements.txt` (the minimum versions above, with the scripts that need each package),
`requirements-tested.txt` (the exact versions of a passing environment: `pip install -r requirements-tested.txt` reproduces it)
and `requirements-optional-macos.txt`. Older versions than the minimums may work but have not been tested.

- The sample case and the unit tests need nothing beyond these packages: no real video, no internet, no GPU, no FFmpeg install.
- The interactive tools open a window using matplotlib's default backend for your platform. macOS and Windows normally need nothing
  more. On Linux install Tk (for example `sudo apt install python3-tk`) or Qt (`pip install PyQt6`), and set `MPLBACKEND`
  (for example `MPLBACKEND=TkAgg`) if matplotlib does not find one. Headless use (no display) is possible with `MPLBACKEND=Agg` for
  everything except the clicking tools.
- On macOS, `opencv-python` and PyAV each bundle their own FFmpeg. Importing both in one Python process prints an Objective-C
  "implemented in both" warning and can be unstable. No script in this pipeline imports both (the camera check runs OpenCV in a
  child process); keep it that way in your own scripts.
- `opencv-python` on Python 3.9 (macOS) is built without FFmpeg: it reads images and videos but cannot write an mp4. Only the
  optional `add_timestamp.py` writes a video, and it stops with an error there instead of reporting success. Nothing else is affected.
- Copy the whole pipeline folder, not just the `.py` files: every output records the version from the `VERSION` file, and the
  scripts stop with a message if it is missing.
- `verify_force.py` is an optional, macOS-only diagnostic. It stops with a clear message on other systems.

## Data availability

This repository contains analysis code only. No patient data, video, or
identifiable information is included. See the associated manuscript for the
data availability statement covering de-identified derived measurements.

## Citation

[PLACEHOLDER: citation for the associated manuscript, to be added upon
publication]
