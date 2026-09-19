# 1. Take the Fleet's Pulse

Lab 1 showed you a **default** config (multicast, no pinning) and a **pinned**
hub-and-spoke config, one robot at a time. This exercise puts more robots on the
default config and introduces the healthy Netdata signals available before an
incident is introduced in [Exercise 2](2_watch_a_healthy_link_fail.md).

Lab 3 starts from a known middleware: **Cyclone DDS**, which Exercises 2 and 3 also use.
The active RMW persists in `.env.local` between sessions, so setting it explicitly here
keeps your results comparable with the numbers quoted in these exercises. Start the core
stack using the [Lab 3 setup](../README.md#before-you-begin).

> **What you will visualize:** this exercise uses **Netdata** to compare discovery
> traffic and container resource use at scale. Packet loss and
> TCP retransmission become useful evidence only in the impaired routed topology in
> later exercises. The live robot operator map appears in [Exercise 2](2_watch_a_healthy_link_fail.md),
> after the fleet moves to the routed topology.

## Steps

1. Select Cyclone DDS. Start Netdata **before** the fleet so its StatsD listener is up
   when the nodes join, then bring up Lab 1's fleet unchanged plus 6 replicas on the
   default config:

   ```bash
   cd "$(git rev-parse --show-toplevel)"
   scripts/workshop netdata up
   lab3-stress-testing/scripts/ex1_up.sh 6
   ```

   The fleet collector is normally its own step (`scripts/workshop -t flat collector up`).
   `ex1_up.sh` runs it for you right after the fleet starts, and briefly holds the robots'
   ROS startup so the collector is already recording when the fleet emits its discovery
   burst - start them by hand in the wrong order and the burst is gone before anything is
   watching it.

2. Open <http://localhost:19999>. On Netdata's welcome screen, click **Skip and use
   anonymously** below the sign-in button. Do not enter an account or sign in. Once the
   dashboard opens, use **Search charts** to search for **Lab 3 Fleet**. Netdata groups
   these under **lab3 > Config comparison**. You should see three charts:
   RTPS Discovery Multicast TX, Default-Group Discovery Multicast TX, and Default-Config Replicas.

3. Watch **RTPS Discovery Multicast TX** and **Default-Group Discovery Multicast TX**
   before scaling. These are discovery-control-plane signals, not a throughput meter:
   participants emit a burst when they join and then settle to a lower periodic rate.
   That join burst happened during bring-up - the collector records through the startup
   hold - and Netdata keeps it in the chart history, so scroll the Default-Group chart
   back a little if it has already settled by the time you open the dashboard.
   The named hub-and-spoke nodes should remain at or near zero. Zenoh uses a different
   discovery mechanism, so it need not emit RTPS multicast traffic.

4. Scale the default group up:

   ```bash
   lab3-stress-testing/scripts/ex1_up.sh 16
   ```

   Keep the multicast-total chart visible while the extra robots join. It sums outbound
   multicast measured from every default-config replica, so the join activity appears
   as a short-lived burst. Do not expect its steady-state rate to increase in direct
   proportion to $N$: DDS reduces discovery traffic after participants have matched.
   **Default-Config Replicas** confirms the fleet reached 16.

5. After the discovery burst settles, compare per-container network I/O:

   ```bash
   docker stats --no-stream --format 'table {{.Name}}\t{{.NetIO}}'
   ```

   Find the `mock-robot-*` and `observer` rows. **NET I/O** shows cumulative received
   and sent bytes, not a bandwidth rate. Run the command again to see which containers
   are exchanging traffic. Counts include discovery and user data; multicast can
   deliver one sent packet to several receivers, so do not add RX and TX together
   as a measure of shared-link load.

   Netdata may also show Docker's `br-...` interface under **Network Interfaces**,
   after a virtual-interface discovery delay of about 40 seconds. That bridge's
   counters do not aggregate traffic forwarded between containers. A missing or
   quiet bridge chart does not mean the fleet is idle. Use the AP qdisc charts in
   Exercise 2 to study shared-link load and queueing.

6. Search Netdata for **Apps CPU**. The `lab3_robots` group shows the simulated
   fleet's CPU use. The observer is idle in this exercise, so do not expect an active
   `lab3_console` group until its Foxglove bridge starts in Exercise 2. There is no
   AP in the flat topology, so `lab3_ap` is absent too. Charts retained from earlier
   runs may still show these names without current samples.

<details>
<summary>Answer: what healthy-fleet telemetry establishes</summary>

The default config multicasts discovery, so adding robots produces a join-time discovery
burst on the shared bridge. The probe records only outbound RTPS multicast, avoiding
Docker's bridge-flooded received traffic. Once participants have matched, discovery
traffic can settle and does not have to scale linearly with fleet size. Docker's
per-container network counters show traffic at each endpoint, not a shared-link total.

These measurements establish a baseline of discovery activity at joins and per-container
resource use. Use ROS graph/topic evidence to establish what
each participant actually discovered. Exercises 2 and 3 then use the AP's qdisc drops
and backlog to diagnose an introduced transport fault.
</details>

## Compare another RMW

```bash
scripts/workshop -t flat down
WORKSHOP_RMW=zenoh lab3-stress-testing/scripts/ex1_up.sh 16
```

Zenoh's default config here is a router-less peer mesh, not RTPS multicast discovery.
The RTPS Discovery Multicast TX charts should therefore remain near zero; compare its
per-container network I/O and resource charts instead.

This leaves the Zenoh fleet running. Exercise 2 selects Cyclone as part of its routed
bring-up.
[Exercise 2](2_watch_a_healthy_link_fail.md) selects Cyclone again as its first step, so
you can move on either way - but if you stop here, set it back before returning:

```bash
scripts/workshop -t flat down
scripts/workshop -t flat up 3 cyclone
```

## When it does not work

**No "Lab 3 Fleet" charts appear.** netdata's StatsD collector only creates a chart
once it's received a value. Give `ex1_up.sh` a few seconds for bringup on first
start, then refresh.

**Multicast TX line for the default group doesn't move at all.** Confirm containers are
actually running: `docker compose -f docker/compose/flat.yml ps`. If fewer than the
requested `mock-robot-*` containers are listed, `ex1_up.sh` didn't start them all — check
`docker compose ... logs` for a startup failure.

Leave the fleet running. [Exercise 2](2_watch_a_healthy_link_fail.md) tears it down for you
and brings up the routed shared-AP topology instead.
