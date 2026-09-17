#!/bin/bash

mkdir -p output
for stem in fast_bridge cyclone_bridge zenoh_perhost_bridge; do
	python analysis/plot_1delivered.py \
		"reference-captures/rmw_subscriber/${stem}_arrivals.csv" \
		"reference-captures/rmw_subscriber/${stem}_markers.csv" \
		"output/${stem}_delivered.png" \
		"${stem} - delivered messages"

	python analysis/plot_1delivered.py \
		"reference-captures/tshark/${stem}_arrivals.csv" \
		"reference-captures/rmw_subscriber/${stem}_markers.csv" \
		"output/${stem}_wire-recovered.png" \
		"${stem} - wire-recovered messages"

	python analysis/plot_2netdata.py \
		reference-captures/netdata "$stem" \
		"reference-captures/rmw_subscriber/${stem}_markers.csv" \
		"output/${stem}_netdata.png" \
		"${stem} - netdata" \
		"reference-captures/netdata/${stem}_reasm.csv" \
		"reference-captures/rmw_subscriber/${stem}_arrivals.csv" \
		"$stem"
done

python analysis/plot_4camera_comparison.py \
	reference-captures/rmw_subscriber/fast_bridge_arrivals.csv \
	reference-captures/rmw_subscriber/cyclone_bridge_arrivals.csv \
	reference-captures/rmw_subscriber/zenoh_perhost_bridge_arrivals.csv \
	reference-captures/rmw_subscriber/fast_bridge_markers.csv \
	reference-captures/rmw_subscriber/cyclone_bridge_markers.csv \
	reference-captures/rmw_subscriber/zenoh_perhost_bridge_markers.csv \
	output/camera_comparison.png

python analysis/plot_5delivered_comparison.py \
	reference-captures/rmw_subscriber/fast_bridge_arrivals.csv \
	reference-captures/rmw_subscriber/cyclone_bridge_arrivals.csv \
	reference-captures/rmw_subscriber/zenoh_perhost_bridge_arrivals.csv \
	reference-captures/rmw_subscriber/fast_bridge_markers.csv \
	reference-captures/rmw_subscriber/cyclone_bridge_markers.csv \
	reference-captures/rmw_subscriber/zenoh_perhost_bridge_markers.csv \
	output/delivered_camera_comparison.png \
	output/delivered_scan_comparison.png
