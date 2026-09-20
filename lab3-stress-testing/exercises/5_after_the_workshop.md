# 5. After the workshop

> **Topology note:** this exercise uses the generated direct-peer topology. The observer
> connects directly to each robot's Zenoh router; `wifi-ap` is only an IP-forwarding path.
> Exercise 4 intentionally uses the `routed_zenoh_ap_hub` fixture instead, where the
> observer and robot routers connect to a Zenoh hub on `wifi-ap`.

Everything above ran during the session. These activities do not need
anyone else in the room - pick whichever sounds interesting and run it at home on the
same stack.

## Push the scale further

Start with a clean, shaped baseline, then recreate the fleet at progressively larger
sizes (for example 10, 16, 20, and 25 - 25 is the harness maximum):

```bash
cd "$(git rev-parse --show-toplevel)"
scripts/workshop -t routed down
scripts/workshop -t routed up 25 cyclone
scripts/workshop -t routed netem good
```

At each size, watch the map and Netdata over the same 30-second interval. In **Apps
CPU**, compare `lab3_robots` and `lab3_console` with the host's CPU utilization. CPU is
the limiting resource when those groups rise with fleet size, host CPU is near saturation,
and the map stutters even though **Lab 3 AP** remains below its configured capacity with no
sustained queue backlog or drops. Conversely, a throughput ceiling accompanied by growing
AP backlog or drops identifies the shared medium as the limit. Record the first size where
the map becomes unusable and which signal led it. Your result depends on the host hardware,
the active RMW, and other local workload; do not assume CPU fails before the AP.

## Change the incident conditions

Repeat the live routed investigation with Zenoh and a different AP profile. Predict
whether the symptom will be a gradual freshness change or a broad TCP retransmission
stall, then test that prediction with Lichtblick, Netdata, and the `observer` container
topic check:

```bash
scripts/workshop -t routed down
scripts/workshop -t routed up 15 zenoh
scripts/workshop -t routed netem degraded
```

Note that `up 15 zenoh` (no `--rmw-directory`) is the **default** routed Zenoh config, not
Exercise 4's hub fixture: here the robot routers do not use the AP hub; the `observer`
dials each robot router directly. The AP's Zenoh listener, if started by the generic
entrypoint, is unused. Discovery gossip is enabled for this default layout.
Compare the two layouts in the [Zenoh routed-topology diagram](../diagrams/zenoh-routed-topologies.mmd)
before interpreting packet captures.

Use `netem bad` only after recording the `degraded` behaviour. `zenoh-lowlat` is Lab 4's
second Zenoh candidate: the same `rmw_zenoh_cpp`, configured as a client of a dedicated
router with Zenoh's low-latency transport (no batching or QoS multiplexing). A repeatable
comparison between it and plain Zenoh belongs in Lab 4, where the same recorded workload
can be used for every candidate.

## Write your own AP profile

Lab 3's shared-medium profiles are defined by [`lab3-stress-testing/scripts/ap_shape.sh`](../scripts/ap_shape.sh),
not by Lab 4's benchmark YAML. Add a named profile there (for example, bursty loss or
asymmetric delay) and apply it with `scripts/workshop -t routed netem <profile>` to the routed fleet.
Does your prediction from Lab 1 hold?

## Bring your own data to Lab 4

Use a representative MCAP in [Lab 4](../../lab4-benchmarking-and-decision/README.md) to
compare candidates under the same clean and stressed scenarios. If your topic names do
not match the `sensor`/`control`/`state` regexes in Lab 4's `benchmark.yaml`, update those patterns
before relying on the benchmark's measurements.

## Monitor your own deployment with Netdata

Install the Netdata Agent on each robot, or on the host that runs it, then establish a
normal baseline before introducing an RMW or network change. Start with each robot's
real network interface, CPU, memory, disk, and process charts; add container charts if
your ROS deployment runs in containers. Run the same state-topic and packet checks from
Exercises 2 and 3 around a controlled change, so an operator symptom can be compared
with independent host and network signals.

The workshop's Netdata container intentionally omits detailed per-container accounting
to keep its host access narrow. For your deployment, a host-installed Agent is the
simplest way to collect container CPU, memory, network, disk I/O, cgroup-limit, and
throttling metrics. A containerized Agent can collect the same data when it has
read-only access to the host's `/proc`, `/sys`, and `/sys/fs/cgroup` trees, plus host PID
visibility. That extra access is a deliberate security and portability tradeoff; it is
not a Netdata or Docker limitation.

For a multi-robot deployment, also install the Agent on the fleet-manager or monitoring
host. Stream every Agent to one Netdata parent or Netdata Cloud space, then compare the
fleet manager's API, database, message-broker, and network charts with the affected
robots' charts on the same time range. This distinguishes a shared network incident from
a fleet-manager resource bottleneck or a problem isolated to one robot. See Netdata's
[installation guide](https://learn.netdata.cloud/docs/netdata-agent/installation/) and
[multi-node monitoring guide](https://learn.netdata.cloud/docs/observability-centralization-points/).

## Read the real thing

- [`tc-netem(8)`](https://man7.org/linux/man-pages/man8/tc-netem.8.html) - every knob
  `ap_shape.sh`'s profiles use, plus ones they don't (`reorder`, `corrupt`, `duplicate`).
- [`lab3-stress-testing/scripts/ap_shape.sh`](../scripts/ap_shape.sh)'s header comment
  explains the airtime-overhead modelling in more depth than the README does - worth a
  read if "why does a tiny DDS heartbeat cost real bandwidth on real Wi-Fi" wasn't fully
  answered live.
- Compare a `bad` run here against a real Wi-Fi capture from
  [Lab 2's exercises](../../lab2-on-the-wire/exercises/) - `tc`/`netem` is reproducible
  by design, which is exactly why it isn't identical to what you'd see over the air.
