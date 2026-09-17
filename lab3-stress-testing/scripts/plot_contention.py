#!/usr/bin/env python3
# plot_contention.py - chart the shared AP budget from ap_shape.sh sample output.
#
# The routed-peer topology funnels every peer flow through one shaped budget at the
# wifi-ap. `ap_shape.sh sample` writes that queue's cumulative counters as CSV; this
# renders them as three timelines - uplink throughput (the shared ceiling), drops
# (contention across the fleet), and backlog. Self-contained: reads the CSV, writes a
# PNG, no repo dependencies (matplotlib only).
#
# Usage (from the prototype directory):
#   bash scripts/ap_shape.sh bad
#   bash scripts/ap_shape.sh sample 30 1 > tc_samples.csv        # 30s @ 1s interval
#   python3 scripts/plot_contention.py tc_samples.csv            # -> tc_samples.png
#   python3 scripts/plot_contention.py tc_samples.csv markers.csv -o run.png
#
# markers.csv is optional: rows of `elapsed,label` drawn as vertical annotations
# (e.g. one line per profile change during the run).
import argparse
import csv
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless; no DISPLAY needed
import matplotlib.pyplot as plt  # noqa: E402


def load_csv(path: str | None) -> list[dict]:
    if not path:
        return []
    p = Path(path)
    if not p.is_file():
        return []
    with p.open() as f:
        return list(csv.DictReader(f))


def per_sec_rate(t: list[float], cum: list[float]) -> list[float]:
    """Per-second rate from a cumulative counter. A profile change resets the qdisc,
    so the counter drops; clamp those negative deltas to 0."""
    out = [0.0]
    for i in range(1, len(cum)):
        dt = (t[i] - t[i - 1]) or 1.0
        out.append(max(cum[i] - cum[i - 1], 0.0) / dt)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Plot the shared AP budget from ap_shape.sh sample CSV.")
    ap.add_argument("samples", help="tc_samples.csv from `ap_shape.sh sample`")
    ap.add_argument("markers", nargs="?", help="optional markers.csv (elapsed,label)")
    ap.add_argument("-o", "--out", help="output PNG (default: <samples>.png)")
    ap.add_argument("--title", default="Routed-peer shared AP budget")
    args = ap.parse_args()

    rows = load_csv(args.samples)
    if len(rows) < 2:
        print(f"need >=2 samples in {args.samples}; got {len(rows)}", file=sys.stderr)
        return 1
    try:
        t = [float(r["elapsed"]) for r in rows]
        tx_mbit = [v * 8 / 1e6 for v in per_sec_rate(t, [float(r["sent_bytes"]) for r in rows])]
        drops = per_sec_rate(t, [float(r["dropped_pkts"]) for r in rows])
        backlog_kb = [float(r["backlog_bytes"]) / 1024 for r in rows]
    except (KeyError, ValueError) as e:
        print(f"unexpected CSV columns in {args.samples}: {e}", file=sys.stderr)
        return 1

    markers = load_csv(args.markers)

    fig, axes = plt.subplots(3, 1, figsize=(14, 9), sharex=True)
    fig.suptitle(args.title, fontsize=13, fontweight="bold")
    for ax, ys, ylabel, title, color in (
        (axes[0], tx_mbit, "Mbit/s", "AP uplink throughput (the shared budget)", "tab:blue"),
        (axes[1], drops, "Dropped pkts/s", "Shared-queue drops (contention across the fleet)", "tab:red"),
        (axes[2], backlog_kb, "Backlog KB", "Queue backlog", "tab:orange"),
    ):
        ax.plot(t, ys, color=color, linewidth=1.3)
        ax.set_ylabel(ylabel); ax.set_title(title); ax.grid(True, alpha=0.3)
        for m in markers:
            try:
                ax.axvline(float(m["elapsed"]), color="gray", linestyle="--", linewidth=0.8)
            except (ValueError, KeyError):
                continue
    axes[2].set_xlabel("Seconds since sample start")
    if markers:
        top = axes[0].get_ylim()[1]
        for m in markers:
            try:
                axes[0].text(float(m["elapsed"]), top * 0.96, m.get("label", ""),
                             rotation=90, va="top", ha="right", fontsize=8, color="dimgray")
            except (ValueError, KeyError):
                continue
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out = Path(args.out) if args.out else Path(args.samples).with_suffix(".png")
    fig.savefig(out, dpi=120)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
