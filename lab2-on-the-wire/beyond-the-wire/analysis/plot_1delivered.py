#!/usr/bin/env python3
"""
Usage:
    plot_1delivered.py <arrivals.csv> <markers.csv> <output.png> [title]

Render a layer-1 application-delivery timeline. The arrivals CSV must contain
``t_epoch,robot,topic``. The markers CSV must contain ``epoch,label`` and
defines the shaded netem bands. The arrivals CSV may be the subscriber export
or the tshark export, because both use the same schema.

The optional title is one command-line argument. Quote it when it contains
spaces. The output is a two-panel PNG showing rolling message rate and
interarrival jitter for camera and scan messages.

Explanation of the charts
=========================
   1. rolling message rate   - received messages per second, computed over a sliding window.
                            - both payloads (camera and scan)
   2. interarrival jitter   - standard deviation of interarrival times (ms) over a rolling window.
"""

import matplotlib
import statistics
import sys

from matplotlib.lines import Line2D

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROBOT_COLORS = {1: "#E67E22", 2: "#2980B9", 3: "#27AE60"}
TOPIC_STYLE = {"camera": "-", "scan": "--"}
# background tint per band, clean -> worst, low alpha so the traces stay readable
BAND_TINTS = ["#2ECC71", "#F1C40F", "#E67E22", "#E74C3C", "#8E44AD", "#7F8C8D"]

RATE_WIN = 2.0   # s, sliding window for msgs/s
RATE_HOP = 0.5   # s, step between rate samples
JIT_N    = 15    # interarrivals per jitter sample
JIT_YMAX = 300   # ms, floor for the jitter y-axis; clips the end-of-run collapse spike
                 # so the normal-band detail stays legible (grows to p95 if a run is noisier)


def _pctl(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(p / 100.0 * len(s)))]


def load_arrivals(p):
    out = []
    for ln in open(p).read().splitlines()[1:]:
        if not ln.strip():
            continue
        parts = ln.split(",")
        t, r = float(parts[0]), int(parts[1])
        topic = parts[2] if len(parts) > 2 else "camera"   # tolerate old 2-col CSVs
        out.append((t, r, topic))
    return out


def load_markers(p):
    out = []
    for ln in open(p).read().splitlines()[1:]:
        if ln.strip():
            e, lab = ln.split(",", 1)
            out.append((float(e), lab))
    return sorted(out)


def rolling_rate(ts, t0, t1, win, hop):
    ts = sorted(ts)
    xs, ys = [], []
    t = t0
    while t <= t1:
        lo, hi = t - win / 2, t + win / 2
        n = sum(1 for x in ts if lo <= x < hi)
        xs.append(t - t0)
        ys.append(n / win)
        t += hop
    return xs, ys


def rolling_jitter(ts, t0, n):
    ts = sorted(ts)
    gaps = [(ts[k + 1] - ts[k], ts[k + 1]) for k in range(len(ts) - 1)]
    xs, ys = [], []
    for k in range(n, len(gaps) + 1):
        wnd = [g for g, _ in gaps[k - n:k]]
        xs.append(gaps[k - 1][1] - t0)
        ys.append(statistics.pstdev(wnd) * 1000)
    return xs, ys


def main():
    arrivals, markers_p, out = sys.argv[1], sys.argv[2], sys.argv[3]
    title = sys.argv[4] if len(sys.argv) > 4 else "RMW benchmark"

    arr = load_arrivals(arrivals)
    mk = load_markers(markers_p)
    t0 = mk[0][0]
    last_arr = max(t for t, _, _ in arr)
    t_end = min(mk[-1][0], last_arr)   # clip the dead tail: stop at the last real msg
    span = t_end - t0
    robots = sorted({r for _, r, _ in arr})
    topics = [tp for tp in ("camera", "scan") if any(t == tp for _, _, t in arr)]

    fig, (ax_fps, ax_jit) = plt.subplots(2, 1, sharex=True, figsize=(10, 6))

    for i in range(len(mk)):
        e, lab = mk[i]
        x = e - t0
        if x >= span:            # band starts after the last msg, so skip the dead tail
            continue
        nx = min((mk[i + 1][0] - t0) if i + 1 < len(mk) else span, span)
        if lab != "end":
            tint = BAND_TINTS[i % len(BAND_TINTS)]
            for ax in (ax_fps, ax_jit):
                ax.axvspan(x, nx, color=tint, alpha=0.10, lw=0)
            ax_fps.text((x + nx) / 2, 0.97, lab,
                        transform=ax_fps.get_xaxis_transform(),
                        ha="center", va="top", fontsize=8, color="#555")
        for ax in (ax_fps, ax_jit):
            ax.axvline(x, color="#888", ls="--", lw=0.8)

    all_jit = []
    for r in robots:
        c = ROBOT_COLORS.get(r, "#7F8C8D")
        for tp in topics:
            ls = TOPIC_STYLE[tp]
            ts = [t for t, rr, tt in arr if rr == r and tt == tp]
            if not ts:
                continue
            xf, yf = rolling_rate(ts, t0, t_end, RATE_WIN, RATE_HOP)
            ax_fps.plot(xf, yf, ls, color=c, lw=1.6, alpha=0.9)
            xj, yj = rolling_jitter(ts, t0, JIT_N)
            all_jit += yj
            ax_jit.plot(xj, yj, ls, color=c, lw=1.1, alpha=0.9)

    ax_fps.set_ylabel("received msgs/s")
    ax_fps.set_ylim(bottom=0)
    ax_fps.grid(True, alpha=0.25)

    ax_jit.set_ylabel("interarrival\njitter (ms)")
    ax_jit.set_ylim(0, max(JIT_YMAX, _pctl(all_jit, 95)))
    ax_jit.grid(True, alpha=0.25)
    ax_jit.set_xlabel("time (s)   |   shaded bands = netem profile (worsening left to right)")
    ax_jit.set_xlim(0, span)

    # Two legends in the top margin, clear of the in-axes band labels: robot = color,
    # topic = linestyle.
    robot_handles = [Line2D([0], [0], color=ROBOT_COLORS.get(r, "#7F8C8D"), lw=1.8,
                            label=f"robot {r}") for r in robots]
    topic_handles = [Line2D([0], [0], color="#333", lw=1.8, ls=TOPIC_STYLE[tp],
                            label=tp) for tp in topics]
    fig.suptitle(title, y=0.99, fontsize=12)
    leg1 = fig.legend(handles=robot_handles, loc="upper center", ncol=len(robots),
                      frameon=False, fontsize=9, bbox_to_anchor=(0.38, 0.95))
    fig.add_artist(leg1)
    fig.legend(handles=topic_handles, loc="upper center", ncol=len(topics),
               frameon=False, fontsize=9, bbox_to_anchor=(0.72, 0.95))

    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(out, dpi=130)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
