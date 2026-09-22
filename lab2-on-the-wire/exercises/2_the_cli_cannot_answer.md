# 2. The CLI cannot answer this

The camera topic degrades under packet loss and the scan topic does not. The ROS 2 CLI will
show you that much and then run out of answers, so the rest of this exercise is on the wire.

Runs on Fast DDS first, then the same thing on Cyclone.

## Steps

1. With the fleet from [exercise 1](1_take_a_capture.md) still up, shape every robot's
   link:

   ```bash
   scripts/workshop -t flat netem poor
   ```

   `poor` is 20 ms of delay and 0.6% bursty loss, both directions. `scripts/workshop -t flat netem list` shows the
   rest of the profile options.

2. Open a shell on the observer and measure both topics:

   ```bash
   scripts/workshop shell observer

   # Within the container:
   ros2 topic hz /robot_1/sensor_0/camera/image_comp/compressed
   ```

   Press **Ctrl-C** after the camera measurement settles, then run the scan measurement:

   ```bash
   ros2 topic hz /robot_1/scan
   ```

   The camera collapses into the low single digits, somewhere between 2 and 4 Hz, and
   swings from second to second. The scan holds near 10 Hz on the same shaped link, steady.

   Your exact figures will not match anyone else's, because `poor` drops packets randomly in bursts.
   Read the gap between the two topics rather than either number on its own.

3. Write down why one topic cares about 0.6% loss and the other does not before you go on.

4. Use the CLI to try to explain it. Check the QoS on both ends:

   ```bash
   ros2 daemon stop
   ros2 topic info -v /robot_1/sensor_0/camera/image_comp/compressed
   ```

   Stop the daemon first or this can answer from a cache built before your `topic hz`
   subscribers existed, and report zero publishers on a topic that plainly has one.

   You get Reliability, Durability, Lifespan, Deadline and Liveliness for every endpoint.
   Publisher and subscriber both read `BEST_EFFORT`. They match, so QoS negotiation is not
   the fault, and that is the end of what the CLI knows.

> [!IMPORTANT]
> `ros2 topic list` on its own puts nothing on the network. The CLI runs a background
> daemon that caches the graph and answers from memory. Measured on this fleet, plain
> `ros2 topic list` produced 462 participant announcements and **zero** endpoint
> announcements, while `ros2 topic list --no-daemon` produced 559 and **1515**. If you are
> trying to make discovery appear in a capture, use `--no-daemon`, run `ros2 daemon stop`
> first, or start a real node.

5. Go to the wire. In the viewer, open the newest window and click **Fragments**.

6. It reads `0 of N displayed`, in red, and this time that is not a mistake. Fast DDS hands
   the whole 41 KB JPEG to the kernel as one datagram and lets IP split it. There is no
   RTPS-level fragmentation to find.

7. Predict what Cyclone will do, then swap the whole fleet under it:

   ```bash
   scripts/workshop observer capture stop
   scripts/workshop -t flat down
   scripts/workshop -t flat up 3 cyclone
   scripts/workshop webshark up
   scripts/workshop observer capture start 3
   scripts/workshop -t flat netem poor
   ```

8. Re-run step 2's `ros2 topic hz`. The camera holds far steadier and lands well above what
   Fast DDS managed on the same profile. So the CLI can tell you Cyclone does better here.
   It cannot tell you what Cyclone is doing differently, which is the question you actually
   have.

9. Open the newest window and click **Fragments** again. Thousands of frames, against zero
   a moment ago, on a fleet that is otherwise identical.

<details style="border: 2px solid #333; padding: 5px">
<summary>Answer: what the two stacks are actually doing</summary>

Both facts come from where the 41 KB JPEG gets split.

Fast DDS sends the sample as one large UDP datagram and lets the kernel fragment it into
roughly 28 IP fragments. The RTPS layer never sees a fragment, so `rtps.sm.id == 0x16`
matches nothing. Lose any one of those 28 and IP reassembly fails, so the whole sample is
gone.

Cyclone splits the sample itself, into RTPS `DATA_FRAG` submessages, which is what the
Webshark filter counts. A drop still costs the whole frame under best-effort, but the RTPS layer
can see exactly which fragment went missing.

Measured on this fleet under `poor`, camera delivery at a sustained subscriber over five
20-second windows, against `DATA_FRAG` in one window:

| | camera at the app | RTPS `DATA_FRAG` |
|---|---:|---:|
| Fast DDS | 3.0 to 3.7 Hz | **0** |
| Cyclone | 8.1 Hz | 1524 |
| no impairment | 10.0 Hz | |

The scan survives on both because a `LaserScan` fits in one datagram. It is not more
reliable, it is just small enough that no fragment can go missing.

Fast DDS is also the unsteady one. Its windows ran from 0.8 to 5.4 Hz while Cyclone stayed
between 7.9 and 8.7, and that follows from the same mechanism. When a frame costs 28
fragments and one loss discards all of them, a single burst takes out several frames
at once.

What the CLI cannot reach is the reason. `ros2 topic hz` reports the same kind of number
for both stacks and offers nothing to distinguish 0 from 1524, so it can rank them without
ever showing that they disagree about where a large message gets split.

Do not read this as "Cyclone avoids IP fragmentation". It does not. The same Cyclone
window still carries tens of thousands of IP fragments, because `DATA_FRAG` submessages
travel inside IP-fragmented datagrams themselves. `rtps.sm.id == 0x16` is the only filter
that separates the stacks cleanly, which is why the preset is scoped to it.
</details>

## Troubleshooting

**`0 of N displayed` on Fragments, and you are on Cyclone.** Check you are on the newest
window and that `scripts/workshop -t flat netem poor` reported all three robots. An unshaped Cyclone fleet
still fragments, but far less.

**`ros2 topic hz` prints nothing at all.** The compressed topic is published lazily: the
republisher launches with each robot but only wakes once something subscribes. `ros2 topic
hz` is that subscriber, so it wakes it — if it still prints nothing, confirm the fleet is up
and that you named the compressed topic, not `sensor_0/camera/image_raw`.

**`ros2: command not found`.** Use `docker exec -it observer bash`. A non-interactive
shell such as `docker exec observer bash -lc` does not read `.bashrc`, so ROS is not
sourced.

**No fleet at all.** This is the one exercise that works entirely from a recording. Open
`fragment-loss.pcap.gz`, a Cyclone capture with 1505 `DATA_FRAG` submessages, alongside
`healthy-fastdds.pcap.gz`, which has zero.

If the viewer from `scripts/workshop webshark up` is still running, it serves the fleet's
capture directory:

```bash
cp docker/webshark/fixtures/*.pcap.gz lab2-on-the-wire/captures/
```

If nothing is running, start the standalone viewer, which serves `docker/webshark/captures`:

```bash
mkdir -p docker/webshark/captures                  # first run only, see docker/webshark/webshark.yml for why
cp docker/webshark/fixtures/*.pcap.gz docker/webshark/captures/
docker compose -f docker/webshark/webshark.yml up -d
```

Leave the fleet running. [Exercise 3](3_how_the_capture_lies.md) starts with a
prediction.
