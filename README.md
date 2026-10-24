# Hiatal Tension Pipeline

**Version 2.1.0, per-frame workflow** (development copy, not yet released; see [CHANGELOG.md](CHANGELOG.md)).
Version 1.0.0 (one frame per force second) is a separate release and its results are not read by this version.
Version 2.0.0 was tested on a real case but never released; 2.1.0 is the first release of the per-frame workflow.
Its files are still read, but the default frames per force second changed, so a plan made by 2.0.0 must be made again
(the marks already made are kept; see the CHANGELOG).

Computational pipeline for extracting synchronized force and crural gap
deformation data from da Vinci 5 surgical platform recordings, developed to
support in vivo measurement of crural closure tension during robotic hiatal
hernia repair.

The pipeline requires no additional instrumentation: it uses per-arm force
data already recorded by the da Vinci 5 console and endoscope video already
captured during the procedure.

## What changed from version 1.0.0

- Only the original video is used. No timestamped re-encode and no video clips are needed.
- `index_video.py` reads the stored timestamp of every frame of the video into a frame table, and every later stage identifies
  frames by that true timestamp instead of assuming frame number / fps.
- Each force second is measured on several frames around it, not one, so the distance comes with a spread. No frame serves two
  force seconds: every frame is strictly less than half a second from its force second's centre frame (at most 14 frames at 30 fps).
- The buffer around each window is now measured as well, and window and buffer rows are labelled so buffer rows can be left
  out of an analysis (`fit_moduli.py --rows window`).
- `plan_measurements.py` reports how many force values and frames are available and sets the stride (how many frames to skip) per point.
- Marking autosaves, resumes, and has undo, redo and skip. Marks are stored per frame so a denser pass only adds frames.
- Each point's calibration frame is the first frame of its segment, exported exactly from the video (see Calibration frames).
- Convention B takes its zero-strain reference at the rise at the noted window start (see Fits and row sets).

## Try it first with sample data

The repository includes a synthetic sample case so you can confirm that the pipeline works on your computer before you use
real data. It contains no patient data: everything is generated, and the true answers are known.

```bash
python3 -m venv .venv
source .venv/bin/activate                  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python3 -m unittest discover -s tests      # unit tests (one to two minutes)
python3 examples/run_sample.py             # the whole pipeline on the sample case (under a minute)
```

`examples/run_sample.py` builds a 150 s video at 29.97 fps (two bright dots stand in for the crural entry points and close
during four "suture" windows, with a different pixel scale for each), a force log in the console's format, a tracking
spreadsheet and the calibration files. It then runs every stage as its own command, exactly as you would, and checks the results
against the known truth: the frame rate read from the stored timestamps, the selected force samples, every measured distance
(within 0.05 mm), the pairing of force and distance, and the fitted modulus (the sample is built to give 6 N). It prints
`ALL CHECKS PASSED` and exits with code 0 if everything is right. `examples/auto_mark.py` plays the operator, because the real
`mark_suture_entry.py` needs a person to click on every frame; the sample's dots are easy for a program to find, real images
are not. The sample is written to `Videos/SAMPLE001/` (ignored by git). `--fresh` rebuilds it, and the script refuses to delete or
overwrite any folder that is not a sample.

## Pipeline stages

In run order:

| Script | Purpose |
|---|---|
| `index_video.py` | Reads the stored timestamp of every frame of the raw video into a frame table (`<case_id>_frame_times.csv`: frame number, stored time) |
| `parse_force_api.py` | Parses the raw `forceTimeline` JSON exported from the da Vinci console's web interface into per-arm and combined force time series (Excel/CSV) |
| `make_tracking_sheet.py` | Creates the tracking spreadsheet with the exact column headers (one row per case ID). Never overwrites an existing file |
| `export_calibration_frame.py` | Exports a point's calibration frame, the first frame of its segment, exactly and losslessly at the video's native resolution, with a record of which frame it is |
| `pick_calibration_frame.py` | Only when the first frame cannot be used: scrub the segment, see the default frame beside the current one, and export the chosen frame |
| `calibrate_reference.py` | Interactive tool for pixel-to-millimeter spatial calibration; supports both a full ruler-based calibration and a landmark-only calibration per point (that point's calibration frame) to correct for depth-dependent scale variation. Shows the previous point's frame with its landmark marks as a guide |
| `extract_point_forces.py` | Selects the force samples to measure: those between each point's noted start and end, plus a buffer before and after, each labelled with its role. Records the selection |
| `plan_measurements.py` | Reports how many force values and how many frames are available, then sets the stride for each point and saves the measurement plan |
| `mark_suture_entry.py` | Interactive tool for manually marking the left/right crus entry points on every planned frame, converting pixel distance to millimeters |
| `merge_distance_force.py` | Summarises the per-frame distances for each force second (mean, SD, N, min, max, median, straight-line fit), computes a combined Total Force column, and writes a new merged workbook plus a per-frame table |
| `measure_hiatal_position.py` | Interactive tool for measuring the position of each annotated point along a defined anatomical long axis, using a single reference frame |
| `fit_moduli.py` | Converts the per-force-second mean distances to strain and fits one-parameter constitutive models (linear, Neo-Hookean) to force-strain data. Plots show the spread of each force second and the individual frames |
| `framelib.py` | Shared helpers (frame table, window selection, exact decoding, mark storage); not run directly |
| `add_timestamp.py` | Optional and not part of the workflow. Burns a time label into a re-encoded copy of the video (about 4x the source size), for anyone who wants a labelled copy for viewing |
| `measure_suture.py` | Secondary calibration utility: estimates px/mm from the known physical diameter of visible suture material |
| `verify_force.py` | Utility for spot-checking parsed force data against source values. macOS-only — uses Apple's Vision framework for OCR |

Every command-line script prints its version with `--version` and its usage with `--help`, and the files made by the stages
that are new or changed since 1.0.0 (frame table, extraction workbook, measurement plan, marks, calibration records, merged
workbook, fit tables and plots) record the version that wrote them.

## Getting the input data

Force data is obtained from the da Vinci console's companion web interface,
which serves a per-case JSON blob containing per-second (~1 Hz) force
readings for each instrument arm. To obtain this file for a given case:

1. Create the case's working directory: `mkdir -p Videos/<case_id>/force_data`
2. Log in to the console's web interface and open the case of interest.
3. Open your browser's developer tools, Network tab, and filter for
   `forceTimeline`.
4. Reload the page so the request fires.
5. Save the response body as `Videos/<case_id>/force_data/<case_id>_force_raw.json`.

No script in this pipeline creates the `Videos/<case_id>/` directory tree —
step 1 must be done by hand before running anything else.

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

The corresponding endoscope video for the same case is required for the video-based stages. Use the original
video file; it can sit anywhere, and its path is given to `index_video.py` and `mark_suture_entry.py`.

### What the force log looks like

- **The log is sparse, not a continuous 1 Hz stream.** In the real test case one arm has about 500 entries over five hours,
  with gaps of more than two hours, and nonzero force occurs only while the instruments are in use. `extract_point_forces.py` keeps only
  the samples that exist.
- **An arm can be empty.** Only arms with data get a column (`USM1` to `USM4`); `merge_distance_force.py` adds the arms present
  to give the total and `fit_moduli.py` fits each arm present and the total.
- **Buffer seconds can have no sample.** A point can have fewer buffer rows than twice the buffer length; every window second
  that the log has is kept.
- **A blank reading counts as 0 N** in the totals and the fits. A blank row can therefore look like a zero-force row when an arm
  was simply not logged.

## Required per-case tracking spreadsheet

`extract_point_forces.py` reads, and `calibrate_reference.py` writes to, a spreadsheet named `Hiatal tension patients.xlsx` in the
repository root. This file is intentionally **not** included (it is per-patient tracking data). Create it with
`python3 make_tracking_sheet.py <case_id> [<case_id> ...]`, which writes the exact header row and one empty row per case and never
overwrites an existing file, or make your own with a header row containing at least:

| Column | Meaning |
|---|---|
| `Study ID` | Case identifier, must match `<case_id>` used elsewhere (e.g. `CASE001`). Any text works; use a code, not a name or record number |
| `Point A start`, `Point A end` | `HH:MM:SS` start and end of the period during which point A's suture is tied (see below) |
| `Point B start`, `Point B end` | Same, for point B |
| `Point C start`, `Point C end` | Same, for point C |
| `Point D start`, `Point D end` | Same, for point D |

One row per case. Points with no start/end filled in are skipped by
`extract_point_forces.py`, which also names any required column that is missing and stops with an error (exit status 1) when a
named case produces no output (the case is not in the sheet, has no force JSON, or has no points defined). Use `--tracking-sheet FILE`
to read a differently named or located sheet. **The full calibration (`calibrate_reference.py <image> <case_id>`, with a ruler)
appends calibration columns (`px_per_mm_ruler`, `landmark_mm`, ...) to the case's row of this sheet in place, with no backup.**
The calibration JSON holds the same results and nothing later reads those columns, so copy the sheet first if it matters to you.

**Where the start and end times come from.** The operator scrubs through the video in any media player
(for example QuickTime) and writes down when each point's suture is being tied. Whole seconds (`HH:MM:SS`)
are enough; fractions (`HH:MM:SS.mmm`) are accepted. These are **video times**, the time the player shows from the start of
the video, which is the same clock as `time_s` in the frame table. Frame-exact times are not needed: the window only selects
which whole-second force samples are measured, and the exact frames around each are found from the frame table.

## Usage

Each script is run independently and takes a case identifier and/or file
paths as arguments; run any of them with `--help` for its usage, or see its module docstring. All scripts resolve paths relative to their
own location by default and expect a `Videos/<case_id>/` subdirectory
structure for per-case inputs and outputs.

**Every new terminal:** activate the virtual environment (`source .venv/bin/activate`, Windows `.venv\Scripts\activate`) and
work from the repository root. The paths in the commands below are relative to the repository root.

A typical end-to-end run for a new case:

```bash
python3 make_tracking_sheet.py <case_id>                  # once, if you have no tracking sheet yet
mkdir -p "Videos/<case_id>/force_data"
# place <case_id>_force_raw.json in Videos/<case_id>/force_data/ (see above)

python3 index_video.py "<video file>.mp4" <case_id>
python3 parse_force_api.py "Videos/<case_id>/force_data/<case_id>_force_raw.json" <case_id>

# scrub the video in your own player, note each point's start and end (HH:MM:SS), and enter
# them in Hiatal tension patients.xlsx

python3 extract_point_forces.py <case_id>
python3 plan_measurements.py <case_id>

# the full calibration needs a frame with a ruler in the field (see Calibration frames)
python3 export_calibration_frame.py "<video file>.mp4" <case_id> ruler --time <HH:MM:SS of a frame that shows the ruler>
python3 calibrate_reference.py "Videos/<case_id>/calibration_frames/<case_id>_ruler_frame<N>.png" <case_id>

# per point (A-D): export the calibration frame (the first frame of the point's segment) and calibrate on it.
# mark_suture_entry.py will not start without the calibration file.
python3 export_calibration_frame.py "<video file>.mp4" <case_id> A
python3 calibrate_reference.py "Videos/<case_id>/calibration_frames/<case_id>_A_frame<N>.png" <case_id> A
# repeat for B, C, D

# mark every planned frame of a point (autosaves; run again to resume)
python3 mark_suture_entry.py "<video file>.mp4" <case_id> A
# repeat for B, C, D

python3 merge_distance_force.py <case_id>
python3 measure_hiatal_position.py "Videos/<case_id>/calibration_frames/<case_id>_ruler_frame<N>.png" <case_id>
python3 fit_moduli.py <case_id>            # add --rows window to leave the buffer rows out
```

Calibration frames must be at the video's native resolution; a scaled screenshot gives the wrong px/mm.
`export_calibration_frame.py` makes them exactly (next section).

## Calibration frames

**Full calibration (once per case).** It needs one frame in which a ruler of known length lies in the field (for example a
centimetre ruler across the hiatus), and the two blood-vessel landmarks. Place a ruler in the field during the case and note that
it was used. Without a frame that shows a ruler there is no ruler calibration, and the per-point calibrations cannot be done because
they take the landmark distance from it. Export that frame exactly, at the video's native resolution (never a scaled screenshot):
`python3 export_calibration_frame.py "<video>" <case_id> ruler --time HH:MM:SS` (the first frame at or after that video time) or
`--frame N`. It saves `Videos/<case_id>/calibration_frames/<case_id>_ruler_frame<N>.png`, and `calibrate_reference.py` runs on it.

**Per-point calibration frame: the first frame of the point's segment.** Each point's px/mm is found from the same two landmarks
on that point's own frame, because the scale changes with the camera's depth. The frame is the first frame of the point's segment,
the first frame whose stored time is at or after the window start in the tracking sheet. The reason is that later frames may
already show the tissue deformed by pulling, which changes the landmark distance and so the scale: on the real test case, calibrating on
the middle of the window instead of its first frame moved the scale by 4.5% for one point and 7.0% for another (one operator, one
pass, so that includes click variation).

```bash
python3 export_calibration_frame.py "<video file>.mp4" <case_id> A
```

decodes that frame from the original video by its number (exactly, not a screenshot), saves it as a lossless PNG at the video's native
resolution in `Videos/<case_id>/calibration_frames/<case_id>_A_frame<N>.png`, and writes a `.json` next to it recording the frame
number, its video time, its position (window or buffer), its checksum and whether it is the default. Then run
`calibrate_reference.py` on that PNG. The calibration JSON copies the record as `frame_info`, so a point that was calibrated on another
frame can be found afterwards (a still made by hand has `frame_info: null`).

**Leaving the first frame is for two cases only:** (a) the landmark is not visible on the first frame (for example an instrument
covers it), or (b) the camera has moved between the first frame and the time the forces are collected.
`pick_calibration_frame.py <video> <case_id> <point>` is the tool for that: it shows the frame you are on, labelled with its
frame number, its stored video time and whether it is in the window or the buffer, and beside it the default first frame so
camera movement is easy to see. Keys: left/right one frame, shift+left/right ten frames, down/up one second, `d` back to the
default, Enter exports the frame, `q` quits without exporting. You can move through the window and its buffer. The exported file
is marked as not the default. (`export_calibration_frame.py --frame N` does the same non-interactively.)

**Landmark clicks, point by point.** In the per-point calibration window a panel on the right shows the previous reference frame
with its two landmark marks numbered in the order they were clicked: point A shows the ruler frame, B shows A's, C shows B's and D
shows C's; when the previous point has not been calibrated yet, the ruler frame is shown. Click the same two vessels in the same order.
The panel sits beside the frame, so it never covers the area being clicked. The command exits with an error and writes nothing
unless both landmarks were clicked ("No calibration saved").

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
apart, and the role is carried through the merged workbook, the per-frame table and the fits. A `Selection` sheet in the workbook
records what was selected: each point's start and end as entered, the buffer, the time offset and the row counts.
Buffer rows exist only where the force log has a sample.

`--time-offset-s` is the video time minus the force time. The noted windows are video times, and a force sample `x` is at video
time `x + offset`. It is 0 unless the two clocks are known to differ; it is recorded in the `Selection` sheet and used by every later stage.
To work it out, find one event that is visible in both (for example an instrument docking, or a sharp rise in force when a
grasper closes) and subtract: the offset is the time the player shows for the event minus the force log's `x` for it. Force samples
are a second apart, so this is good to about a second at best; it is not verified automatically, and 0 is the default.

If a point's first selected row already has force on it (leftover force from earlier activity at the start of the buffer),
`extract_point_forces.py` prints a warning naming the arms. It does not change anything: the default Convention B reference does
not depend on those rows (see Fits and row sets).

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
distance measurement would feed two points on the force-strain curve, so neighbouring points would depend on each other. The
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

`mark_suture_entry.py` and `merge_distance_force.py` apply the same limit to `--half-window-frames`. A plan or marks file made by
2.0.0 (half-window 15, offsets -15 and +15 shared between neighbouring seconds, `edge` layout) is refused with a message to run
`plan_measurements.py` again. Marks already made stay in the marks file, keyed by frame number, and a frame that is still planned keeps its mark;
frames that are no longer planned (for example the +/-15 frames) are not used.
`plan_measurements.py` also reports the number of frames used for two force seconds, which is 0, and stops if it is not.

**How frames are chosen.** For a force second `x`, the centre frame is the frame whose stored timestamp is nearest
`x + time_offset_s + window_center_shift_s`, and the measured frames are the centre frame plus the offsets above. The window is built
in frames, not as a hard time cut, so the same number of frames is chosen wherever the centre frame falls within its frame slot.
The true millisecond offset of every frame is recorded. A sensible check is a sparse pass on every point plus a full pass
(`--stride 1`) on one point, to confirm that the sparse mean and SD match the dense ones.

## Marking

`mark_suture_entry.py <video> <case_id> <point>` takes its parameters from the measurement plan (options given on its command
line override the plan and are recorded). The video is decoded exactly from the original file and the time on screen is each
frame's stored timestamp. The title shows the frame number, its video time, and for each force second that uses the frame its
role (window or buffer) and offset. `--list` prints the frame plan and progress without opening a window, and `--verify`
re-decodes marked frames and checks they are the frames that were shown.

**Keys:** click the left crus entry point, then the right; `u` undo a click (or the last mark); `r` redo (clear this frame and
mark it again); `x` skip an unusable frame (it is excluded from the statistics); arrow keys or space move between frames without
changing anything; `n` jumps to the next frame that is neither marked nor skipped; `g` shows or hides faint "ghost" marks from
the previous marked frame, to speed up consistent clicking; `q` quits. Every action is saved at once, and relaunching the tool
resumes at the first open frame.

## Outputs

New files per case, all under `Videos/<case_id>/force_data/` (nothing is overwritten except by re-running the stage that makes it):

| File | Made by | Contents |
|---|---|---|
| `<case_id>_frame_times.csv`, `.json` | `index_video.py` | the frame table and its summary |
| `../calibration_frames/<case_id>_<point>_frame<N>.png`, `.json` | `export_calibration_frame.py`, `pick_calibration_frame.py` | a calibration frame and the record of which frame it is |
| `<case_id>_calibration.json`, `<case_id>_<point>_calibration.json` | `calibrate_reference.py` | px/mm, the landmark clicks, the frame used (`frame_info`) and the version |
| `<case_id>_points_ABCD_force.xlsx` | `extract_point_forces.py` | the selected force rows per point with their roles, and the `Selection` record |
| `<case_id>_measurement_plan.json` | `plan_measurements.py` | the parameters and the stride per point, with force and frame counts |
| `<case_id>_frame_marks.json` | `mark_suture_entry.py` | every marked or skipped frame, keyed by frame number, with its timestamp, click positions, distances and a checksum of the frame shown; the parameters used |
| `<case_id>_points_ABCD_force_merged.xlsx` | `merge_distance_force.py` | the force workbook plus, per force second: mean distance (the column the fits use), SD, number of frames, min, max, median, and a straight-line fit |
| `<case_id>_frame_distances.csv` | `merge_distance_force.py` | one row per (point, force second, frame): role, frame number, time, offset, distance, click positions, status |
| `<case_id>_moduli_table_<rows>.xlsx`, `plots/..._model_fits_<rows>.png` | `fit_moduli.py` | fits and plots for `all` rows or `window` rows only |

## How to read the spread

The frames of one force second are up to about 0.47 s apart (14 frames at 30 fps either side), and the gap can change by several millimetres per second,
so the SD across frames mixes real tissue motion, click noise and timing ambiguity. It is a conservative uncertainty of the
distance at the nominal sample time, not pure measurement error. The residual SD about the straight-line fit (`Fit resid SD`) is
closer to click noise. With only three or four frames per force second any SD is a rough estimate, and more frames per force
second give an uncertainty on each point but do not add points to a force-strain curve: there is still one point per force
second (buffer rows add points). To estimate click noise alone, re-mark a subset of frames on another occasion and compare.

## Fits and row sets

`fit_moduli.py <case_id> [--rows all|window] [--onset window-rise|first-rise|smallest-gap]` fits the per-force-second mean distance
against force. It fits every arm that has a column in the merged workbook (`USM1` to `USM4`) and the total. `--rows all` (default)
uses every measured row; `--rows window` leaves the buffer rows out, so the strain reference (widest gap, force onset) comes from the
noted window only. Outputs carry the row set in their name so both can coexist, the table lists `n window` and `n buffer` for each
curve, and the plots draw window points filled and buffer points hollow. The two row sets can give different moduli: buffer rows
bring in pre- and post-placement positions and can supply the zero-force points Convention B looks for. Buffer rows after the
window also include whatever happens once the suture is tied and released, so check them before relying on `--rows all`.

**Convention B reference (`--onset`).** Convention B takes the gap at the zero-force row just before the force rises at the noted
window start as its zero-strain reference. Rule `window-rise` (the default since 2.1.0), found for each channel on its own: the
**last zero-force row before the first nonzero row at or after the noted window start** (the first row with role `window`). Rows
before it may be buffer rows, so force left over from earlier activity in the buffer does not invalidate the reference. It is
undefined only when no row is nonzero from the window start on, or when no zero row comes before that first nonzero row. A Convention
B fit needs at least 3 points. The other rules stay selectable for comparison:

| `--onset` | Reference row | Notes |
|---|---|---|
| `window-rise` | last zero-force row before the first nonzero row at or after the window start | default |
| `first-rise` | last zero-force row before the force first becomes nonzero anywhere in the rows used | 2.0.0 rule. Undefined if the first row is already nonzero. Equals `window-rise` with `--rows window` |
| `smallest-gap` | the zero-force row with the smallest gap | 1.0.0 rule. Differs whenever the force returns to zero after loading (for example when an instrument is released): the reference moves to the end of the window and few points are kept |

The rule used is written in the moduli table and on the plots.

**Convention B and the buffer.** In the real test case the force flickers between exactly 0 and 1 to 2 N while the instruments hold,
and the first buffer row of one point still had 1.7 N from earlier activity, followed by zeros and then the rise. Under `first-rise`
that point's Convention B was undefined; under `window-rise` its reference is the last zero before the rise. The result still depends on
what the force log holds around the window: a blank arm reading counts as 0 N, so a blank row can look like a zero-force row, and the
buffer length decides which zeros are available. Check each point's reference row.

**Total force.** `merge_distance_force.py` adds the arms' readings to give the total, and a missing reading for an arm counts as 0 N.
If one arm is logged and the other is not for the same second, that second's total is lower by the missing arm's force.

## Dependencies

**Python 3.9 or newer.** The full test suite, including the sample-data run, passed in fresh virtual environments (nothing
inherited) installed from `requirements.txt` alone, on Python 3.9, 3.10, 3.12 and 3.14 (macOS, Apple silicon). Other
platforms have not been tested.

```bash
pip install -r requirements.txt                    # everything the pipeline needs
pip install -r requirements-optional-macos.txt     # only for verify_force.py, on macOS
```

| Package | Minimum tested | Needed by | What for |
|---|---|---|---|
| `numpy` | 2.0 | every stage | arrays and statistics |
| `openpyxl` | 3.1 | `extract_point_forces`, `plan_measurements`, `merge_distance_force`, `fit_moduli`, `calibrate_reference`, `measure_hiatal_position` | reading and writing the Excel workbooks |
| `scipy` | 1.13 | `fit_moduli` | curve fitting |
| `matplotlib` | 3.9 | `mark_suture_entry`, `calibrate_reference`, `measure_hiatal_position`, `measure_suture`, `fit_moduli` | the interactive windows and the plots |
| `av` (PyAV) | 15 | `index_video`, `mark_suture_entry`, `export_calibration_frame`, `pick_calibration_frame`, the sample case | reading each frame's stored timestamp and decoding frames exactly. Bundles FFmpeg's libraries, so no separate FFmpeg install is needed |
| `pillow` | 8.0 | `export_calibration_frame`, `pick_calibration_frame` | the lossless PNG of an exact frame (matplotlib already needs it) |
| `opencv-python` | 5.0 | `calibrate_reference`, `measure_hiatal_position`, `measure_suture`, `add_timestamp`, `verify_force` | reading images |
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
  "implemented in both" warning and can be unstable. No script in this pipeline imports both; keep it that way in your own scripts.
- `verify_force.py` is an optional, macOS-only diagnostic. It stops with a clear message on other systems.

## Data availability

This repository contains analysis code only. No patient data, video, or
identifiable information is included. See the associated manuscript for the
data availability statement covering de-identified derived measurements.

## Citation

[PLACEHOLDER: citation for the associated manuscript, to be added upon
publication]
