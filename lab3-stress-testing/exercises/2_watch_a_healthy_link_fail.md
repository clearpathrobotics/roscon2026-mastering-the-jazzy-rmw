# 2. Watch a healthy fleet fail

You now know what normal discovery and resource signals look like in Netdata. Put a
moving fleet behind one shared wireless medium, then create a visible fault without
changing the robots. Start with Cyclone DDS; [Exercise 3](3_the_shared_medium.md)
turns what you see here into an evidence-based diagnosis.

`ap_shape.sh` is the Lab 3 shared-medium netem emulator. Its `bad` profile constrains
the single queue every robot and the `observer` operator container must cross.

## Steps

1. Tear down Exercise 1's fleet, choose Cyclone DDS, and start a routed mock fleet:

   ```bash
   cd "$(git rev-parse --show-toplevel)"
   scripts/workshop -t flat down
   scripts/workshop -t routed up 3 cyclone
   ```

   The `routed` command waits until all AP interfaces are attached. ROS discovery may
   continue after it returns. The observer idles until you start its Foxglove bridge:

   ```bash
   scripts/workshop observer bridge
   scripts/workshop lichtblick up
   ```

   Apply the healthy shared-AP profile, then open the printed Lichtblick URL:

   ```bash
   scripts/workshop -t routed netem good
   ```

   If this command prints `SKIP`, the host kernel cannot apply the shared-medium
   impairment. Continue only with the topology and discovery observations; the `bad`
   profile will not produce valid impairment evidence on this host.

   ```bash
   http://localhost:8080/?ds=foxglove-websocket&ds.url=ws://localhost:8765
   ```

2. Open <http://localhost:19999> in a second tab. Search for **Lab 3 AP** and keep
   the shared throughput, drops, and queue backlog charts visible. Search for
   **Apps CPU** to keep the `lab3_robots` and `lab3_console` process groups nearby.

   Do not use **Lab 3 Fleet Dropped Packets** for this step. That chart belongs to
   Exercise 1's separate flat/pinned-fleet deployment and reads each container NIC's local
   drop counter. `ap bad` drops packets at the `wifi-ap` shared `ifb0` qdisc, which is
   reported by **Lab 3 AP Qdisc Drops**.

3. Watch the operator map for 30 seconds with the applied `good` profile. The robots
   should move smoothly and the TF freshness ribbons should remain mostly green.

4. Find out what is actually crossing the AP. The map is drawn inside `observer` operator
   container from `/tf` alone, and Foxglove Bridge only subscribes to a topic once a panel opens it.
   So every robot's `scan` and camera are published to nobody. Check one:

   ```bash
   docker exec observer bash -c 'source /opt/ros/jazzy/setup.bash && ros2 topic info /robot_1/scan'
   ```

   `Subscription count: 0`. A publisher alone puts nothing on the wire - a *subscriber*
   is what pulls a topic across the shared medium. The map still subscribes to `/tf`, so
   transform state remains baseline AP traffic. Open a second terminal and start the
   fleet inspector with no subscriptions, to establish that it adds no *sensor* load:

   ```bash
   docker exec -it observer bash -c 'source /opt/ros/jazzy/setup.bash && python3 /scripts/lab3/fleet_inspector.py --robots robot_1,robot_2,robot_3 --sensors none'
   ```

   Stop it with Ctrl-C, then start it again on the scan class and watch **Lab 3 AP**
   throughput in Netdata rise as the subscriptions match:

   ```bash
   docker exec -it observer bash -c 'source /opt/ros/jazzy/setup.bash && python3 /scripts/lab3/fleet_inspector.py --robots robot_1,robot_2,robot_3 --sensors scan'
   ```

   The inspector prints one row per subscribed topic and rewrites it once a second. That
   running readout is the **inspector table**, referred to by that name from here on. On
   a healthy medium each robot arrives at about 10 Hz with single-digit millisecond age,
   for roughly 0.043 MB/s in total:

   ```text
   topic                                            Hz   age_ms   p95_ms     MB/s  gaps
   /robot_1/scan                                  10.0      6.1      9.8    0.014     0
   /robot_2/scan                                  10.0      6.5      8.8    0.014     0
   /robot_3/scan                                  10.0      6.4      8.2    0.014     0
   ```

   `age_ms` is the gap between the sensor's own timestamp and arrival at `observer`.

   **Write these three numbers down: rate, `age_ms`, and `p95_ms`. This is your healthy
   baseline**, and Exercises 3 and 4 both compare against it. Leave the inspector running;
   it is your measurement for the next step.

   <details>
   <summary>Where these numbers come from, and how to reproduce them yourself</summary>

   Nothing here is privileged. The inspector subscribes like any ROS 2 node and, once a
   second, reports what arrived in that window:

   | Column | How it is computed |
   | --- | --- |
   | `Hz` | messages received in the window / window length |
   | `age_ms` | `observer` clock at arrival - the message's own `header.stamp` |
   | `p95_ms` | 95th percentile of those ages, so one bad sample cannot hide in a mean |
   | `MB/s` | summed payload bytes / window length |
   | `gaps` | arrivals separated by more than 500 ms, i.e. an operator-visible stall |

   The first three have stock equivalents. Run one against the same topic, let it
   settle, record its output, then let its in-container timeout stop it before running
   the next:

   ```bash
   docker exec observer bash -c 'source /opt/ros/jazzy/setup.bash && timeout 15 ros2 topic hz /robot_1/scan'
   docker exec observer bash -c 'source /opt/ros/jazzy/setup.bash && timeout 15 ros2 topic delay /robot_1/scan'
   docker exec observer bash -c 'source /opt/ros/jazzy/setup.bash && timeout 15 ros2 topic bw /robot_1/scan'
   ```

   On a healthy medium `ros2 topic delay` reports `average delay: 0.007` and `ros2 topic
   bw` reports `14.47 KB/s ... Message size mean: 1.52 KB` - the same 7 ms and
   ~0.014 MB/s the table shows. `delay` only works because the publisher stamps a
   `header`, and because every container here shares the host clock; across real machines
   that number is only meaningful with clocks disciplined by NTP or PTP.

   The inspector exists for what those three cannot do: watch several robots at once,
   report a percentile rather than an average, count stalls, and choose the subscription
   QoS. Note too that `hz`, `delay`, and `bw` are each *subscribers* - running them also
   pulls the topic across the AP, so they add the very load you are measuring. The
   in-container timeout stops each one before returning to the inspector; a running stock
   tool remains a subscriber.
   </details>

5. Degrade only the shared medium:

   ```bash
   scripts/workshop -t routed netem bad
   ```

   Watch the map, the inspector table, and Netdata together. The `bad` profile can
   already delay or lose the map's `/tf` state; the inspector shows what additionally
   happens to the subscribed scan stream. Which robots freeze or jump? What changes in
   the AP charts, and what happens to `age_ms` and `p95_ms`? Then recover without
   restarting anything:

   ```bash
   scripts/workshop -t routed netem good
   ```

   Do not diagnose from the map alone. It is an in-band symptom display; the Netdata
   AP charts and the inspector table remain available when the map itself becomes
   stale.

<details>
<summary>Answer: what the map is telling you</summary>

The map shows the operator consequence of stale or missing state, not necessarily a
stopped robot. The shared AP queue is the first hypothesis: `ap bad` can raise its
backlog and drops while the fleet still runs locally. Exercise 3 distinguishes that
from a host CPU bottleneck and verifies whether the topic stream is actually stale.
</details>

## When it does not work

**Map shows an empty grid.** Confirm the `observer` container sees the map topic:

```bash
docker exec observer bash -c 'source /opt/ros/jazzy/setup.bash && ros2 topic list' | grep fleet_map
docker logs observer 2>&1 | grep 'fleet_map: tracking' | tail -1
```

**The map freezes but the cause is unclear.** Check Netdata. Live AP charts with a
frozen map indicate stale in-band telemetry, not proof that the fleet died.

**`/robot_1/scan` is an unknown topic.** The routed fleet or DDS discovery may still
be starting. Wait a few seconds and run the check again. Once discovery has settled,
`ros2 topic info /robot_1/scan` reports one publisher and zero subscriptions before
the inspector starts.

**`/robot_1/scan` has subscribers before the inspector starts.** A prior `ros2 topic`
measurement may still be running in the `observer` container. Find it, then stop its listed PID:

```bash
docker exec observer bash -c "ps -eo pid,args | grep -E '[r]os2 topic (hz|delay|bw|echo)'"
docker exec observer kill <pid>
```

Run `ros2 topic info /robot_1/scan` again. Before the inspector starts, it should
report `Subscription count: 0`.

**Lab 3 Fleet Dropped Packets stays at zero.** Expected for this routed exercise.
The AP qdisc, not the robot NIC, is dropping packets. Search for **Lab 3 AP Qdisc
Drops** and use `scripts/workshop -t routed netem list` to inspect the same
cumulative `tc` counter.

Leave the routed fleet running. [Exercise 3](3_the_shared_medium.md) uses it to trace
the problem from symptom to root cause.
