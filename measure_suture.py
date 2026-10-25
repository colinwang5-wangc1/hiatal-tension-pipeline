"""
measure_suture.py — Calibrate pixels/mm using a suture of known diameter.

Usage:
    python3 measure_suture.py <image.png>

Instructions:
    1. Click TWO points along the suture (defines its direction)
    2. The script extracts a perpendicular intensity profile through the midpoint
    3. Measures the suture width in pixels using the blue channel FWHM
    4. Outputs pixels/mm calibration factor (based on 0 Prolene = 0.35mm)

The plot window uses matplotlib's default interactive backend for your platform. Set the
MPLBACKEND environment variable (for example TkAgg or QtAgg) to choose another.
"""

import argparse
import sys
import numpy as np
import cv2
import matplotlib.pyplot as plt
from matplotlib.widgets import Button

import framelib

SUTURE_DIAMETER_MM = 0.35  # USP 0 Prolene

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("image", help="a frame showing the suture (PNG/TIFF at the video's native resolution)")
ap.add_argument("--version", action="version", version=f"%(prog)s {framelib.PIPELINE_VERSION}")
img_path = ap.parse_args().image

img_bgr = cv2.imread(img_path)
if img_bgr is None:
    sys.exit(f"ERROR: cannot read the image: {img_path}")
img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

clicks = []
profile_data = {}

fig, axes = plt.subplots(1, 2, figsize=(14, 6))
ax_img, ax_profile = axes

ax_img.imshow(img_rgb)
ax_img.set_title("Click TWO points along the suture")
ax_img.axis("off")

ax_profile.set_title("Perpendicular intensity profile (blue channel)")
ax_profile.set_xlabel("Pixels from center")
ax_profile.set_ylabel("Blue channel intensity")

def extract_profile(img, p1, p2, half_width=20):
    """Extract intensity profile perpendicular to the line p1->p2 at midpoint."""
    mx = (p1[0] + p2[0]) / 2
    my = (p1[1] + p2[1]) / 2

    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    length = np.sqrt(dx**2 + dy**2)
    dx /= length
    dy /= length

    # Perpendicular direction
    px, py = -dy, dx

    h, w = img.shape[:2]
    values = []
    positions = range(-half_width, half_width + 1)
    for t in positions:
        x = int(round(mx + t * px))
        y = int(round(my + t * py))
        if 0 <= x < w and 0 <= y < h:
            values.append(img[y, x, 2])  # blue channel (RGB)
        else:
            values.append(0)

    return list(positions), values, (mx, my), (px, py)

def measure_fwhm(positions, values):
    """Measure full width at half maximum of the peak."""
    vals = np.array(values, dtype=float)
    peak_idx = np.argmax(vals)
    peak_val = vals[peak_idx]
    half_max = (peak_val + np.min(vals)) / 2

    # Find left edge
    left = peak_idx
    while left > 0 and vals[left] > half_max:
        left -= 1

    # Find right edge
    right = peak_idx
    while right < len(vals) - 1 and vals[right] > half_max:
        right += 1

    fwhm = right - left
    return fwhm, half_max, positions[left], positions[right]

def onclick(event):
    if event.inaxes != ax_img:
        return
    if len(clicks) >= 2:
        return

    x, y = int(event.xdata), int(event.ydata)
    clicks.append((x, y))
    ax_img.plot(x, y, 'yo', markersize=8)
    fig.canvas.draw()

    if len(clicks) == 2:
        p1, p2 = clicks
        ax_img.plot([p1[0], p2[0]], [p1[1], p2[1]], 'y-', linewidth=1.5)

        positions, values, midpoint, perp = extract_profile(img_rgb, p1, p2)
        profile_data['positions'] = positions
        profile_data['values'] = values
        profile_data['midpoint'] = midpoint
        profile_data['perp'] = perp

        # Draw perpendicular line on image
        hw = 20
        x0 = int(midpoint[0] - hw * perp[0])
        y0 = int(midpoint[1] - hw * perp[1])
        x1 = int(midpoint[0] + hw * perp[0])
        y1 = int(midpoint[1] + hw * perp[1])
        ax_img.plot([x0, x1], [y0, y1], 'c-', linewidth=1.5)

        # Plot profile
        ax_profile.clear()
        ax_profile.plot(positions, values, 'b-', linewidth=1.5)
        ax_profile.set_title("Perpendicular intensity profile (blue channel)")
        ax_profile.set_xlabel("Pixels from center")
        ax_profile.set_ylabel("Blue channel intensity")

        fwhm, half_max, left_pos, right_pos = measure_fwhm(positions, values)
        ax_profile.axhline(half_max, color='gray', linestyle='--', alpha=0.7, label='half max')
        ax_profile.axvline(left_pos, color='red', linestyle='--', alpha=0.7)
        ax_profile.axvline(right_pos, color='red', linestyle='--', alpha=0.7)
        ax_profile.fill_betweenx([0, max(values)], left_pos, right_pos, alpha=0.15, color='red')

        px_per_mm = fwhm / SUTURE_DIAMETER_MM
        ax_profile.set_title(
            f"FWHM = {fwhm} px  |  {SUTURE_DIAMETER_MM}mm suture  →  {px_per_mm:.1f} px/mm  ({1/px_per_mm*1000:.2f} µm/px)"
        )

        print(f"\nSuture width (FWHM): {fwhm} pixels")
        print(f"Suture diameter: {SUTURE_DIAMETER_MM} mm (USP 0 Prolene)")
        print(f"Calibration: {px_per_mm:.2f} px/mm  |  {1/px_per_mm:.4f} mm/px")

        fig.canvas.draw()

fig.canvas.mpl_connect('button_press_event', onclick)
plt.tight_layout()
plt.show()
