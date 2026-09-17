# Lab 2: ROS 2 on the wire

Three mock robots stream a compressed camera image and a laser scan while netem shapes
their links. You will take a packet capture, find the failure the ROS 2 CLI cannot explain,
and then find the case where the capture itself is the thing that is wrong. Everything runs
in Docker on your own laptop.

<details>
<summary><b>Setup:</b> bring up the fleet and start capturing</summary>

Start by modifying some permissions `chmod 1777 lab2-on-the-wire/captures/` from the repository root.

Run all `scripts/workshop` commands from the repository root.

```bash
scripts/workshop -t flat up 3 fast   # observer + 3 robots (the flat fleet)
scripts/workshop webshark up             # webshark viewer, layered on the fleet
scripts/workshop observer capture start 3 --files 12    # rotating capture at the observer
```

Then open <http://localhost:8085/webshark/>. Leave this running: exercise 1 needs the
capture to have been going for a couple of minutes.

`scripts/workshop observer capture start [N] [--duration S]` sets the robot count and seconds per file
(default 3 robots, 30 s). `--files N` limits the number of files kept (default 6) and
`--max-mb MB` the total bytes across them (default 2000), so on a fast link files rotate on
size before the 30 s mark. Exercise 1 compares the first window of the run against the current one, so `12`
keeps six minutes of history instead of three and gives you room to read. The JPEG
republishers now launch with each robot, so `sensor_0/camera/image_comp/compressed` is
available as soon as the fleet is up.

`scripts/workshop netem list` shows every netem profile, `scripts/workshop -t flat netem`
shows the current shaping state, and `scripts/workshop -t flat down` tears the fleet down
(webshark, netdata, and the collector are independent - stop each with its own `down`).
Everything in `captures/` is gitignored.

Reload the viewer to see newly rotated files, which are listed newest first. sharkd does
not poll a growing file, so click Refresh on an open capture to pull in packets written
since you opened it.
</details>

<details>
<summary><b>Reference:</b> topics, QoS, and the per-RMW configs</summary>

Each robot publishes two topics:

- **camera**: `/robot_<i>/sensor_0/camera/image_comp/compressed`,
  `sensor_msgs/CompressedImage`, a JPEG of about 41 KB at 10 Hz. It does not fit in one
  datagram, so it fragments, and it is where loss shows.
- **scan**: `/robot_<i>/scan`, `sensor_msgs/LaserScan` at 10 Hz. One datagram, so it
  survives loss the camera cannot, which makes it the control.

Both are read **best-effort, keep-last, depth 10**
([`scripts/rmw_subscriber_probe.py`](scripts/rmw_subscriber_probe.py)).
DDS does not retransmit a dropped best-effort sample, so on Fast and Cyclone a lost
fragment is a lost frame. Zenoh carries the same ROS QoS over a TCP session, which re-sends
the bytes regardless of what the ROS layer asked for. That difference is exercise 3.

The transport configs the workshop runner loads:

- **Fast DDS**: [`../docker/rmw_configuration/fast/`](../docker/rmw_configuration/fast/)
  for robots 1-2 and the observer, plus robot 3 at
  [`../docker/rmw_configuration/fast/lab2_mock-robot-3.xml`](../docker/rmw_configuration/fast/lab2_mock-robot-3.xml).
- **Cyclone DDS**: [`../docker/rmw_configuration/cyclone/`](../docker/rmw_configuration/cyclone/),
  stock settings, robot 3 already present.
- **Zenoh**: each robot runs its own local `rmw_zenohd` router that its nodes are clients of;
  its per-host config is generated under `docker/rmw_configuration/flat/zenoh/` when the stack
  comes up, with robot 3's lab2 peer profile at
  [`../docker/rmw_configuration/zenoh/lab2_mock-robot-3.json5`](../docker/rmw_configuration/zenoh/lab2_mock-robot-3.json5).
  Select it with the `zenoh` RMW argument (`up 3 zenoh`); the per-host router is the only
  Zenoh topology, so nothing else needs setting.

Three choices behind that setup:

- **The payload is JPEG.** A raw frame is 2.68 MB and fragments into roughly 1900 packets,
  so a single drop kills it and raw collapses at the slightest loss. At 41 KB there is
  enough headroom to watch it degrade instead.
- **The capture runs at the observer**, which is the vantage a network monitor has on
  the shared segment.
- **Delivery is counted as frames per second at the subscriber** rather than as RTPS
  fragments, because Zenoh does not use RTPS and only the first question can be asked of
  all three stacks.
</details>

<details>
<summary><b>Why a live fleet</b> and not a recorded bag</summary>

A bag records messages, not packets. None of the failures this lab is about leave a trace
in one: fragmentation, the discovery handshake, retransmits, QoS negotiation. A bag shows
that frames went missing, not why. Replaying it does not recover them, because `ros2 bag
play` republishes from a single node and the participant layout, addressing and MTU all
belong to the replay machine rather than the robot.

This fleet works the other way round. The content is synthetic, but the wire behaviour is
real: three robots in separate containers on their own interfaces, discovering each other
and fragmenting real camera frames under real netem shaping.

The same argument decides what to record if you get one pass at a broken robot. A pcap is
self-contained, so you can open it long after losing access to the machine. `ros2 topic hz`,
netdata and `htop` answer real questions too, but only while you are still connected.
</details>

## Exercises

### [1. Take a capture, and take it wrong](exercises/1_take_a_capture.md)

Your capture is full of RTPS (Real-Time Publish-Subscribe) packets and cannot name a single topic. Fix it without restarting.

### [2. The CLI cannot answer this](exercises/2_the_cli_cannot_answer.md)

Camera frames degrade, laser scans do not, and `ros2 topic hz` runs out of things to tell
you. Run it on Fast DDS and then Cyclone, which produce the same symptom for different
reasons.

### [3. Where the capture lies](exercises/3_how_the_capture_lies.md)

Predict what Zenoh does at both layers, then swap the fleet and find out how the capture
misleads you.

### [4. Puzzles](exercises/4_puzzles.md)

Ten recorded failures, easiest to hardest, answers included. No fleet needed, so these
finish at home.

## Going further

- Did you like the ROS 2 filters? Copy your own PCAP files to `lab2-on-the-wire/captures/` and view
  these within Webshark.
- [Examine the network traffic](https://docs.ros.org/en/jazzy/Tutorials/Advanced/Security/Examine-Traffic.html)
  from the ROS 2 docs to confirm that SROS2 encryption is on. It answers whether
  encryption works; Lab 2's methods show what enabling it costs in diagnosability.
- [beyond-the-wire](beyond-the-wire/README.md) runs the same pipeline through the full
  netem ladder and reads all three observability layers side by side. The results are
  committed, so it needs no setup, and it is where lab 3 comes from.
- [docker/webshark/README.md](../docker/webshark/README.md) covers the viewer, capturing on
  real hardware, and the capture internals.
- [docker/webshark/guide.html](../docker/webshark/guide.html) is the take-home reference:
  how to capture on a robot you have one pass at, and a symptom-by-symptom diagnosis
  section.
