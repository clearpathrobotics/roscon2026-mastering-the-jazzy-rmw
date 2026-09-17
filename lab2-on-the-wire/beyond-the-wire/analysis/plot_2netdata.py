#!/usr/bin/env python3
"""
Usage:
    plot_2netdata.py <capture-dir> <timestamp> <markers.csv> <output.png> \
        [title] [repair.csv] [arrivals.csv] [rmw]

Render a layer-2 netdata timeline. ``capture-dir`` contains the netdata JSON
export for the orchestrator. Reference captures use
``<timestamp>_<container>_net.json``; legacy per-interface exports named
``<timestamp>.netdata_<container>_net_ethN.json`` are also accepted.

The marker CSV contains ``epoch,label``. ``repair.csv`` and ``arrivals.csv``
are optional and add the repair and delivered-frame panels when present. The
repair CSV contains ``t_epoch,reqds,oks,fails,retrans``. ``rmw`` selects the
repair column: a value beginning with ``zen`` uses TCP retransmits; every
other value uses IP reassembly failures. Quote ``title`` when it contains
spaces. The output is a PNG with throughput, delivered-versus-offered camera
frames, and the transport repair counter.

Explanation of the charts
=========================
   1. throughput   - orchestrator net RX (kilobits/s). The system view, and the point is that it
                     stays high under load while frames die: bytes keep crossing because only a few
                     percent are lost, so this panel is blind to the frame collapse.
   2. frames       - attempted vs delivered camera frames/s. Delivered is the layer-1 arrival count
                     as an aggregate; attempted is the offered load (the clean-band rate). The shaded
                     gap is frames lost, and it is computed the same way for every RMW.
   3. repair       - where the transport is working: IP reassembly fails/s for the UDP RMWs (Fast,
                     Cyclone), TCP retransmits/s for Zenoh. Same slot, RMW-appropriate counter. The
                     tell is the contrast across RMWs: reassembly fails spike for Fast, stay near zero
                     for Cyclone (its frames die at the RTPS layer), and Zenoh shows retransmits
                     instead because TCP recovers the bytes rather than dropping the frame.
"""

import csv
import json
import matplotlib
import sys

from matplotlib.lines import Line2D
from pathlib import Path

matplotlib.use("Agg")
import matplotlib.pyplot as plt

CONTAINER_COLORS = {"mock-robot-1": "#E67E22", "mock-robot-2": "#2980B9",
                    "mock-robot-3": "#27AE60", "orchestrator": "#333333"}
BAND_TINTS = ["#2ECC71", "#F1C40F", "#E67E22", "#E74C3C", "#8E44AD", "#7F8C8D"]


def load_markers(p):
    out = []
    for ln in open(p).read().splitlines()[1:]:
        if ln.strip():
            e, lab = ln.split(",", 1)
            out.append((float(e), lab))
    return sorted(out)


def netdata_series(json_path):
    """(abs_times, [per-dim series], dim_labels). Absolute epoch so markers align. From plot_run.py."""
    p = Path(json_path)
    if not p.is_file():
        return [], [], []
    try:
        d = json.loads(p.read_text())
    except Exception:
        return [], [], []
    labels, data = d.get("labels", []), d.get("data", [])
    if not labels or not data:
        return [], [], []
    data = list(reversed(data))                    # netdata is newest-first
    ts = [row[0] for row in data]
    ys = [[float(row[i] or 0) for row in data] for i in range(1, len(labels))]
    return ts, ys, labels[1:]


def busiest_net_series(cap_dir, ts, container):
    """netdata_series for whichever ethN carried the most traffic. The DDS bus iface is not eth0 on
    every RMW, so snapshot.sh dumps every ethN and we pick the busy one here."""
    best = ([], [], [])
    best_total = -1.0
    capture_dir = Path(cap_dir)
    # Reference captures use <timestamp>_<container>_net.json. Keep accepting
    # the older per-interface <timestamp>.netdata_<container>_net_ethN.json
    # export as well, since live captures may still use that naming convention.
    paths = list(capture_dir.glob(f"{ts}_{container}_net*.json"))
    paths += list(capture_dir.glob(f"{ts}.netdata_{container}_net_eth*.json"))
    for p in sorted(set(paths)):
        xs, ys, dims = netdata_series(p)
        if not xs:
            continue
        total = sum(abs(v) for s in ys for v in s)
        if total > best_total:
            best_total, best = total, (xs, ys, dims)
    return best


def draw_bands(ax, mk, t0, span, label=False):
    for i in range(len(mk)):
        e, lab = mk[i]
        x = e - t0
        if x >= span:
            continue
        nx = min((mk[i + 1][0] - t0) if i + 1 < len(mk) else span, span)
        if lab != "end":
            ax.axvspan(x, nx, color=BAND_TINTS[i % len(BAND_TINTS)], alpha=0.10, lw=0)
            if label:
                ax.text((x + nx) / 2, 0.97, lab, transform=ax.get_xaxis_transform(),
                        ha="center", va="top", fontsize=8, color="#555")
        ax.axvline(x, color="#888", ls="--", lw=0.8)


def frame_rate(arrivals_p, t0, span):
    """Per-second delivered camera frames/s across the sweep (aggregate over robots)."""
    n = int(span) + 1
    counts = [0] * n
    for row in csv.reader(open(arrivals_p)):
        if not row or row[0] == "t_epoch" or len(row) < 3 or row[2] != "camera":
            continue
        k = int(float(row[0]) - t0)
        if 0 <= k < n:
            counts[k] += 1
    return list(range(n)), counts


def main():
    cap_dir, ts, markers_p, out = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    title = sys.argv[5] if len(sys.argv) > 5 else "layer 2 · netdata"
    reasm_p = sys.argv[6] if len(sys.argv) > 6 else None
    arrivals_p = sys.argv[7] if len(sys.argv) > 7 else None
    rmw = (sys.argv[8] if len(sys.argv) > 8 else "rtps").lower()

    mk = load_markers(markers_p)
    t0 = mk[0][0]
    span = mk[-1][0] - t0
    clean_end = mk[1][0] - t0 if len(mk) > 1 else span

    have_frames = bool(arrivals_p and Path(arrivals_p).is_file())
    have_reasm = bool(reasm_p and Path(reasm_p).is_file())
    kinds, ratios = ["net"], [2.6]
    if have_frames:
        kinds.append("frames"); ratios.append(2.6)
    if have_reasm:
        kinds.append("repair"); ratios.append(1.4)

    fig, axs = plt.subplots(len(kinds), 1, sharex=True, figsize=(10, 1.4 + sum(ratios)),
                            gridspec_kw={"height_ratios": ratios})
    axs = list(axs) if len(kinds) > 1 else [axs]
    ax = dict(zip(kinds, axs))

    # 1. throughput
    containers = []
    xs, ys, dims = busiest_net_series(cap_dir, ts, "orchestrator")
    if xs:
        rx_idx = dims.index("received") if "received" in dims else 0
        ax["net"].plot([x - t0 for x in xs], [abs(v) for v in ys[rx_idx]],
                       color=CONTAINER_COLORS["orchestrator"], lw=1.8)
        containers.append("orchestrator RX")
    draw_bands(ax["net"], mk, t0, span, label=True)
    ax["net"].set_ylabel("net RX (kilobits/s)")
    ax["net"].set_ylim(bottom=0)
    ax["net"].grid(True, alpha=0.25)

    # 2. attempted vs delivered frames/s (cross-RMW: delivered from layer-1 arrivals, attempted =
    # offered load measured as the clean-band mean). The shaded gap is what the link cost us.
    if have_frames:
        xf, deliv = frame_rate(arrivals_p, t0, span)
        clean = [deliv[k] for k in range(len(xf)) if xf[k] < clean_end] or [0]
        offered = sum(clean) / len(clean)
        att = [offered] * len(xf)
        a = ax["frames"]
        draw_bands(a, mk, t0, span)
        a.fill_between(xf, deliv, att, where=[d < offered for d in deliv],
                       color="#C0392B", alpha=0.12, lw=0, label="lost")
        a.plot(xf, att, color="#7F8C8D", lw=1.1, ls="--", label=f"offered ~{offered:.0f} f/s")
        a.plot(xf, deliv, color="#1E8449", lw=1.4, label="delivered f/s")
        a.set_ylabel("camera frames/s\n(all robots)")
        a.set_ylim(bottom=0)
        a.grid(True, alpha=0.25)
        a.legend(loc="upper right", fontsize=8, frameon=False)

    # 3. repair events/s: where the transport is straining. UDP RMWs -> IP reassembly fails/s;
    # Zenoh (TCP) -> retransmits/s. Same panel slot, counter chosen by RMW.
    if have_reasm and reasm_p:
        rows = [r for r in csv.reader(open(reasm_p))][1:]
        te = [float(r[0]) for r in rows]
        is_tcp = rmw.startswith("zen")
        col = 4 if is_tcp else 3
        label = "TCP retransmits/s" if is_tcp else "IP reassembly fails/s"
        color = "#8E44AD" if is_tcp else "#C0392B"
        a = ax["repair"]
        draw_bands(a, mk, t0, span)
        if rows and len(rows[0]) > col:
            cval = [float(r[col]) for r in rows]
            xr, rate = [], []
            for k in range(1, len(te)):
                dt = te[k] - te[k - 1]
                if dt > 0:
                    xr.append(te[k] - t0)
                    rate.append(max((cval[k] - cval[k - 1]) / dt, 0.0))
            a.fill_between(xr, 0, rate, color=color, alpha=0.15, lw=0)
            a.plot(xr, rate, color=color, lw=1.2, label=label)
            a.legend(loc="upper left", fontsize=8, frameon=False)
        else:
            a.text(0.5, 0.5, f"{label}: not sampled", transform=a.transAxes,
                   ha="center", va="center", fontsize=9, color="#999")
        a.set_ylabel(label.split("/s")[0].replace(" ", "\n"))
        a.set_ylim(bottom=0)
        a.grid(True, alpha=0.25)

    axs[-1].set_xlabel("time (s)   |   shaded bands = netem profile (worsening left to right)")
    axs[-1].set_xlim(0, span)

    handles = [Line2D([0], [0], color=CONTAINER_COLORS.get(c, "#7F8C8D"), lw=1.8, label=c)
               for c in containers]
    fig.suptitle(title, y=0.99, fontsize=12)
    fig.legend(handles=handles, loc="upper center", ncol=max(len(handles), 1), frameon=False,
               fontsize=9, bbox_to_anchor=(0.5, 0.955))
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(out, dpi=130)
    print(f"wrote {out}  (frames={'yes' if have_frames else 'no'}, "
          f"repair={'tcp' if rmw.startswith('zen') else 'udp'})")


if __name__ == "__main__":
    main()
