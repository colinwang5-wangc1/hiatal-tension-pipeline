# Changelog

Versions follow `MAJOR.MINOR.PATCH`. A change of MAJOR version means file formats or the run order changed and
files written by another major version are not read. The current version is in `VERSION`; every output file records
the version that wrote it.

## 2.1.0 - changes from the real-case test of 2.0.0 (development copy, not yet released)

Version 2.0.0 was tested on one real case (macOS, Python 3.14) and never released. Version 2.1.0 implements the operator's
decisions from that test and fixes the bugs it found. It is the first release of the per-frame workflow; 1.0.0 stays the
citable baseline. Files written by 2.0.0 are still read (same major version), but **the default plan is different**, see below.

### Changed: the default frames per force second (read this if you used 2.0.0)
- **No frame may serve two force seconds.** Force samples are one second apart (30 frames at 30 fps), and in 2.0.0 the default
  (`edge` layout, half-window 15 frames, stride 10: offsets -15, -5, +5, +15) gave the +15 frame of one force second to the next as
  its -15 frame. On the test case that was 300 frame slots but only 232 distinct frames, with 68 frames each used for two force
  seconds, so neighbouring points of a force-strain curve were not independent although the fits treat them as independent.
  Every offset is now strictly less than half the spacing of the force samples: at most 14 frames either side at 30 and 29.97 fps (29 at
  60 fps), the limit being derived from the video's frame rate. Stride 10 measures -10, 0, +10; stride 5 measures -10 to +10 by 5; stride 1
  measures -14 to +14 (29 frames). On the test case: 225 frame slots, 225 distinct frames, 0 used twice.
- The `edge` layout is removed (under the limit its offsets are lopsided, for example -14, -4, +6 at stride 10) and with it
  `--layout` in `plan_measurements.py`, `mark_suture_entry.py` and `merge_distance_force.py`. The default half-window is the largest allowed for
  the video. `--half-window-s` / `--half-window-frames` that would allow 15 frames (0.5 s at 30 fps) or more are refused. `plan_measurements.py`
  reports the number of frames used for two force seconds and stops if it is not 0.
- A plan or marks file written by 2.0.0 (half-window 15) is refused by `mark_suture_entry.py` and `merge_distance_force.py` with
  a message to run `plan_measurements.py` again. Marks already made are kept in the marks file (they are keyed by frame number);
  a frame that is still planned keeps its mark and frames that are no longer planned are not used.
- **Convention B reference rule (`--onset`, new default `window-rise`).** The reference is the last zero-force row before the first
  nonzero row at or after the noted window start (the first row with role `window`), per channel. Rows before it may be buffer rows, so
  force left over in the buffer no longer makes Convention B undefined. 2.0.0's rule (`first-rise`) stopped at the first nonzero row of
  all the rows and returned undefined when the first buffer row already had force; on the test case it also took one point's reference from a
  0.8 N blip in the buffer four seconds before the noted start. Both earlier rules stay selectable (`--onset first-rise`, `--onset smallest-gap`
  for the 1.0.0 rule); with `--rows window` the new rule and `first-rise` agree. On the test case: the reference rows of points B and C move later on most channels and
  point D's USM3 and Total curves are defined. Results should be compared under the rules before they are reported. The manuscript's Methods must
  describe this rule.
- **Calibration frame of each point: the first frame of the point's segment** (the first frame at or after the noted window start). Later
  frames may show tissue already deformed by pulling (on the test case the scale moved by 4.5% and 7.0% for two points between a mid-window frame
  and the first frame). `calibrate_reference.py` now records the frame used (`frame_info`) in the calibration JSON.
- `calibrate_reference.py` is restructured into a click state machine and a thin window. It stops with "No calibration saved" and exit status
  1 when the window is closed before the calibration is complete (see B3), shows the previous reference frame with its two landmark marks beside
  the frame being calibrated (point A shows the ruler frame, B shows A's, C shows B's, D shows C's; the ruler frame when the previous point has
  no calibration yet), and takes `--tracking-sheet`. It refuses two clicks on the same pixel.
- `fit_moduli.py` fits the arms present in the merged workbook (`USM1` to `USM4`) and the total, no longer only `USM1`, `USM3` and the total.
- `extract_point_forces.py` stops with an error and exit status 1 when a named case is not in the tracking sheet, has no force JSON or has no
  points defined (an unnamed run skips such cases and fails only if nothing is written), and prints a warning when a point's first row already
  has force.
- `--help` prints usage for every script that did not handle it (see B5). `--window-center-shift-s` help states the timing assumption.

### Added
- `export_calibration_frame.py`: exports a point's calibration frame, or the ruler frame of the full calibration, from the original video by
  frame number (exactly, at the video's native resolution, as a lossless PNG) with a `.json` recording the frame and whether it is the default.
- `pick_calibration_frame.py`: scrubs a point's window and buffer, shows the default first frame beside the frame being viewed, and exports the chosen
  frame. For the two cases where the first frame cannot be used (the landmark is hidden, or the camera has moved).
- `make_tracking_sheet.py`: creates the tracking spreadsheet with the exact headers; never overwrites an existing file.
- Tests for each change (`tests/test_calibration.py`, `test_calibration_frames.py`, `test_cli_scripts.py`, `test_tracking_sheet.py` and additions to
  the existing files). `pillow` is listed in `requirements.txt`.

### Fixed
- B1 `extract_point_forces.py` printed nothing and exited 0 for a named case that is not in the sheet, and exited 0 for a case without a force
  JSON. Both are now errors with exit status 1.
- B2 `fit_moduli.py` was hard-wired to `USM1`, `USM3` and the total, so a case on other arms stopped with a `KeyError` and arms 2 and 4 were never fitted.
- B3 `calibrate_reference.py` printed only "Loaded reference ..." and exited 0 when its window was closed without the needed clicks.
- B4 `add_timestamp.py` printed "Done. 0 frames written" and exited 0 for a video it could not read (including `--help`, which it read as a file name).
- B5 `parse_force_api.py`, `calibrate_reference.py`, `measure_hiatal_position.py`, `measure_suture.py` and `verify_force.py` did not handle
  `--help` (an error, or a traceback for `measure_suture.py`); an unreadable image is now an error instead of a traceback in the image tools.
  `verify_force.py` answers `--help` and `--version` on any system.

### Not decided (documented, defaults unchanged)
- Timing convention of a force sample: the pipeline treats a sample at second `x` as the centre of that second. If the console means the second
  that starts at `x`, every frame sits half a second early. The data cannot say which; see the README ("Timing convention").
- The 5 s buffer is kept. Convention B still depends on the force log around the window (a blank arm reading counts as 0 N).

### Migration from 2.0.0
Run `plan_measurements.py` again for each case (marks already made are kept), re-calibrate points on their first frames if they were calibrated on another frame,
and re-run `merge_distance_force.py` and `fit_moduli.py`. Compare Convention B under `--onset window-rise` and `--onset first-rise` before reporting.

## 2.0.0 - per-frame workflow (tested on one case; never released, superseded by 2.1.0)

Version 1.0.0 (GitHub tag `v1.0.0`, Zenodo 10.5281/zenodo.23288184) is unchanged and remains the citable baseline.
Results made with 1.0.0 must be regenerated with 2.0.0; they are not read by it.

### Why
A force sample stamped `x` is not tied to one video frame: frame timestamps are not on an exact nominal-fps grid, and the
instant within the second that a sample represents is not known. Version 1.0.0 measured one frame per force second, found by
`int(x * fps)` on a re-encoded copy of the video. Version 2.0.0 measures several frames around each force second, identified by
the video's own stored timestamps, and reports their spread.

### Added
- `index_video.py`: reads the stored presentation timestamp (PTS) of every frame of the raw video into a frame table
  (`<case_id>_frame_times.csv`: frame number, PTS, time, keyframe flag) with a sidecar `.json`.
- `plan_measurements.py`: after the force samples are selected, reports how many force values and how many frames are
  available, then sets the stride for each point and writes `<case_id>_measurement_plan.json`.
- `framelib.py`: shared helpers (frame table, window selection by true timestamps, exact decoding, mark storage).
- `extract_point_forces.py`: `--buffer-s`, `--time-offset-s`, a `Role` column (window, buffer-before, buffer-after) and a
  `Selection` sheet recording what was selected.
- `examples/`: a synthetic sample case (`make_sample_case.py`), a stand-in operator (`auto_mark.py`) and an end-to-end run that
  checks the results against known truth (`run_sample.py`), so the pipeline can be tried in a new environment without patient data.
- `--tracking-sheet` for `extract_point_forces.py` (read a differently named or located spreadsheet) and `--onset` for
  `fit_moduli.py` (the Convention B reference rule).
- Unit tests (`tests/`), `VERSION`, this file, and `--version` on every command-line script. Files made by the new and changed
  stages record the version that wrote them.
- Labelled dependency files: `requirements.txt` (minimum versions, with the scripts that need each package),
  `requirements-tested.txt` (exact versions of a passing environment) and `requirements-optional-macos.txt`.

### Changed
- `mark_suture_entry.py`: takes the original video (not a clip); marks every frame in a window of +/-0.5 s around each force
  second (configurable stride); decodes frames exactly from the raw video (needs PyAV); autosaves after every action,
  resumes, and has undo, redo, skip and ghost marks; marks are keyed by raw frame index so a denser pass only adds frames;
  the matplotlib backend is no longer hard-coded to macOS.
- Buffer rows are now measured. In 1.0.0 the 5 s buffer only added force rows for context and only start-to-end rows were
  measured. In 2.0.0 window and buffer rows are all measured and labelled so buffer rows can be excluded from analysis.
- Window times are read as video time and a force second `x` is compared as `x + time_offset_s`.
- `merge_distance_force.py`: summarises the frames of each force second (mean, SD, N, min, max, median, straight-line fit),
  writes a new merged workbook and a per-frame table, and no longer modifies the extraction workbook.
- `fit_moduli.py`: reads the merged workbook; fits use the per-force-second means; `--rows all|window` selects the rows used
  (default all measured rows); plots show spread, individual frames, and window versus buffer points.
- `fit_moduli.py`, Convention B: the zero-strain reference is now the gap at the last zero-force row before the force first
  becomes nonzero, which is the definition in the Methods. Version 1.0.0 took the zero-force row with the smallest gap, which
  gives the same result only when the force is zero before loading and nowhere after. On a force trace that returns to zero
  later (for example when an instrument is released) it moved the reference to the end of the window and kept only one to five
  points, giving meaningless fits. A Convention B fit now needs at least 3 points (a 2-point line always has R2 = 1).
  `--onset smallest-gap` reproduces the old rule. Results for a case should be compared under both rules before they are reported.
- `extract_point_forces.py` accepts any case ID. Version 1.0.0 silently skipped every ID that did not start with two particular
  initials. It also names any missing column of the tracking spreadsheet instead of stopping with a KeyError.
- A case ID is now a required argument. Version 1.0.0 defaulted to a particular case in several scripts.
- The interactive tools (`calibrate_reference.py`, `measure_hiatal_position.py`, `measure_suture.py`) no longer force the macOS
  plot backend, so they can run on Linux and Windows. `MPLBACKEND` selects another backend. `verify_force.py` says clearly that it
  needs macOS.

### Removed from the run order
- `add_timestamp.py` (burning a time label into a re-encoded copy) is not needed and is not part of the workflow. The file
  is kept only for people who want a labelled copy for viewing.
- Cutting a video clip for each point is not needed.
- Version 1.0.0's `<case_id>_suture_entry.json/.xlsx` are not read.

### Migration from 1.0.0
Re-run the pipeline from `index_video.py`. Calibration files made by `calibrate_reference.py` and the force workbook inputs
(`parse_force_api.py`) are unchanged in format.

## 1.0.0 - baseline
First public release (one frame per force second, timestamped re-encode, per-clip workflow).
