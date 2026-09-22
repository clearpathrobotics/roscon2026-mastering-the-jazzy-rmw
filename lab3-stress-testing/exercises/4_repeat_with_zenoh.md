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

Exercise 4 deliberately uses a hub fixture, unlike Exercise 5's generated default:
each robot router connects to the Zenoh router on `wifi-ap`, and the observer peer connects
to that same hub. The fixture's configs make the AP router part of the active data path:

```text
robot ROS nodes -> local robot router -> wifi-ap rmw_zenohd <- observer peer
                         (loopback)       (one observer TCP session)
```

This is intentional: the hub gives the exercise one deterministic TCP connection from the
observer carrying traffic aggregated by the hub. Exercise 5 explores the generated default,
where the observer connects to each robot router directly.

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
   scripts/workshop -t routed up 3 zenoh --rmw-directory lab3-stress-testing/fixtures/routed_zenoh_ap_hub
   scripts/workshop observer bridge
   scripts/workshop lichtblick up
   scripts/workshop -t routed netem good
   ```

   The routed command waits for the recreated AP and all of its interfaces. Zenoh router
   startup and ROS discovery can take longer. Confirm the robot and AP router listeners in Step 2,
   then open:

   ```
   http://localhost:8080/?ds=foxglove-websocket&ds.url=ws://localhost:8765
   ```

   (Opening plain `http://localhost:8080` does not select the data source - use the
   full URL. If the layout does not show the operator map, see the [Lab 3
   README](../README.md#how-the-live-fleet-works) for how to import it.)

   <details>
   <summary>Why the RMW cannot be hot-swapped</summary>

   `RMW_IMPLEMENTATION` and every QoS setting bind when a node's participant is created;
   ROS 2 has no API to renegotiate them on a running node. Each robot's local Zenoh router
   and the observer's routed peer session must use Zenoh to receive the robots' topics.
   That is why Step 1 recreates the routed topology instead of flipping an
   environment variable under running nodes. The network shaping (`netem bad`/`good`) is the
   only thing that changes live, which is why it is the knob built for a live demo.
   </details>

2. Inspect the deployment before introducing a fault. This hub fixture has one Zenoh router
   per robot, one Zenoh router on `wifi-ap`, and one observer peer. Robot routers and the
   observer connect to the AP hub. Local ROS nodes connect to their robot's router over
   loopback, so the observer has one TCP session to the hub while each robot's local control
   path stays local. This workshop configuration uses TCP, so each host's remote traffic
   crosses the shared AP while its own control loop stays on loopback:

   ```bash
   docker exec mock-robot-1 sh -c '
     echo "=== $ZENOH_SESSION_CONFIG_URI ==="
     cat "$ZENOH_SESSION_CONFIG_URI"
     echo "=== $ZENOH_ROUTER_CONFIG_URI ==="
     cat "$ZENOH_ROUTER_CONFIG_URI"
   '
   docker exec observer sh -c '
     echo "=== $ZENOH_SESSION_CONFIG_URI ==="
     cat "$ZENOH_SESSION_CONFIG_URI"
   '
   docker exec mock-robot-1 sh -c 'ss -ltn | grep 7447'
   docker exec wifi-ap sh -c 'ss -ltn | grep 7447'
   ```

   **Question: what do you expect these checks to prove?** Predict what listeners on
   `mock-robot-1` and `wifi-ap` say about router readiness, and what they cannot say about
   an established Zenoh connection. Also predict why the observer should be a peer that
   dials the hub rather than another listener on port 7447.

   `$ZENOH_SESSION_CONFIG_URI` (e.g. `/rmw_configuration/routed/zenoh/mock-robot-1.json5`) is the
   ROS client's configuration: it connects to its local router at `tcp/localhost:7447`.
   `$ZENOH_ROUTER_CONFIG_URI` (e.g. `mock-robot-1-router.json5` in the same directory) is that
   router's configuration: it listens locally on `7447` and connects to `wifi-ap:7447`.
   The observer's session config is a `peer` with `connect: ["tcp/wifi-ap:7447"]` and no
   local `rmw_zenohd` router. Confirm that `mock-robot-1` and `wifi-ap` are listening;
   those are the two router endpoints used by this fixture. `LISTEN ... 0.0.0.0:7447` means the router accepts TCP
   connections on every IPv4 interface; `LISTEN ... *:7447` has the same practical
   meaning here.

   <details>
   <summary>Answer: listening proves readiness and shape, not an established data path</summary>

   These lines prove that each router is ready to accept a connection, not that the
   routers have connected or that ROS data is flowing. The observer runs no local
   `rmw_zenohd`, so there is no `LISTEN ... 7447` for it to expose; it dials the hub as a
   peer instead. That is why you check listeners on `mock-robot-1` and `wifi-ap`, and
   not on `observer`.

   </details>

   Watch the map for 30 seconds with `good` applied and take a **Zenoh healthy baseline**
   with the inspector, the same way you did in
   [Exercise 2, step 4](2_watch_a_healthy_link_fail.md). You will compare against this
   baseline in step 6, so record the numbers before moving on:

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

   **Question: will this look different from Exercise 3?** Predict which parts should
   remain the same (shared AP queue, stale TF, map symptoms) and which part may differ
   because Zenoh carries the traffic over TCP. Record your prediction before watching
   the ribbon colours and map.

   <details>
   <summary>Answer: the symptom can look similar, but TCP adds stream-level repair</summary>

   Watch the ribbon colours (green/amber/red = TF freshness) and the map. Some robots
   should begin to freeze or jump as telemetry becomes stale, with the freshness getting deep in the red.

   </details>

   <details>
   <summary>Why the topology is worth this much attention</summary>

   The deployed `peer` sessions connect to a local router over loopback. The local router
   links onward to `wifi-ap`, so remote robot/observer traffic crosses the AP while the
   robot's local `pilot` -> `cmd_vel` -> `twist_mux` -> controller path does not depend
   on it. Switch the sessions to `client` mode pointed at the remote router - the optional
   exercise below shows how - and that local control path is relayed through `wifi-ap`.
   Under `netem bad`, the controller can then miss its `cmd_vel_timeout: 0.5` deadline and
   stop the robot for a real control-path reason, rather than merely showing stale state.

   That distinction matters for Lab 4: benchmarking a client-of-a-remote-router setup
   would measure a deployment mistake rather than the middleware.
   </details>

4. Diagnose the stall. In Netdata, use **Apps CPU** and interface charts to rule out host
   process pressure. Use **Lab 3 AP** to establish that the shared queue is dropping
   packets or building a backlog. Then check
   `/fleet_map/state_freshness` from the `observer` container. First confirm that a new
   ROS CLI process joins the same routed Zenoh session as the running operator tools:

   **Question: what evidence would separate a host problem from a transport problem?**
   Predict what Apps CPU, the AP queue/drop charts, and `state_freshness_ms` should show
   if the robots keep computing normally but their telemetry is delayed on the AP path.

   ```bash
   docker exec observer bash -lc 'echo "$ZENOH_SESSION_CONFIG_URI"'
   docker exec observer bash -lc 'source /opt/ros/jazzy/setup.bash && ros2 topic list --no-daemon | grep -x /fleet_map/state_freshness'
   docker exec observer bash -lc 'source /opt/ros/jazzy/setup.bash && ros2 topic info -v /fleet_map/state_freshness'
   ```

   `--no-daemon` starts a fresh node with its own short discovery window each time, so
   a single check can race a healthy graph. Rerun it if the first attempt prints
   nothing; waiting longer does not help.

   The first command must print the observer's own zenoh session config path (e.g.
   `/rmw_configuration/routed/zenoh/observer.json5`); the next two must find one
   `diagnostic_msgs/msg/DiagnosticArray` publisher named `fleet_map`. Read a report,
   then sample its rate for about 20 seconds; each in-container timeout stops its reader:

   ```bash
   docker exec observer bash -lc 'source /opt/ros/jazzy/setup.bash && timeout 20 ros2 topic echo /fleet_map/state_freshness'
   docker exec observer bash -lc 'source /opt/ros/jazzy/setup.bash && timeout 20 ros2 topic hz /fleet_map/state_freshness'
   ```

   <details>
   <summary>Answer: steady CPU plus AP pressure and older state indicates transport trouble</summary>

   Each `status` entry reports a robot's `state_freshness_ms` and its health. Compare
   those values and the received rate under `good` and `bad`. These signals show the
   conditions for a transport failure; they do not prove a TCP retransmission by
   themselves.

   </details>

5. **Measure TCP retransmissions for the first time in Lab 3.** Exercise 3 introduced
   the live TShark workflow for measuring packets delivered toward the observer; this
   step applies the Zenoh TCP filter and Lab 2's retransmission display filter to test
   the transport hypothesis directly. Run it once under `good` and again while `bad` is
   active. Capture on the `observer`: it does not run `rmw_zenohd`, but its Zenoh peer
   session owns the TCP socket to the `wifi-ap` router, so each segment is seen once on
   the observer's interface. Running this on the forwarding `wifi-ap` with `-i any`
   would see forwarded packets twice and could make ordinary forwarding look like
   retransmission:

   **Question: what do you predict will change between `good` and `bad`?** Expect a small
   baseline under `good`, because it still has loss, and more retransmissions or tighter
   clusters under `bad`. What would clustered retransmissions imply for later bytes in the
   same TCP stream and for ROS topics sharing that stream?

   Step 3 left `bad` applied, so heal the link first, capture, then reintroduce `bad` and
   capture again. The second `netem bad` restores the profile step 6 expects:

   ```bash
   scripts/workshop -t routed netem good
   docker exec observer bash -lc '
     timeout 20 tshark -i eth0 -n \
       -f "net 172.40.0.0/16 and tcp port 7447" \
       -Y "tcp.analysis.retransmission" \
       -T fields -e frame.time_relative -e ip.src -e ip.dst -e tcp.seq -e tcp.len
   '
   scripts/workshop -t routed netem bad
   docker exec observer bash -lc '
     timeout 20 tshark -i eth0 -n \
       -f "net 172.40.0.0/16 and tcp port 7447" \
       -Y "tcp.analysis.retransmission" \
       -T fields -e frame.time_relative -e ip.src -e ip.dst -e tcp.seq -e tcp.len
   '
   ```

   <details>
   <summary>Answer: loss creates TCP repair and head-of-line blocking</summary>

   This is a Lab 2 display filter with a Lab 3-specific output format. Each printed
   row has already matched `tcp.analysis.retransmission`; it is not every Zenoh TCP
   packet. The five columns are:

   | Column | Meaning |
   |---|---|
   | `frame.time_relative` | seconds since this capture started |
   | `ip.src`, `ip.dst` | the two ends of the TCP session visible at the observer. Most rows will show `wifi-ap` (`172.40.100.2`) -> observer (`172.40.100.10`) because that direction carries the bulk of the fleet's downstream data; occasional reverse-direction rows are the observer's own upstream traffic being repaired |
   | `tcp.seq` | first byte sequence number of the retransmitted TCP segment |
   | `tcp.len` | TCP payload bytes in that segment; `1448` is a near-MTU-sized data segment, while small values can be control or small application messages |

   Do not try to infer a ROS topic from the sequence number or payload length. The
   observer sees its single TCP session with `wifi-ap`; Zenoh multiplexes routed traffic
   from the robots over that session, so a retransmitted segment cannot be attributed to a
   particular robot or ROS topic from these fields. Compare the two 20-second captures
   instead. `good` still applies 0.1% bursty loss, so it may show a small retransmission
   baseline or zero events in a short sample. A marked increase or clustering of
   retransmissions under `bad` is evidence
   of transport repair under the impaired medium. At the end of each run, TShark prints
   a packet total. With a display filter active, that total is the number of rows shown
   above, so it is the retransmission count for the 20 seconds. Correlate it with
   AP drops/backlog and state freshness; a raw retransmission count alone does not
   measure user-visible impact.

   Retransmissions together with AP loss/backlog and increasing state age support this
   explanation: TCP holds later bytes behind a missing segment, so several ROS topic
   streams carried by that TCP session can appear to stall together.

   </details>

6. Retry the fix that worked under DDS, and watch it fail. In Exercise 3, making the
   sensor class best effort cut scan age by roughly six times. Run the same comparison
   here, while `netem bad` is applied:

   **Question: why might the same ROS QoS change behave differently here?** Predict the
   rate, age, and p95 pattern for `reliable` versus `best_effort`. Then explain what
   best effort changed in Exercise 3: did it stop per-sample repair, or did it change
   the underlying transport? What can it change when the session still uses TCP?

   ```bash
   docker exec -it observer bash -c 'source /opt/ros/jazzy/setup.bash && python3 /scripts/lab3/fleet_inspector.py --robots robot_1,robot_2,robot_3 --sensors scan --qos reliable'
   ```

   ```bash
   docker exec -it observer bash -c 'source /opt/ros/jazzy/setup.bash && python3 /scripts/lab3/fleet_inspector.py --robots robot_1,robot_2,robot_3 --sensors scan --qos best_effort'
   ```

   These numbers vary widely run-to-run; the point is that neither column is clearly
   better, unlike the ~6x scan-age improvement `best_effort` gave under Cyclone in
   Exercise 3. One representative pair:

   ```text
   reliable      10.0 Hz / age  385 ms      2.5 Hz / age 3561 ms      9.7 Hz / age 2100 ms
   best_effort    5.2 Hz / age 1655 ms      6.2 Hz / age 3359 ms      9.0 Hz / age 2377 ms
   ```

   <details>
   <summary>Answer: ROS best effort cannot override TCP byte-stream repair</summary>

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

   Note what *does not* apply here. Zenoh sets `CongestionControl::BLOCK` - the
   publisher's `publish()` call stalls until the network drains, rather than dropping a
   sample - only for `KEEP_ALL` history with `RELIABLE` reliability. These publishers use
   `KEEP_LAST`, so that mode is not in play; the latency you are measuring is TCP's, not
   a blocked publisher's.

   None of this is particular to Zenoh. Any transport that guarantees ordered, reliable
   byte delivery behaves the same way: DDS configured with a TCP transport, an MQTT
   broker link, a WebSocket bridge, or a VPN tunnel carrying your ROS traffic. If you
   recognise the shape of this failure - rates holding while age climbs, and every topic
   on one connection degrading together - you will recognise it in all of them.

   </details>

7. Heal it and confirm recovery. Rate should return to about 10 Hz and age should drop
   back to the baseline you took in step 2:

   ```bash
   scripts/workshop -t routed netem good
   docker exec -it observer bash -c 'source /opt/ros/jazzy/setup.bash && python3 /scripts/lab3/fleet_inspector.py --robots robot_1,robot_2,robot_3 --sensors scan'
   ```

8. Compare this run with your Cyclone DDS notes from Exercise 3 as a **transport**
   comparison: the same fleet, the same impairment, UDP versus TCP.

   **Question: can you summarize the comparison in four sentences?** State the changed
   symptom, the transport signals that changed, the hypothesis that explains them, and
   what best effort could and could not change. Do not produce a ranking of middlewares:
   one interactive incident is useful for diagnosis, but it is not a controlled
   benchmark, and you have changed the transport rather than isolating the RMW.

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

3. **Optional: deliberately move one robot's local connection onto the AP.** The
   [`routed_zenoh_ap_hub` fixture](../fixtures/routed_zenoh_ap_hub/README.md) is not itself
   the mistake: it supplies a central Zenoh router on `wifi-ap` for this experiment. The
   mistake is changing robot 1's ROS session from its local router to that remote hub.
   Changing the observer's endpoint alone would not do this: it would only change where
   the observer receives data. The robot session is the connection used by robot 1's
   `pilot` and other ROS nodes, so changing that session is what moves the control path.
   In [`lab3-stress-testing/fixtures/routed_zenoh_ap_hub/mock-robot-1.json5`](../fixtures/routed_zenoh_ap_hub/mock-robot-1.json5), change `connect` to
   `tcp/wifi-ap:7447` with `mode: "client"`, recreate the fleet with
   `scripts/workshop -t routed up 3 zenoh --rmw-directory lab3-stress-testing/fixtures/routed_zenoh_ap_hub`,
   and apply `netem bad`. This makes robot 1's local ROS nodes reach their router through
   the shared AP instead of loopback. Watch the robot stop driving rather than merely
   appearing stale, and confirm it with `ros2 topic hz /robot_1/diff_drive_controller/cmd_vel`
   against `cmd_vel_timeout: 0.5`.
   How hard it stalls depends on your machine: `netem bad` may only make it stutter, so apply
   `scripts/workshop -t routed netem reorder` (or `severe`) for a decisive, continuous stop.
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
`/rmw_configuration/flat/zenoh/mock-robot.json5` profile rather than the routed client
profile. Confirm the router
is listening, then recreate the routed services so `scripts/workshop -t routed up` regenerates their
environment; this does not stop Netdata:

```bash
docker exec mock-robot-1 sh -c 'ss -ltn | grep 7447'
scripts/workshop -t routed down
scripts/workshop -t routed up 3 zenoh --rmw-directory lab3-stress-testing/fixtures/routed_zenoh_ap_hub
scripts/workshop -t routed netem good
```

Wait for the robot bringup, repeat Step 4's first three checks, and only then apply
`netem bad` again. Do not set `ZENOH_SESSION_CONFIG_URI` manually for one command: that
masks a topology that needs to be recreated and leaves the other CLI commands inconsistent.

Tear down with `scripts/workshop -t routed down`. This is the last in-workshop
exercise for Lab 3 - [Exercise 5](5_after_the_workshop.md) is for exploring further at
home, and [Lab 4](../../lab4-benchmarking-and-decision/README.md) picks up the
clean-network, bring-your-own-data half of the comparison.
