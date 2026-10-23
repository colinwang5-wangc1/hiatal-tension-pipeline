# Changelog

Versions follow `MAJOR.MINOR.PATCH`. A change of MAJOR version means file formats or the run order changed and
files written by another major version are not read. The current version is in `VERSION`; every output file records
the version that wrote it.

## 2.0.0 - per-frame workflow (development copy, not yet released)

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
