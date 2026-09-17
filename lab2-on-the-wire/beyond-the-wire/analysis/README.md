
# Beyond-the-wire analysis

These scripts regenerate the charts from the committed reference captures.
Run them from `lab2-on-the-wire/beyond-the-wire/`. They write derived figures
to `output/`; the capture inputs remain under `reference-captures/`.

## Set up the environment

Create the local virtual environment once, then install the plotting libraries:

```bash
uv venv
source .venv/bin/activate
uv pip install matplotlib numpy pandas
```

```bash
source .venv/bin/activate
# uv pip install -e .
```

## Reference-capture layout

Use one common stem per run, for example `fast_bridge`:

```text
reference-captures/
	rmw_subscriber/<stem>_arrivals.csv
	rmw_subscriber/<stem>_markers.csv
	tshark/<stem>_arrivals.csv
	netdata/<stem>_orchestrator_net.json
	netdata/<stem>_reasm.csv
```

The arrival CSVs have the columns `t_epoch,robot,topic`. Marker CSVs have
`epoch,label`. Netdata JSON is the `netdata` export containing `labels` and
`data`; the repair CSV has `t_epoch,reqds,oks,fails,retrans`.

The `rmw_subscriber` arrivals are application delivery (layer 1). The
`tshark` arrivals are offline wire recovery (layer 3), using the same arrival
schema so they can use the same plotter. `plot_2netdata.py` combines the
netdata export with application arrivals and the repair counter for layer 2.

## Generate the reference charts

The following commands generate delivered, wire-recovered, and netdata charts
for all three reference runs:

```bash
./reference-analysis.sh
```

The resulting nine charts are in `output/`.

## Script parameters

### `plot_1delivered.py`

```text
plot_1delivered.py <arrivals.csv> <markers.csv> <output.png> [title]
```

`arrivals.csv` is either the subscriber or tshark arrival export. `markers.csv`
defines the shaded netem bands. The optional title defaults to `RMW benchmark`.

### `plot_2netdata.py`

```text
plot_2netdata.py <capture-dir> <timestamp> <markers.csv> <output.png> \
	[title] [repair.csv] [arrivals.csv] [rmw]
```

`capture-dir` contains files named `<timestamp>_<container>_net.json` for the
reference captures. The script also accepts the older
`<timestamp>.netdata_<container>_net_ethN.json` naming convention. `timestamp`
is the shared capture stem, not a filesystem path. `repair.csv` and `arrivals.csv` are
optional; omitting them removes the repair and delivered-frame panels.
`rmw` selects the repair counter: values beginning with `zen` use
`retrans`, while other values use `fails`. The optional title defaults to
`layer 2 · netdata`.

### `plot_3tshark.py`

```text
plot_3tshark.py <timestamp-or-pcap>
```

With a timestamp, the script reads `fleet_<timestamp>.pcap` and
`<timestamp>.markers.csv` from `CAPTURES_DIR` (default `/captures`). With a
`.pcap` path, it reads that file directly and derives the timestamp from its
name. It requires `tshark`, pandas, numpy, and matplotlib, and writes its
timeline beside the capture as `<timestamp>_timeline.png`.

The committed reference set contains the tshark arrival exports rather than
the original PCAP files, so the reproducible layer-3 command above uses
`plot_1delivered.py`. Use `plot_3tshark.py` when a raw fleet PCAP is available.

# TODO
matplotlib numpy pandas
