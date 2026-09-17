# 4. Repeat the incident over TCP, using Zenoh

You diagnosed the Cyclone DDS fleet in [Exercise 3](3_the_shared_medium.md). Now repeat
the same live incident with Zenoh. The purpose is to explain a transport behaviour from
evidence, not to select a winner; the repeatable comparison and decision live in Lab 4.

**What this exercise is really about.** Exercise 3 ran over UDP, because that is what
Cyclone DDS and Fast DDS use. Zenoh's default transport is TCP, and configuring it is a
one-line change, which makes it the most convenient way to put a real ROS 2 fleet on a
reliable byte-stream transport and watch what a lossy shared medium does to it. The
subject of this exercise is **TCP under loss**, not Zenoh.

> **This is not a shortcoming of Zenoh.** Zenoh supports UDP, QUIC, TLS, serial and
> shared memory as well; TCP is simply what the default configuration enables, and this
> lab keeps that default. Nor is TCP why teams adopt Zenoh. The usual reasons are
> discovery and scale: multicast scouting is disabled by default and the router
> distributes discovery by gossip instead, which avoids the multicast discovery storms
> that grow with fleet size, and it crosses subnets and NAT without reconfiguration -
> exactly the routed topology you are running. It also ships security tooling and a
> shared-memory path for large intra-host payloads. Judge the transport here, and judge
> the middleware in Lab 4.

## Steps

1. Recreate the routed topology with Zenoh. The `observer` operator container must use
   the same RMW as the robots, and each robot runs its own Zenoh router, so this restarts the
   routed services. You do **not** need to restart the core stack here:
   `scripts/workshop -t routed down` removes only the Lab 3 routed services, while Netdata
   remains available. The new observer idles until its Foxglove bridge is started again.
   Apply `good` after the new AP exists because AP shaping is not retained across recreation:

   ```bash
   cd "$(git rev-parse --show-toplevel)"
   scripts/workshop -t routed down
   scripts/workshop -t routed up 3 zenoh
   scripts/workshop observer bridge
   scripts/workshop lichtblick up
   scripts/workshop -t routed netem good
   ```

   The routed command waits for the recreated AP and all of its interfaces. Zenoh router
   startup and ROS discovery can take longer. Confirm the router listeners in Step 2,
   then open:

   ```
   http://localhost:8080/?ds=foxglove-websocket&ds.url=ws://localhost:8765
   ```

   (Opening plain `http://localhost:8080` does not select the data source - use the
   full URL. If the layout does not show the operator map, see the [Lab 3
   README](../README.md#live-fleet-reference) for how to import it.)

   <details>
   <summary>Why the RMW cannot be hot-swapped</summary>

   `RMW_IMPLEMENTATION` and every QoS setting bind when a node's participant is created;
   ROS 2 has no API to renegotiate them on a running node. Zenoh also needs `wifi-ap` to
   start its routers, and the `observer` container must use Zenoh to receive the robots'
   topics. That is why Step 1 recreates the routed topology instead of flipping an
   environment variable under running nodes. The network shaping (`ap bad`/`good`) is the
   only thing that changes live, which is why it is the knob built for a live demo.
   </details>

2. Inspect the deployment before introducing a fault. Zenoh uses **one `rmw_zenohd`
   per host**. Every robot runs its own router, and local ROS nodes connect to it over
   loopback. The `observer` does not run a router: it connects across the AP to each
   robot's router as a Zenoh peer. In the normal no-uplink design, robot routers have
   no `connect` target; the observer dials them.
   This workshop configuration uses TCP, so each observer-to-robot connection carries
   that robot's remote traffic over the shared AP:

   ```bash
    docker exec mock-robot-1 sh -c '
       echo "=== $ZENOH_SESSION_CONFIG_URI ==="
       cat "$ZENOH_SESSION_CONFIG_URI"
       echo "=== $ZENOH_ROUTER_CONFIG_URI ==="
       cat "$ZENOH_ROUTER_CONFIG_URI"
    '
   docker exec mock-robot-1 sh -c 'ss -ltn | grep 7447'
   docker exec wifi-ap sh -c 'ss -ltn | grep 7447'
   ```

   `$ZENOH_SESSION_CONFIG_URI` (e.g. `/rmw_configuration/routed/zenoh/mock-robot-1.json5`) is the
   ROS client's configuration: it connects to its local router at `tcp/localhost:7447`.
   `$ZENOH_ROUTER_CONFIG_URI` (e.g. `mock-robot-1-router.json5` in the same directory) is that
   router's configuration: it has no `connect` target in the normal deployment. Confirm that
   `mock-robot-1` and `wifi-ap` are listening; the `observer` is a peer and will not listen
   on 7447 (it dials the robots' routers instead). `LISTEN ... 0.0.0.0:7447` means the router accepts TCP
   connections on every IPv4 interface; `LISTEN ... *:7447` has the same practical
   meaning here. These lines prove that each router is ready to accept a connection, not
   that the routers have connected or that ROS data is flowing. Then watch the map for
   30 seconds with `good` and take a **Zenoh healthy baseline** with the inspector, the
   same way you did in
   [Exercise 2, step 4](2_watch_a_healthy_link_fail.md):

   ```bash
   docker exec -it observer bash -c 'source /opt/ros/jazzy/setup.bash && python3 /scripts/lab3/fleet_inspector.py --robots robot_1,robot_2,robot_3 --sensors scan'
   ```

   Expect about 10 Hz at ~3 ms age - slightly fresher than the DDS baseline, because
   nothing has to leave the container to reach a local subscriber. That is the number to
   compare against once the medium degrades.

3. Degrade the medium **without touching anything else**:

   ```bash
   scripts/workshop -t routed netem bad
   ```

   Watch the ribbon colours (green/amber/red = TF freshness) and the map. Some robots
   should begin to freeze or jump as telemetry becomes stale.

   <details>
   <summary>Why the topology is worth this much attention</summary>

   The deployed `peer` sessions connect to a local router over loopback. Robot routers
   have no uplink; the observer connects to them across `wifi-ap`, so remote robot/observer
   traffic crosses the AP while the
   robot's local `pilot` -> `cmd_vel` -> `twist_mux` -> controller path does not depend
   on it. Switch the sessions to `client` mode pointed at the remote router - the optional
   exercise below shows how - and that local control path is relayed through `wifi-ap`.
   Under `ap bad`, the controller can then miss its `cmd_vel_timeout: 0.5` deadline and
   stop the robot for a real control-path reason, rather than merely showing stale state.

   That distinction matters for Lab 4: benchmarking a client-of-a-remote-router setup
   would measure a deployment mistake rather than the middleware.
   </details>

4. Diagnose the stall. In Netdata, use **Apps CPU** and interface charts to rule out host
   process pressure. Use **Lab 3 AP** to establish that the shared queue is dropping
   packets or building a backlog. Then check
   `/fleet_map/state_freshness` from the `observer` container. First confirm that a new
   ROS CLI process joins the same routed Zenoh session as the running operator tools:

   ```bash
   docker exec observer bash -lc 'echo "$ZENOH_SESSION_CONFIG_URI"'
   docker exec observer bash -lc 'source /opt/ros/jazzy/setup.bash && ros2 topic list | grep -x /fleet_map/state_freshness'
   docker exec observer bash -lc 'source /opt/ros/jazzy/setup.bash && ros2 topic info -v /fleet_map/state_freshness'
   ```

   The first command must print the observer's own zenoh session config path (e.g.
   `/rmw_configuration/routed/zenoh/observer.json5`); the next two must find one
   `diagnostic_msgs/msg/DiagnosticArray` publisher named `fleet_map`. Read a report,
   then sample its rate for about 20 seconds; each in-container timeout stops its reader:

   ```bash
   docker exec observer bash -lc 'source /opt/ros/jazzy/setup.bash && timeout 20 ros2 topic echo /fleet_map/state_freshness'
   docker exec observer bash -lc 'source /opt/ros/jazzy/setup.bash && timeout 20 ros2 topic hz /fleet_map/state_freshness'
   ```

   Each `status` entry reports a robot's `state_freshness_ms` and its health. Compare
   those values and the received rate under `good` and `bad`. These signals show the
   conditions for a transport failure; they do not prove a TCP retransmission by
   themselves.

5. Confirm the TCP hypothesis on the wire, using the packet workflow from Lab 2. Run
   this once under `good` and again while `bad` is active. Capture on the `observer`,
   which is a TCP endpoint, so each segment is seen once; running this on the forwarding
   `wifi-ap` with `-i any` would see forwarded packets twice and count them as
   retransmissions. It filters to the Zenoh connection and prints only the retransmissions
   TShark detects:

   ```bash
   docker exec observer bash -lc '
     timeout 20 tshark -i eth0 -n \
       -f "net 172.40.0.0/16 and tcp port 7447" \
       -Y "tcp.analysis.retransmission" \
       -T fields -e frame.time_relative -e ip.src -e ip.dst -e tcp.seq -e tcp.len
   '
   ```

   This is a Lab 2 display filter with a Lab 3-specific output format. Each printed
   row has already matched `tcp.analysis.retransmission`; it is not every Zenoh TCP
   packet. The five columns are:

   | Column | Meaning |
   |---|---|
   | `frame.time_relative` | seconds since this capture started |
   | `ip.src`, `ip.dst` | a robot or observer (`172.40.<n>.10`) and its local AP address (`172.40.<n>.2`) |
   | `tcp.seq` | first byte sequence number of the retransmitted TCP segment |
   | `tcp.len` | TCP payload bytes in that segment; `1448` is a near-MTU-sized data segment, while small values can be control or small application messages |

   For example, `172.40.2.10  172.40.2.2  69505  1448` is a near-MTU segment being
   retransmitted from `mock-robot-2` toward its AP interface. Do not try to infer a ROS
   topic from the sequence number or compare sequence numbers between clients: each
   client has its own TCP byte stream. Compare the two 20-second captures instead.
   `good` still applies 0.1% bursty loss, so it can show a small retransmission
   baseline. A marked increase or clustering of retransmissions under `bad` is evidence
   of transport repair under the impaired medium. At the end of each run, TShark also
   prints its captured-packet total. That total counts every TCP/7447 packet admitted by
   the capture filter, not just the retransmission rows displayed above; record it as
   context when comparing the number of displayed retransmissions. Correlate both with
   AP drops/backlog and state freshness; a raw retransmission count alone does not
   measure user-visible impact.

   Retransmissions together with AP loss/backlog and increasing state age support this
   explanation: TCP holds later bytes behind a missing segment, so several ROS topic
   streams carried by that TCP session can appear to stall together.

6. Retry the fix that worked under DDS, and watch it fail. In Exercise 3, making the
   sensor class best effort cut scan age by roughly six times. Run the same comparison
   here, while `ap bad` is applied:

   ```bash
   docker exec -it observer bash -c 'source /opt/ros/jazzy/setup.bash && python3 /scripts/lab3/fleet_inspector.py --robots robot_1,robot_2,robot_3 --sensors scan --qos reliable'
   ```

   ```bash
   docker exec -it observer bash -c 'source /opt/ros/jazzy/setup.bash && python3 /scripts/lab3/fleet_inspector.py --robots robot_1,robot_2,robot_3 --sensors scan --qos best_effort'
   ```

   ```text
   reliable      10.0 Hz / age  385 ms      2.5 Hz / age 3561 ms      9.7 Hz / age 2100 ms
   best_effort    5.2 Hz / age 1655 ms      6.2 Hz / age 3359 ms      9.0 Hz / age 2377 ms
   ```

   Best effort does not rescue it, and the run-to-run spread is large. `rmw_zenoh`'s
   design doc says why:

   > `BEST_EFFORT` - Data may be dropped during delivery. If non-reliable endpoints are
   > configured (e.g. `udp`) they will be used. **Otherwise a reliable transport will be
   > used. Note that with the default configuration, only the TCP transport is
   > configured.**

   This deployment configures only TCP endpoints, so a best-effort ROS publisher is still
   carried by TCP. The QoS request is honoured at the ROS layer and then handed to a
   transport that repairs every loss regardless. You cannot opt out of retransmission
   from above it.

   That is the central lesson of this exercise. Under DDS the reliability contract is
   implemented per sample, per reader, so best effort genuinely stops the repair traffic.
   Under TCP it is implemented per byte stream, shared by everything multiplexed onto that
   connection, so one lost segment delays whatever is queued behind it and no application
   QoS setting can change that.

   Note what *does not* apply here. Zenoh sets `CongestionControl::BLOCK` - where a
   publisher is blocked while the network is congested - only for `KEEP_ALL` history with
   `RELIABLE` reliability. These publishers use `KEEP_LAST`, so that mode is not in play;
   the latency you are measuring is TCP's, not a blocked publisher's.

   None of this is particular to Zenoh. Any transport that guarantees ordered, reliable
   byte delivery behaves the same way: DDS configured with a TCP transport, an MQTT
   broker link, a WebSocket bridge, or a VPN tunnel carrying your ROS traffic. If you
   recognise the shape of this failure - rates holding while age climbs, and every topic
   on one connection degrading together - you will recognise it in all of them.

7. Heal it:

   ```bash
   scripts/workshop -t routed netem good
   ```

8. Compare this run with your Cyclone DDS notes from Exercise 3 as a **transport**
   comparison: the same fleet, the same impairment, UDP versus TCP. Which symptom and
   which monitoring signals changed? Where did best effort help, and where was it unable
   to? Do not produce a ranking of middlewares: one interactive incident is useful for
   diagnosis, but it is not a controlled benchmark, and you have changed the transport
   rather than isolating the RMW.

## Discussion: a transport-level alternative

A Zenoh client can connect to its router over UDP rather than TCP; lost datagrams then
become application-visible loss instead of TCP retransmission and stream-wide
head-of-line blocking. Its trade-offs are loss, reordering, and the need for
application/QoS policies that tolerate them. The routed UDP configuration is deliberately
not a student command yet: validation of this multi-node `rmw_zenoh_cpp` topology did not
deliver the fleet map reliably even on an unshaped link. Identify which traffic classes in
a real deployment can tolerate loss and what evidence you would require before approving
this change. Do not present UDP as a default or a proven remediation until that topology
is validated end to end.

## If you finish early, or want to continue at home

1. **Change the impairment, not the stack.** `bad` combines 20 Mbit, 80 ms of delay and
   15% loss, which is deliberately harsh. Re-run steps 3-6 with `ap degraded` (delay, no
   loss) and then `ap lossy` (5% loss), predicting each result first. Delay alone mostly
   shifts `age_ms`; loss is what makes a TCP-carried stream collapse, because every lost
   segment must be retransmitted before later bytes can be delivered.

   ```bash
   scripts/workshop -t routed netem degraded
   scripts/workshop -t routed netem lossy
   ```

2. **Give best effort a transport that can honour it.** Step 6 showed that a best-effort
   ROS publisher is still carried by TCP when only TCP endpoints are configured. Read
   `rmw_zenoh`'s notes on transports and work out what a UDP or QUIC endpoint would
   change, and what it would cost you. Lab 3 ships no validated UDP configuration: an
   earlier attempt did not deliver the fleet map even on an unshaped link, so treat this
   as a design exercise and say what evidence you would demand before shipping it.

3. **Try the wrong deployment on purpose.** The normal deployment has no robot-router
   uplink: the observer connects to each robot router. Change `connect` in
   [`routed-client.json5`](../scripts/discovery/zenoh/routed-client.json5) to
   `tcp/wifi-ap:7447` with `mode: "client"`, recreate the fleet, and apply `ap bad`. Watch
   the robot stop driving rather than merely appearing stale, and confirm it with
   `ros2 topic hz /robot_1/diff_drive_controller/cmd_vel` against `cmd_vel_timeout: 0.5`.
   Then put it back. This is the single most valuable thing to be able to recognise in a
   real deployment. Use `timeout 20 ros2 topic hz
   /robot_1/diff_drive_controller/cmd_vel` for the confirmation so it does not leave a
   subscriber running.

## When it does not work

**Map shows an empty grid.** Check the `observer` container actually sees robots:

```bash
docker exec observer bash -c 'source /opt/ros/jazzy/setup.bash && ros2 topic list' | grep fleet_map
docker logs observer 2>&1 | grep 'fleet_map: tracking' | tail -1
```

The first should list `/fleet_map/image_raw`; the second should name robot namespaces.
If the topic exists but nothing is tracked, check one robot with `docker logs mock-robot-1`.

**Browser stream frozen but it is unclear whether the problem is the demo or the browser.** Cross-check
against the out-of-band signal: netdata's **Lab 3 AP** charts (throughput/drops/backlog)
keep updating even if the in-band Foxglove stream stalls under `bad` - a frozen
in-band map with live out-of-band charts means stale telemetry, not a dead fleet.

**ROS CLI warns that it cannot connect to a Zenoh router.** It is using the flat-network
`/zenoh_session.json5` profile rather than the routed client profile. Confirm the router
is listening, then recreate the routed services so `scripts/workshop -t routed up` regenerates their
environment; this does not stop Netdata:

```bash
docker exec wifi-ap sh -c 'ss -ltn | grep 7447'
scripts/workshop -t routed down
scripts/workshop -t routed up 3 zenoh
scripts/workshop -t routed netem good
```

Wait for the robot bringup, repeat Step 4's first three checks, and only then apply
`ap bad` again. Do not set `ZENOH_SESSION_CONFIG_URI` manually for one command: that
masks a topology that needs to be recreated and leaves the other CLI commands inconsistent.

Tear down with `scripts/workshop -t routed down`. This is the last in-workshop
exercise for Lab 3 - [Exercise 5](5_after_the_workshop.md) is for exploring further at
home, and [Lab 4](../../lab4-benchmarking-and-decision/README.md) picks up the
clean-network, bring-your-own-data half of the comparison.
