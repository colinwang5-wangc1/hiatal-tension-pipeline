# Hiatal Tension Pipeline

Computational pipeline for extracting synchronized force and crural gap
deformation data from da Vinci 5 surgical platform recordings, developed to
support in vivo measurement of crural closure tension during robotic hiatal
hernia repair.

The pipeline requires no additional instrumentation: it uses per-arm force
data already recorded by the da Vinci 5 console and endoscope video already
captured during the procedure.

## Pipeline stages

| Script | Purpose |
|---|---|
| `parse_force_api.py` | Parses the raw `forceTimeline` JSON exported from the da Vinci console's web interface into per-arm and combined force time series (Excel/CSV) |
| `add_timestamp.py` | Burns an absolute `HH:MM:SS.mmm` timestamp onto every frame of the full case video, producing a frame-accurate reference video |
| `extract_point_forces.py` | Extracts force readings within annotated time windows of interest from the parsed force data |
| `calibrate_reference.py` | Interactive tool for pixel-to-millimeter spatial calibration; supports both a full ruler-based calibration and a landmark-only per-clip calibration to correct for depth-dependent scale variation |
| `mark_suture_entry.py` | Interactive tool for manually annotating paired anatomical landmark positions (e.g., left/right crus entry points) frame-by-frame at each force data timestamp, converting pixel distance to millimeters |
| `measure_hiatal_position.py` | Interactive tool for measuring the position of each annotated point along a defined anatomical long axis, using a single reference frame |
| `merge_distance_force.py` | Merges the crural distance measurements from `mark_suture_entry.py` into the force Excel and computes a combined Total Force column, producing the file `fit_moduli.py` expects |
| `fit_moduli.py` | Converts paired force/distance measurements to strain and fits one-parameter constitutive models (linear, Neo-Hookean) to force-strain data |
| `measure_suture.py` | Secondary calibration utility: estimates px/mm from the known physical diameter of visible suture material |
| `verify_force.py` | Utility for spot-checking parsed force data against source values. macOS-only — uses Apple's Vision framework for OCR |

## Getting the input data

Force data is obtained from the da Vinci console's companion web interface,
which serves a per-case JSON blob containing millisecond-precise force
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

Corresponding endoscope video for the same case is required for the
video-based stages of the pipeline (timestamping, calibration, distance
annotation).

## Required per-case tracking spreadsheet

`calibrate_reference.py`, `extract_point_forces.py`, and `mark_suture_entry.py`
all read from and/or write to a spreadsheet named `Hiatal tension patients.xlsx`
in the repository root. This file is intentionally **not** included (it is
per-patient tracking data) — create your own with a header row containing at
least:

| Column | Meaning |
|---|---|
| `Study ID` | Case identifier, must match `<case_id>` used elsewhere (e.g. `YV003`) |
| `Point A start`, `Point A end` | `HH:MM:SS` window during which point A's suture is tied, per the console timeline |
| `Point B start`, `Point B end` | Same, for point B |
| `Point C start`, `Point C end` | Same, for point C |
| `Point D start`, `Point D end` | Same, for point D |

One row per case. Points with no start/end filled in are skipped by
`extract_point_forces.py`. `calibrate_reference.py` will also append
calibration columns (`px_per_mm_ruler`, `landmark_mm`, etc.) to this same
file automatically the first time it's run for a case.

## Usage

Each script is run independently and takes a case identifier and/or file
paths as arguments; run any script with no arguments (or see its module
docstring) for usage details. All scripts resolve paths relative to their
own location by default and expect a `Videos/<case_id>/` subdirectory
structure for per-case inputs and outputs.

Clip extraction (producing `Videos/<case_id>/clips/A/<case_id>_A.mp4`, etc.,
one short clip per point) is a manual step (e.g. via `ffmpeg` or QuickTime)
using the start/end times from the tracking spreadsheet above — no script in
this repo does this for you.

A typical end-to-end run for a new case:

```bash
mkdir -p "Videos/<case_id>/force_data"
# place <case_id>_force_raw.json in Videos/<case_id>/force_data/ (see above)

python3 parse_force_api.py "Videos/<case_id>/force_data/<case_id>_force_raw.json" <case_id>
python3 add_timestamp.py "Videos/<case_id>/<case_id>_full.mp4"
python3 calibrate_reference.py "Videos/<case_id>/calibration_frame.png" <case_id>
python3 extract_point_forces.py <case_id>

# manually cut Videos/<case_id>/clips/A/<case_id>_A.mp4 (and B, C, D) here

python3 mark_suture_entry.py "Videos/<case_id>/clips/A/<case_id>_A.mp4" <case_id> A
# repeat mark_suture_entry.py for clips B, C, D

python3 merge_distance_force.py <case_id>
python3 measure_hiatal_position.py "Videos/<case_id>/calibration_frame.png" <case_id>
python3 fit_moduli.py <case_id>
```

## Dependencies

```bash
pip install -r requirements.txt
```

`verify_force.py` is an optional, macOS-only diagnostic utility — its
dependencies (`pyobjc-framework-Cocoa`, `pyobjc-framework-Vision`) are only
installed on macOS and are not required to run the rest of the pipeline.

## Data availability

This repository contains analysis code only. No patient data, video, or
identifiable information is included. See the associated manuscript for the
data availability statement covering de-identified derived measurements.

## Citation

[PLACEHOLDER: citation for the associated manuscript, to be added upon
publication]
