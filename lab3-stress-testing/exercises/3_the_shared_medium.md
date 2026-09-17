# 3. The shared medium

In [Exercise 2](2_watch_a_healthy_link_fail.md), the fleet looked wrong after the shared
medium degraded. This exercise turns that observation into a diagnosis. The robots and
the `observer` operator container sit on separate subnets behind `wifi-ap`, so all
robot-to-robot and robot-to-observer traffic crosses one shaped queue. The `observer`
container runs the fleet-map compositor and is the observation point for the ROS CLI
commands below.

Build an evidence chain, in this order: **symptom -> monitoring signal -> hypothesis
-> confirming tool -> root cause**. The map is a symptom; do not treat it as proof.

## Steps

1. Exercise 2 healed the AP so you could observe recovery. Reintroduce the incident,
   then record the symptom in Lichtblick: which robots have stale ribbons, freeze, or
   jump? Leave the map open, but move to Netdata for the next observation.

   ```bash
   cd "$(git rev-parse --show-toplevel)"
   scripts/workshop -t routed netem bad
   ```

2. In Netdata, inspect **Lab 3 AP**. Note the relationship between configured capacity,
   throughput, qdisc drops per second, and queue backlog. A growing backlog or drops
   while the profile is `bad` supports the hypothesis that the shared medium is the
   bottleneck. These are drops at `wifi-ap`'s shared `ifb0` qdisc; the separate
   **Lab 3 Fleet Dropped Packets** charts read container NIC counters from Exercise 1
   and are not the loss signal for this routed topology.

3. Rule out host pressure. Search Netdata for **Apps CPU** and compare the
   `lab3_robots` and `lab3_console` process groups with the AP queue behaviour. For this
   link-only impairment, expect CPU to stay broadly steady while the AP backlog or drops
   change; that is evidence against a host bottleneck. If CPU is saturated before the AP
   backlog grows, the immediate constraint is compute, not the link. Write down which
   signal supports your conclusion.

4. Rule out a failed or slowed source before blaming the network. Each robot broadcasts
   its moving transform on the shared `/tf` topic, but that topic mixes every robot's
   transforms and, under `routed`, robots can reach each other through `wifi-ap` too.
   A "local" `/tf` reading at mock-robot-1 is therefore not purely local. Use the namespaced
   state topic `/robot_1/odometry/filtered` instead (50 Hz): only mock-robot-1 publishes it,
   so it cannot pick up another robot's traffic. In separate terminals, measure the same
   stream locally at its source and after it crosses the AP to the `observer` container:

   ```bash
   docker exec mock-robot-1 bash -c 'source /opt/ros/jazzy/setup.bash && timeout 20 ros2 topic hz /robot_1/odometry/filtered'
   docker exec observer bash -c 'source /opt/ros/jazzy/setup.bash && timeout 20 ros2 topic hz /robot_1/odometry/filtered'
   ```

   The local rate is the producer-side reference. If it remains steady while the
   observer rate stalls, falls, has long gaps, or receives no samples for the whole
   20-second window under `ap bad`, the source is not the immediate bottleneck. The
   initial `does not appear to be published yet` warning means this new reader has not
   received a sample yet; discovery, endpoint matching, or delivery can all cause it.
   It can appear before samples start. `ros2 topic hz` measures received messages after
   its own subscription starts, so compare the two readings rather than expecting an
   exact configured rate. Repeat the observer command after `ap good`: delivery
   returning with the healthy profile confirms the AP path.

5. Confirm whether the user-visible symptom is stale ROS traffic. From the `observer`
   container, first verify that the map diagnostic exists, then inspect the values built
   from those received transforms:

   ```bash
   docker exec observer bash -c 'source /opt/ros/jazzy/setup.bash && ros2 topic list --no-daemon' | grep -Fx /fleet_map/state_freshness
   docker exec observer bash -c 'source /opt/ros/jazzy/setup.bash && timeout 20 ros2 topic hz /fleet_map/state_freshness'
   docker exec observer bash -c 'source /opt/ros/jazzy/setup.bash && timeout 10 ros2 topic echo --once /fleet_map/state_freshness'
   scripts/workshop -t routed netem list
   ```

   If the first command prints nothing, just run it again: `--no-daemon` starts a fresh
   node with its own short discovery window each time, so a single check can race a
   healthy graph. That is not a sign of a problem, and waiting longer does not help;
   only `docker logs observer` errors would.

   Use `hz` only to confirm that the local map diagnostic is alive. Its publication rate
   follows the map render loop and need not change with remote TF delivery. The `echo`
   output is the evidence: record each robot's `state_freshness_ms` and status. Under
   `ap bad`, expect `DEGRADED` or `STALE` values in the hundreds of milliseconds or
   higher; after `ap good`, they should return to `FRESH` values in the tens of
   milliseconds. That change connects the operator symptom to received state over the
   transport path. `state_freshness_ms` is state age, not a one-way latency measurement.

6. **Confirm delivered traffic when Netdata and the ROS CLI disagree.** Lab 2 read
    captures through WebShark's GUI, frame by frame. Here, measure traffic that has
    survived the shared queue and is leaving `wifi-ap` for the operator. Resolve the AP
    interface facing the `observer` subnet, then capture only packets destined for that
    subnet:

   ```bash
   docker exec wifi-ap bash -lc '
       console_if=$(ip route get 172.40.100.10 | \
          awk "{for (i = 1; i <= NF; i++) if (\$i == \"dev\") { print \$(i + 1); exit }}")
   timeout 20 tshark -q -i "$console_if" \
          -f "dst net 172.40.100.0/24" \
       -z io,stat,5
   '
   ```

   The table now counts delivered packets toward `observer`, after the shared shaper, so
   it is relevant to the operator symptom. Compare windows with the same subscribers
   and offered load: less delivered traffic under `ap bad` supports the transport
   hypothesis. Do not expect its byte total to fall by `ap bad`'s configured loss
   percentage: this egress-only capture counts packets that survived the shaper, not
   packets offered to it. The profile also affects every peer flow in both directions,
   while DDS repair and background traffic vary between windows. Use the AP queue's
   sampled drop rate for the loss signal, and pair it with this capture and the
   state-freshness result. Packet inspection is a targeted confirmation step, not the
   continuous monitoring tool - reach for it only when Netdata and the ROS CLI disagree.
   To narrow the capture to one RMW's traffic, see "Not sure how to build the step 6
   capture" below.

7. **Measure the sensor class, not just the map.** With `ap bad` still applied, run the
   inspector on the scan class and let it settle for two or three windows:

   ```bash
   docker exec -it observer bash -c 'source /opt/ros/jazzy/setup.bash && python3 /scripts/lab3/fleet_inspector.py --robots robot_1,robot_2,robot_3 --sensors scan --qos reliable'
   ```

   Compared with the **healthy baseline** you recorded in
   [Exercise 2, step 4](2_watch_a_healthy_link_fail.md) - about 10 Hz at ~6 ms age and
   ~10 ms p95 - the rate holds up but the age collapses: readings near a second old,
   against the 1000 ms threshold the map paints red:

   ```text
   topic                                            Hz   age_ms   p95_ms     MB/s  gaps
   /robot_2/scan                                  12.0    584.3    989.4    0.017     1
   ```

   Messages are still arriving, so this is not a dead link. They are arriving *late*.
   Write down why late-but-complete is a different failure from missing.

   To confirm the age independently, `ros2 topic delay /robot_1/scan` measures the same
   `header.stamp` difference from the same container; Exercise 2 explains how each column
   is derived.

8. **Ask what the robot promised.** Inspect the QoS the scan publisher actually
   advertises:

   ```bash
   docker exec observer bash -c 'source /opt/ros/jazzy/setup.bash && ros2 topic info -v /robot_1/scan'
   ```

   It reports `Reliability: RELIABLE`. That is rclpy's default whenever a publisher is
   created with only a depth (`create_publisher(LaserScan, topic, 10)`). For this
   high-rate, freshness-sensitive sensor on a lossy medium, reliable delivery can spend
   capacity repairing old samples instead of delivering current ones. That tradeoff is
   precisely the high `age_ms` you just measured.

9. **Test the hypothesis from the subscriber side.** A reliable writer is compatible
   with a best-effort reader, and serves that reader without repair - so you can test
   the theory immediately, with no robot restart. Stop the inspector and rerun it with
   one flag changed:

   ```bash
   docker exec -it observer bash -c 'source /opt/ros/jazzy/setup.bash && python3 /scripts/lab3/fleet_inspector.py --robots robot_1,robot_2,robot_3 --sensors scan --qos best_effort'
   ```

   ```text
   topic                                            Hz   age_ms   p95_ms     MB/s  gaps
   /robot_1/scan                                   4.5     87.5    118.2    0.006     1
   ```

   Age drops by roughly a factor of six, and the rate drops too. That is the trade in
   plain sight: reliable requests repair for lost samples, while best effort discards
   them. For a lidar feeding obstacle avoidance, favouring current data over stale data
   is the better fit for this workload.

10. **Move the fix into configuration.** The subscriber flag proved the theory, but the
    real fix belongs with the publisher, and it does not require touching node code.
    Both sensor publishers opt in to ROS 2 QoS overrides, so a params file can retune
      them. First verify that every configured scan topic exists and has one publisher:

      ```bash
      docker exec observer bash -c '
         source /opt/ros/jazzy/setup.bash
         for robot in robot_1 robot_2 robot_3; do
            echo "=== /${robot}/scan ==="
            ros2 topic info "/${robot}/scan"
         done
      '
      ```

      Each topic should report `Publisher count: 1`. Then edit
      [`scripts/qos/sensor_qos.yaml`](../scripts/qos/sensor_qos.yaml) and set each
      robot's scan to `best_effort`:

    ```yaml
    /**:
      ros__parameters:
        qos_overrides:
          /robot_1/scan:
            publisher:
              reliability: best_effort
         /robot_2/scan:
            publisher:
               reliability: best_effort
         /robot_3/scan:
            publisher:
               reliability: best_effort
    ```

    QoS binds when the publisher is created, so the robots must be recreated. Editing a
    bind-mounted file does not change the container definition, so a plain
    `scripts/workshop -t routed up 3 cyclone` will **not** pick it up - tear down first:

    ```bash
    scripts/workshop -t routed down
    scripts/workshop -t routed up 3 cyclone
    scripts/workshop -t routed netem bad
    ```

      Verify that all three publisher overrides took effect:

    ```bash
      docker exec observer bash -c 'source /opt/ros/jazzy/setup.bash && ros2 topic info -v /robot_1/scan'
      docker exec observer bash -c 'source /opt/ros/jazzy/setup.bash && ros2 topic info -v /robot_2/scan'
      docker exec observer bash -c 'source /opt/ros/jazzy/setup.bash && ros2 topic info -v /robot_3/scan'
    ```

   Each should report `Reliability: BEST_EFFORT`. Now every subscriber benefits, not
   just the one you happened to run with a flag.

11. **Escalate to the camera and observe overload handling.** Each robot can also publish
   an ~850x1050 RGB frame at 10 Hz, about 2.7 MB per message - roughly 214 Mbit/s of
   payload from a single robot into a 100 Mbit/s medium. Nothing subscribes to it by
   default, and compositing it is the largest CPU cost on a robot, so the routed fleet
   starts with the camera switched off. Turn it on, and heal the AP so the only variable
   is offered load. Keep the scan publishers `best_effort` from Step 10: the camera
   publisher is separate and remains `RELIABLE` by default, so this test isolates
   oversized offered load rather than reverting the scan QoS fix. `ap good` does **not**
   remove shaping: it retains the shared 100 Mbit/s AP budget with only 0.1% baseline
   loss. `ap bad` instead lowers that budget to 20 Mbit/s and adds 80 ms delay plus 15%
   bursty loss. This step tests congestion caused by offered load alone:

    ```bash
    scripts/workshop -t routed down
    MOCK_SENSOR_COUNT=1 scripts/workshop -t routed up 3 cyclone
    scripts/workshop -t routed netem good
    ```

   Before starting the inspector, open Netdata's **Lab 3 AP** charts and note the
   baseline throughput, queue backlog, and qdisc drops. Leave those charts visible,
   then start the inspector:

   ```bash
   docker exec -it observer bash -c 'source /opt/ros/jazzy/setup.bash && python3 /scripts/lab3/fleet_inspector.py --robots robot_1,robot_2,robot_3 --sensors both --max-camera 1'
   ```

   While it runs, confirm the camera subscription exists:

   ```bash
   docker exec observer bash -c 'source /opt/ros/jazzy/setup.bash && ros2 topic info -v /robot_1/sensor_0/camera/image_raw'
   ```

   It should report one publisher and the inspector subscriber. Compare Netdata with
   the baseline: the camera subscription should raise AP throughput and can create a
   queue backlog and qdisc drops despite `ap good`. Then compare the inspector rows with
   the Lichtblick map. The camera can report `0.0` Hz because a 2.7 MB frame is split
   into thousands of fragments and one lost fragment discards the whole frame. Interface
   accounting can show the robot offering about 29 MB/s once transport overhead is
   included, while `observer` receives about 0.3 MB/s.

   This is the lesson: the camera subscriber makes more than 214 Mbit/s of payload
   contend for a 100 Mbit/s shared queue, so it can create backlog and queue drops even
   under `ap good`. Offered bytes are not useful data when fragmentation and loss prevent
   complete frames from arriving. The inspector reports only scan and camera
   subscriptions; the Lichtblick map is driven separately by `/tf`, so `0.0` sensor rows
   do not mean the robots have stopped moving. Under overload, reliable scan delivery can also arrive in bursts:
   a window can show no samples, then a later window can show a rate above the 10 Hz
   source rate with high age. Read that as queued, late sensor data, not a new source
   rate.

   The AP's SFQ leaf can protect small `/tf` and scan flows while the camera flow fails.
   A smooth map is evidence that fair queueing contained the noisy subscription; a
   frozen map means the offered load exceeded that protection, and should be correlated
   with the AP queue/drop charts. Stop the inspector with Ctrl-C and the fleet recovers.

<details>
<summary>Answer: reading the evidence chain</summary>

The shared queue is a plausible root cause only when independent signals agree: the
operator map becomes stale, the AP backlog or drop rate changes when the profile
changes, and ROS topic flow/freshness follows that change. A frozen map alone is not
enough because it is itself in-band traffic. Conversely, saturated CPU with a quiet AP
queue points to a host bottleneck. Use a Lab 2 capture when these signals conflict or
when you need packet-level evidence for retransmission or loss.

Steps 7-11 add a second lesson: the medium was not the only defect. A reliable sensor
publisher converts loss into latency, and an oversized subscription converts a healthy
link into a dead one. Impairment exposed both, but neither was caused by the impairment.
</details>

## What to report

Write five short statements: the observed map symptom; the Netdata signal; the leading
hypothesis; the ROS CLI or packet-level confirmation; and the root cause. State what
evidence would have changed your conclusion.

Then add the numbers from steps 7-11: scan age under `ap bad` as reliable versus best
effort, and what one raw camera subscription did to the rest of the fleet on a healthy
medium. Say which change you would actually ship, and which topics in *your* deployment
are currently reliable because nobody chose - they just called `create_publisher` with a
depth.

## When it does not work

**AP charts do not change after `ap bad`.** Check the profile and raw qdisc state with
`scripts/workshop -t routed netem list`. If the system lacks shaping modules, preflight reports it and
the impairment result is not meaningful.

**`ros2 topic hz` reports no data.** First verify the source is alive from `mock-robot-1`:

```bash
docker exec mock-robot-1 bash -c 'source /opt/ros/jazzy/setup.bash && timeout 20 ros2 topic hz /robot_1/odometry/filtered'
```

Then repeat the `observer` command after `ap good`. A steady source rate and recovery
after healing the AP supports a transport problem; no source rate points to the
producer, while no recovery on `observer` points to discovery or endpoint matching.

**Not sure how to build the step 6 capture.** Start with the routed interfaces and paths:

```bash
docker exec wifi-ap ip -br address
docker exec wifi-ap ip route
```

Step 6's command intentionally stops after 20 seconds; `timeout` may return status 124
when the capture window ends. The packet table printed before that status is the
evidence you need. To narrow it to one RMW's traffic instead of the whole shared
subnet: for the default `ROS_DOMAIN_ID=25`, the RTPS base is `7400 + 250 * 25 = 13650`,
so a DDS-focused capture can use `-f "net 172.40.0.0/16 and udp portrange 13650-13849"`.
For Zenoh, every node connects to the router over TCP (see
`discovery/zenoh/routed-client.json5`), so use `-f "net 172.40.0.0/16 and tcp port 7447"`.

Leave the routed fleet running. [Exercise 4](4_repeat_with_zenoh.md) repeats the same
incident over TCP, using Zenoh's default transport, to investigate what reliable
byte-stream delivery changes.
