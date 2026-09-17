#!/usr/bin/env python3
"""
Usage:
	plot_4camera_comparison.py <fast-arrivals.csv> <cyclone-arrivals.csv> \
		<zenoh-arrivals.csv> <fast-markers.csv> <cyclone-markers.csv> \
		<zenoh-markers.csv> <output.png> [title]

Compare application-delivered camera frames per second for Fast DDS, Cyclone
DDS, and Zenoh. Each arrivals CSV must contain ``t_epoch,robot,topic`` and
each marker CSV must contain ``epoch,label``. The timestamps do not need to be
from the same wall-clock run: each series is normalized to its own first
marker so the netem bands line up.

The clean-band camera rate is averaged across the three runs and retained as a
horizontal offered-load reference. The output uses the shared netem band
palette and the established Fast (orange), Cyclone (blue), and Zenoh (green)
colors.
"""

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

RMW_COLORS = {
	"Fast DDS": "#E67E22",
	"Cyclone DDS": "#2980B9",
	"Zenoh": "#27AE60",
}
BAND_TINTS = ["#2ECC71", "#F1C40F", "#E67E22", "#E74C3C", "#8E44AD", "#7F8C8D"]


def load_arrivals(path):
	"""Return camera arrival timestamps from an arrivals CSV."""
	arrivals = []
	with Path(path).open(newline="") as stream:
		for row in csv.reader(stream):
			if not row or row[0] == "t_epoch" or len(row) < 3 or row[2] != "camera":
				continue
			arrivals.append(float(row[0]))
	return sorted(arrivals)


def load_markers(path):
	"""Return sorted ``(epoch, label)`` marker rows."""
	markers = []
	with Path(path).open(newline="") as stream:
		for row in csv.reader(stream):
			if not row or row[0] == "epoch":
				continue
			markers.append((float(row[0]), row[1]))
	return sorted(markers)


def relative_data(arrivals, markers):
	"""Return relative camera times, relative markers, and clean-band rate."""
	if not arrivals:
		raise ValueError("arrival CSV contains no camera rows")
	if len(markers) < 2:
		raise ValueError("marker CSV must contain at least clean and end markers")

	t0 = markers[0][0]
	relative_arrivals = [t - t0 for t in arrivals if t >= t0]
	relative_markers = [(t - t0, label) for t, label in markers]
	clean_end = relative_markers[1][0]
	clean_count = sum(0 <= t < clean_end for t in relative_arrivals)
	offered = clean_count / clean_end if clean_end > 0 else 0.0
	end = relative_markers[-1][0]
	return relative_arrivals, relative_markers, offered, end


def per_second_rate(times, span):
	"""Return one-second camera counts over ``[0, span)``."""
	count = int(span) + 1
	rates = [0] * count
	for timestamp in times:
		second = int(timestamp)
		if 0 <= second < count:
			rates[second] += 1
	return list(range(count)), rates


def draw_bands(ax, marker_sets, span):
	"""Draw the shared netem bands using normalized marker positions."""
	starts = {}
	for markers in marker_sets:
		for timestamp, label in markers:
			if label != "end":
				starts.setdefault(label, []).append(timestamp)
	boundaries = sorted((sum(values) / len(values), label)
						for label, values in starts.items())
	for index, (start, label) in enumerate(boundaries):
		if start >= span:
			continue
		next_start = boundaries[index + 1][0] if index + 1 < len(boundaries) else span
		next_start = min(next_start, span)
		ax.axvspan(start, next_start, color=BAND_TINTS[index % len(BAND_TINTS)],
				   alpha=0.10, lw=0)
		ax.axvline(start, color="#888", ls="--", lw=0.8)
		ax.text((start + next_start) / 2, 0.97, label,
				transform=ax.get_xaxis_transform(), ha="center", va="top",
				fontsize=8, color="#555")


def main():
	if len(sys.argv) < 8:
		print(__doc__)
		raise SystemExit(1)

	arrival_paths = sys.argv[1:4]
	marker_paths = sys.argv[4:7]
	output_path = sys.argv[7]
	title = sys.argv[8] if len(sys.argv) > 8 else "Camera frames received by RMW"

	series = []
	marker_sets = []
	offered_rates = []
	span = 0.0
	for name, color, arrival_path, marker_path in zip(
			RMW_COLORS, RMW_COLORS.values(), arrival_paths, marker_paths):
		arrivals = load_arrivals(arrival_path)
		relative_arrivals, markers, offered, end = relative_data(
			arrivals, load_markers(marker_path))
		series.append((name, color, relative_arrivals))
		marker_sets.append(markers)
		offered_rates.append(offered)
		span = max(span, end)

	offered = sum(offered_rates) / len(offered_rates)
	fig, ax = plt.subplots(figsize=(10, 5))
	draw_bands(ax, marker_sets, span)
	for name, color, arrivals in series:
		x, rate = per_second_rate(arrivals, span)
		ax.plot(x, rate, color=color, lw=1.8, label=name)

	ax.axhline(offered, color="#7F8C8D", ls="--", lw=1.2,
			   label=f"offered ~{offered:.0f} frames/s")
	ax.set_title(title)
	ax.set_ylabel("camera frames/s (all robots)")
	ax.set_xlabel("time (s)   |   shaded bands = netem profile (worsening left to right)")
	ax.set_xlim(0, span)
	ax.set_ylim(bottom=0)
	ax.grid(True, alpha=0.25)
	ax.legend(frameon=False, loc="upper right")
	fig.tight_layout()
	fig.savefig(output_path, dpi=130)
	plt.close(fig)
	print(f"wrote {output_path}")


if __name__ == "__main__":
	main()
