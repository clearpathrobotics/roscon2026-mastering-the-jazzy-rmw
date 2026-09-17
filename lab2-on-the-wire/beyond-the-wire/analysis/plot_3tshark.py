#!/usr/bin/env python3
"""
Usage:
    plot_3tshark.py <timestamp>
    plot_3tshark.py <capture.pcap>

With a timestamp, read ``fleet_<timestamp>.pcap`` from ``CAPTURES_DIR``. With
an explicit PCAP path, read that file directly. In both cases, markers are
loaded from ``<timestamp>.markers.csv`` in ``CAPTURES_DIR`` when available.
``CAPTURES_DIR`` defaults to ``/captures``.

Write ``<timestamp>_timeline.png`` to ``CAPTURES_DIR``. The output has two
panels sharing a wall-clock axis, with one colored line per robot:

    top    complete-frame delivery interval in milliseconds, which is the gap
                 between successfully reassembled image frames, not one-way latency
    bottom image frames lost per second, where an incomplete DATA_FRAG set counts
                 as a lost frame
"""

import math
import matplotlib
import numpy as np
import os
import pandas as pd
import subprocess
import sys

from collections import defaultdict
from pathlib import Path

matplotlib.use("Agg")
import matplotlib.pyplot as plt

CAPTURES_DIR = Path(os.environ.get("CAPTURES_DIR", "/captures"))

IP_ROBOT = {"172.30.10.11": "mock-robot-1",
            "172.30.10.12": "mock-robot-2",
            "172.30.10.13": "mock-robot-3"}
ROBOT_COLORS = {"mock-robot-1": "#E67E22", "mock-robot-2": "#2980B9", "mock-robot-3": "#27AE60"}
DEFAULT_COLOR = "#7F8C8D"
SEVERITY = {"wifi_marginal": 0.10, "wifi_good": 0.14, "wifi_lossy": 0.18,
            "wifi_bad": 0.24, "congested": 0.30}


def run_tshark(pcap, fields, dfilter):
    cmd = ["tshark", "-r", str(pcap), "-Y", dfilter, "-T", "fields", "-E", "separator=|"]
    for f in fields:
        cmd += ["-e", f]
    out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()
    return [line.split("|") for line in out.splitlines() if line.strip()]


def first(v):
    return v.split(",")[0].strip() if v else ""


def load_samples(pcap):
    """Return dict robot -> list of (first_time, complete_bool)."""
    rows = run_tshark(pcap,
                      ["frame.time_epoch", "ip.src", "rtps.sm.seqNumber",
                       "rtps.data_frag.num_fragments", "rtps.data_frag.sample_size",
                       "rtps.data_frag.size"],
                      "rtps.sm.id==0x16")
    agg = defaultdict(lambda: [0, 0, None])  # (src,seq) -> [recv, expected, first_t]
    for p in rows:
        if len(p) < 6:
            continue
        src, seq = first(p[1]), first(p[2])
        ssize, fsize = first(p[4]), first(p[5])
        if not (src in IP_ROBOT and seq and ssize and fsize):
            continue
        try:
            t = float(first(p[0]))
            recv = int(first(p[3])) if first(p[3]) else 1
            exp = math.ceil(int(ssize) / int(fsize))
        except ValueError:
            continue
        a = agg[(src, seq)]
        a[0] += recv
        a[1] = max(a[1], exp)
        a[2] = t if a[2] is None else min(a[2], t)

    per_robot = defaultdict(list)
    for (src, seq), (recv, exp, t) in agg.items():
        per_robot[IP_ROBOT[src]].append((t, exp > 0 and recv >= exp))
    return per_robot


def load_markers(ts):
    path = CAPTURES_DIR / f"{ts}.markers.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path)
    return list(zip(df["epoch"].astype(float), df["label"].astype(str)))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    arg = sys.argv[1]
    if arg.endswith(".pcap") or Path(arg).exists():
        pcap = Path(arg)
        ts = pcap.stem.replace("fleet_", "")
    else:
        ts = arg
        pcap = CAPTURES_DIR / f"fleet_{ts}.pcap"

    per_robot = load_samples(pcap)
    if not per_robot:
        print("No DATA_FRAG image samples found, nothing to plot")
        sys.exit(1)
    markers = load_markers(ts)

    all_t = [t for rows in per_robot.values() for t, _ in rows]
    t0 = min(all_t + [ep for ep, _ in markers]) if markers else min(all_t)
    span_end = max(all_t) - t0

    fig, (ax_lat, ax_loss) = plt.subplots(2, 1, sharex=True, figsize=(11, 7))

    for robot in sorted(per_robot):
        color = ROBOT_COLORS.get(robot, DEFAULT_COLOR)
        rows = sorted(per_robot[robot])
        # top: delivery interval between COMPLETE frames
        done = np.array([t - t0 for t, ok in rows if ok])
        if len(done) >= 2:
            interval = np.diff(done) * 1000.0
            s = pd.Series(interval, index=done[1:]).rolling(5, min_periods=1).median()
            ax_lat.plot(s.index, s.values, color=color, lw=1.6, label=robot)
        # bottom: lost frames per second
        lost = np.array([t - t0 for t, ok in rows if not ok])
        if len(lost):
            edges = np.arange(0, np.ceil(span_end) + 1, 1.0)
            counts, _ = np.histogram(lost, bins=edges)
            ax_loss.plot(edges[:-1], counts, color=color, lw=1.6, label=robot)

    xs = [ep - t0 for ep, _ in markers]
    bounds = xs + [span_end]
    for ax in (ax_lat, ax_loss):
        for i, (_, lab) in enumerate(markers):
            ax.axvspan(bounds[i], bounds[i + 1], color="red", alpha=SEVERITY.get(lab, 0.15), lw=0)
            ax.axvline(xs[i], color="0.3", ls="--", lw=1)
    if markers:
        ymax = ax_lat.get_ylim()[1]
        for ep, lab in markers:
            ax_lat.text(ep - t0, ymax * 0.98, lab, rotation=90, va="top", ha="right",
                        fontsize=8, color="0.25")

    ax_lat.set_title(f"Image frames over a degrading link (per robot) - {ts}")
    ax_lat.set_ylabel("complete-frame\ndelivery interval (ms)")
    ax_lat.legend(loc="upper left", fontsize=8)
    ax_lat.grid(True, alpha=0.3)
    ax_loss.set_ylabel("image frames lost / s")
    ax_loss.set_xlabel("time since capture start (s)")
    ax_loss.grid(True, alpha=0.3)

    fig.tight_layout()
    out = CAPTURES_DIR / f"{ts}_timeline.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"written: {out}")


if __name__ == "__main__":
    main()
