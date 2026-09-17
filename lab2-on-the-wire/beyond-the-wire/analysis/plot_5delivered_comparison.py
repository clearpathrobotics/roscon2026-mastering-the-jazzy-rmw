#!/usr/bin/env python3
"""
Usage:
    plot_5delivered_comparison.py <fast-arrivals.csv> <cyclone-arrivals.csv> \
        <zenoh-arrivals.csv> <fast-markers.csv> <cyclone-markers.csv> \
        <zenoh-markers.csv> <camera-output.png> <scan-output.png> [title]

Compare delivered camera and scan messages for Fast DDS, Cyclone DDS, and
Zenoh. Each arrivals CSV must contain ``t_epoch,robot,topic`` and each marker
CSV must contain ``epoch,label``. Timestamps are normalized to each run's
first marker. For each RMW, robot 1, 2, and 3 are averaged at every plotted
time sample, rather than treating the aggregate fleet as one stream.

Each output has stacked received-message-rate and interarrival-jitter plots.
The two output files contain the camera and scan comparisons respectively.
"""

import csv
import statistics
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

RMW_COLORS = {
	"Fast DDS": "#E67E22",
	"Cyclone DDS": "#2980B9",
	"Zenoh": "#27AE60",
}
BAND_TINTS = ["#2ECC71", "#F1C40F", "#E67E22", "#E74C3C", "#8E44AD", "#7F8C8D"]
RATE_WIN = 2.0
RATE_HOP = 0.5
JIT_N = 15
JIT_YMAX = 300
ROBOTS = (1, 2, 3)


def load_arrivals(path):
	"""Return ``{topic: {robot: [absolute timestamps]}}`` from a CSV."""
	result = {"camera": {robot: [] for robot in ROBOTS},
			  "scan": {robot: [] for robot in ROBOTS}}
	with Path(path).open(newline="") as stream:
		for row in csv.reader(stream):
			if not row or row[0] == "t_epoch" or len(row) < 3:
				continue
			topic = row[2]
			robot = int(row[1])
			if topic in result and robot in result[topic]:
				result[topic][robot].append(float(row[0]))
	return result


def load_markers(path):
	"""Return sorted ``(absolute timestamp, label)`` marker rows."""
	with Path(path).open(newline="") as stream:
		return sorted(
			(float(row[0]), row[1])
			for row in csv.reader(stream)
			if row and row[0] != "epoch"
		)


def normalize_run(arrivals, markers):
	"""Normalize one run to its first marker and return its usable span."""
	if not markers:
		raise ValueError("marker CSV is empty")
	t0 = markers[0][0]
	relative = {
		topic: {
			robot: [timestamp - t0 for timestamp in timestamps if timestamp >= t0]
			for robot, timestamps in robots.items()
		}
		for topic, robots in arrivals.items()
	}
	end = markers[-1][0] - t0
	return relative, [(timestamp - t0, label) for timestamp, label in markers], end


def average_rate(robot_times, x):
	"""Average robot rates in a centered rolling window at relative time x."""
	lo, hi = x - RATE_WIN / 2, x + RATE_WIN / 2
	rates = [sum(lo <= timestamp < hi for timestamp in robot_times[robot]) / RATE_WIN
		 for robot in ROBOTS]
	return sum(rates) / len(rates)


def average_jitter(robot_times, x):
	"""Average per-robot jitter over the most recent ``JIT_N`` gaps."""
	values = []
	for robot in ROBOTS:
		timestamps = sorted(robot_times[robot])
		gaps = [timestamps[index + 1] - timestamps[index]
			for index in range(len(timestamps) - 1)
			if timestamps[index + 1] <= x]
		if len(gaps) >= JIT_N:
			values.append(statistics.pstdev(gaps[-JIT_N:]) * 1000)
	return sum(values) / len(values) if values else None


def draw_bands(axes, marker_sets, span):
	"""Draw averaged marker boundaries and the shared netem band colors."""
	positions = {}
	for markers in marker_sets:
		for timestamp, label in markers:
			if label != "end":
				positions.setdefault(label, []).append(timestamp)
	boundaries = sorted(
		(sum(values) / len(values), label)
		for label, values in positions.items()
	)
	for index, (start, label) in enumerate(boundaries):
		if start >= span:
			continue
		finish = min(boundaries[index + 1][0] if index + 1 < len(boundaries) else span, span)
		for axis in axes:
			axis.axvspan(start, finish, color=BAND_TINTS[index % len(BAND_TINTS)],
					 alpha=0.10, lw=0)
			axis.axvline(start, color="#888", ls="--", lw=0.8)
		axes[0].text((start + finish) / 2, 0.97, label,
					 transform=axes[0].get_xaxis_transform(), ha="center",
					 va="top", fontsize=8, color="#555")


def plot_topic(topic, runs, marker_sets, output_path, title):
	span = min(markers[-1][0] for markers in marker_sets)
	x_values = []
	x = 0.0
	while x <= span:
		x_values.append(x)
		x += RATE_HOP

	fig, (rate_axis, jitter_axis) = plt.subplots(2, 1, sharex=True, figsize=(10, 6))
	draw_bands((rate_axis, jitter_axis), marker_sets, span)
	for name, color, arrivals in runs:
		rate_times = [average_rate(arrivals[topic], x) for x in x_values]
		jitter_times = [average_jitter(arrivals[topic], x) for x in x_values]
		rate_axis.plot(x_values, rate_times, color=color, lw=1.8, label=name)
		jitter_axis.plot(
			x_values,
			[float("nan") if value is None else value for value in jitter_times],
			color=color,
			lw=1.3,
		)

	rate_axis.set_ylabel("received messages/s")
	rate_axis.set_ylim(bottom=0)
	rate_axis.grid(True, alpha=0.25)
	jitter_axis.set_ylabel("interarrival\njitter (ms)")
	jitter_values = [
		value
		for _, _, arrivals in runs
		for x in x_values
		for value in [average_jitter(arrivals[topic], x)]
		if value is not None
	]
	jitter_axis.set_ylim(0, max(JIT_YMAX, max(jitter_values, default=0)))
	jitter_axis.grid(True, alpha=0.25)
	jitter_axis.set_xlabel("time (s)   |   shaded bands = netem profile (worsening left to right)")
	jitter_axis.set_xlim(0, span)
	fig.suptitle(title, y=0.99, fontsize=12)
	fig.legend(handles=[Line2D([0], [0], color=color, lw=1.8, label=name)
				   for name, color in RMW_COLORS.items()],
			   loc="upper center", ncol=3, frameon=False, fontsize=9,
			   bbox_to_anchor=(0.5, 0.95))
	fig.tight_layout(rect=(0, 0, 1, 0.92))
	fig.savefig(output_path, dpi=130)
	plt.close(fig)
	print(f"wrote {output_path}")


def main():
	if len(sys.argv) < 9:
		print(__doc__)
		raise SystemExit(1)
	arrival_paths = sys.argv[1:4]
	marker_paths = sys.argv[4:7]
	camera_output, scan_output = sys.argv[7:9]
	title = sys.argv[9] if len(sys.argv) > 9 else "Delivered messages by RMW"

	runs = []
	marker_sets = []
	for name, color, arrival_path, marker_path in zip(
		RMW_COLORS, RMW_COLORS.values(), arrival_paths, marker_paths
	):
		arrivals, markers, span = normalize_run(
			load_arrivals(arrival_path), load_markers(marker_path)
		)
		runs.append((name, color, arrivals))
		marker_sets.append(markers)
	plot_topic("camera", runs, marker_sets, camera_output, f"{title} - camera")
	plot_topic("scan", runs, marker_sets, scan_output, f"{title} - scan")


if __name__ == "__main__":
	main()
