
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
