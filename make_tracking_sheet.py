"""
make_tracking_sheet.py — Create the tracking spreadsheet (Hiatal tension patients.xlsx) with the exact column headers.

extract_point_forces.py reads each point's start and end from this sheet, and it stops with an error naming any
column that is missing. This script writes the header row (Study ID, then Point A start, Point A end, ... Point D end)
and one empty row per case ID you give, so nothing has to be typed by hand but the times.

Fill in the times as HH:MM:SS, read in your media player (video time). Leave a point's cells empty if it was
not measured. Use a code for the case ID, not a name or record number: it also names the folder Videos/<case_id>/.

An existing file is never overwritten.

Usage:
    python3 make_tracking_sheet.py <case_id> [<case_id> ...] [--out FILE]
    --out FILE   where to write the sheet [Hiatal tension patients.xlsx in this folder]
"""

import argparse
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

import framelib as fl

BASE = Path(__file__).resolve().parent
HEADERS = ["Study ID"] + [f"Point {p} {side}" for p in "ABCD" for side in ("start", "end")]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case_ids", nargs="+", metavar="case_id", help="case IDs to put in the Study ID column")
    ap.add_argument("--out", default=None, help="output file [Hiatal tension patients.xlsx in this folder]")
    ap.add_argument("--version", action="version", version=f"%(prog)s {fl.PIPELINE_VERSION}")
    args = ap.parse_args(argv)

    out = Path(args.out) if args.out else BASE / "Hiatal tension patients.xlsx"
    if out.exists():
        sys.exit(f"ERROR: {out} already exists; it was not overwritten. Add the case IDs to it by hand, "
                 "or choose another file with --out.")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tracking"
    ws.append(HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True)
    for case in args.case_ids:
        ws.append([case] + [None] * 8)
    for letter in "ABCDEFGHI":
        ws.column_dimensions[letter].width = 16
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print(f"Saved: {out}\nFill in the Point A-D start and end times (HH:MM:SS, video time) for: {', '.join(args.case_ids)}")


if __name__ == "__main__":
    main()
