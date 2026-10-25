#!/usr/bin/env python3
"""
parse_force_api.py  –  Convert raw force JSON from my.intuitive.com to Excel/CSV.

The JSON has the structure:
  {
    "USM1": [ {"x": <seconds>, "y": <force_N>, "z": <metadata or null>}, ... ],
    "USM2": [ ... ],
    ...
  }

Where:
  x = seconds from case start (integer)
  y = force in Newtons (float)
  z = {"sensitivity": "Low"|"Medium"|"High"|"Off", "instrument": "<name>"} or null

Usage:
    python parse_force_api.py <input.json> [patient_id]

Output:
    One Excel file per arm: <patient_id>_USM1_force.xlsx, etc.
    One combined Excel file: <patient_id>_all_arms_force.xlsx
"""

import argparse
import json
import sys
import os
import pandas as pd
from pathlib import Path

import framelib


def seconds_to_hms(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_arm(arm_name: str, data: list) -> pd.DataFrame:
    rows = []
    for entry in data:
        x = entry.get("x")
        y = entry.get("y")
        z = entry.get("z")

        if x is None or y is None:
            continue

        row = {
            "Timestamp":   seconds_to_hms(x),
            "Seconds":     x,
            "Force (N)":   y,
            "Arm":         arm_name,
            "Instrument":  z.get("instrument", "") if z else "",
            "Sensitivity": z.get("sensitivity", "") if z else "",
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    return df


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="raw force JSON exported from my.intuitive.com")
    ap.add_argument("patient_id", nargs="?", help="case ID used to name the output files [the input file name]")
    ap.add_argument("--version", action="version", version=f"%(prog)s {framelib.PIPELINE_VERSION}")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    json_path = Path(args.input)
    if not json_path.exists():
        print(f"Error: file not found: {json_path}")
        sys.exit(1)

    patient_id = args.patient_id if args.patient_id else json_path.stem
    out_dir = json_path.parent

    with open(json_path) as f:
        data = json.load(f)

    print(f"Arms found: {list(data.keys())}")

    all_dfs = []
    for arm_name, arm_data in data.items():
        if not isinstance(arm_data, list):
            print(f"  Skipping {arm_name} (not a list)")
            continue

        df = parse_arm(arm_name, arm_data)
        if df.empty:
            print(f"  {arm_name}: no data")
            continue

        # Filter to rows with an instrument docked, for the diagnostic summary below
        # (does not filter on force value — zeros are kept in the saved output)
        df_active = df[df["Instrument"] != ""].copy()

        print(f"\n  {arm_name}: {len(df)} total entries, {len(df_active)} with instrument active")
        print(f"    Time range: {df['Timestamp'].iloc[0]} → {df['Timestamp'].iloc[-1]}")
        if not df_active.empty:
            instruments = df_active["Instrument"].unique()
            print(f"    Instruments: {', '.join(instruments)}")
            print(f"    Force range: {df_active['Force (N)'].min():.1f} – {df_active['Force (N)'].max():.1f} N")

        # Save per-arm file (all entries including zeros)
        xlsx_path = out_dir / f"{patient_id}_{arm_name}_force.xlsx"
        csv_path  = out_dir / f"{patient_id}_{arm_name}_force.csv"

        cols = ["Timestamp", "Seconds", "Force (N)", "Arm", "Instrument", "Sensitivity"]
        df[cols].to_excel(xlsx_path, index=False)
        df[cols].to_csv(csv_path, index=False)
        print(f"    Saved: {xlsx_path}")
        print(f"    Saved: {csv_path}")

        df["Arm"] = arm_name
        all_dfs.append(df[cols])

    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True).sort_values(["Arm", "Seconds"])
        combined_path = out_dir / f"{patient_id}_all_arms_force.xlsx"
        combined.to_excel(combined_path, index=False)
        print(f"\nCombined file saved: {combined_path}")
        print(f"Total rows: {len(combined)}")


if __name__ == "__main__":
    main()
