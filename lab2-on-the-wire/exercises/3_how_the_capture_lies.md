# 3. How the capture lies

Exercises 1 and 2 taught you to trust the wire over the CLI. This one shows you the case
where the wire is the thing that is wrong, and how to tell.

Runs on Zenoh.

## Steps

1. Before you swap anything, commit to two predictions in writing. Under the same `poor`
   profile, compared to the DDS stacks you just measured:

   - **At the application**, will Zenoh deliver more camera frames per second, fewer, or
     about the same?
   - **On the wire**, will the capture look cleaner or worse?

   Zenoh carries ROS 2 traffic over TCP sessions rather than UDP multicast. Both answers
   follow from that.

2. Swap the fleet:

   ```bash
   scripts/workshop observer capture stop
   scripts/workshop -t flat down
   scripts/workshop -t flat up 3 zenoh
   scripts/workshop webshark up
   scripts/workshop observer capture start 3
   scripts/workshop -t flat netem poor
   ```

3. Check your first prediction:

   ```bash
   docker exec -it observer bash
   ros2 topic hz /robot_1/sensor_0/camera/image_comp/compressed
   ```

   Compare it against what the same command gave you for Fast DDS and Cyclone in
   [exercise 2](2_the_cli_cannot_answer.md), not against the table below. That table comes
from the sustained subscriber `scripts/workshop observer capture start` already runs, which reads higher than
   `ros2 topic hz` because `topic hz` joins a second subscriber of its own. The ranking of
   the three stacks is the same either way, and the ranking is the answer.

4. Check your second. Open the newest window in the viewer and click **SEDP**, then
   **Fragments**. Both read `0 of N displayed`. Every filter you learned in the last two
   exercises is now useless.

5. Click **Zenoh Declare**. Also zero, on the newest window. Scroll to the oldest window
   and click it again.

6. Find the damage. In the filter box, type:

   ```
   tcp.analysis.retransmission
   ```

   Then `tcp.analysis.out_of_order`.

<details style="border: 2px solid #333; padding: 5px">
<summary>Answer: both predictions are wrong, in opposite directions</summary>

**The application does better than either DDS stack, not worse.** Measured under an
identical `poor` profile on the same fleet, camera delivery at a sustained subscriber over
five 20-second windows:

| stack | camera at the app |
|---|---:|
| Fast DDS | 3.0 to 3.7 Hz |
| Cyclone | 8.1 Hz |
| Zenoh | **9.2 Hz** |
| no impairment | 10.0 Hz |

Zenoh loses almost nothing. The ROS QoS is still best-effort, but TCP does not care what
the ROS layer asked for: a dropped segment is retransmitted because that is what the
transport does. The DDS stacks honour best-effort literally and let the frame die.

**The wire looks worse than reality, not better.** The same 30-second window:

| | |
|---|---:|
| total packets | 26313 |
| Zenoh frames | 15467 |
| TCP retransmissions | 2124 |
| TCP out-of-order | 2482 |
| RTPS frames | **0** |

So the capture is full of alarming repair traffic during a run that delivered nearly every
frame, and the stack that looks worst on the wire is the one that performed best. Read the
retransmit count alone and you would report a failing link.

Further down the ladder this stops being cosmetic. `beyond-the-wire` reruns the whole sweep,
and in the `bad` band offline analysis recovers **0.0** camera frames per second from the
Zenoh capture while the subscriber received 13.4 and lost nothing. The dissector lost
message-boundary sync under 11k out-of-order and 17k retransmitted segments, so it could no
longer tell where one Zenoh message ended and the next began. The `drain` band proves that
is the analysis rather than the link, because clearing the shaping snaps both layers back
to 29.9 together.

So the rule from exercises 1 and 2 needs a caveat. On a UDP stack, offline reassembly has
unlimited time and memory, so tshark's count is an upper bound on what any receiver could
have got. On TCP it is a lower bound, because reconstructing an ordered stream from a
retransmit-heavy capture is exactly what loss breaks.

Step 5 repeats exercise 1 on a different protocol. Zenoh's `Declare` frames are its version
of SEDP and they go quiet the same way, a few hundred in the first window of the run and
zero in every one after it, so the fix from exercise 1 is the fix here too.
</details>

> [!TIP]
> Say the limit out loud when you present a capture. "Zero frames recovered" from a
> TCP-based transport under loss is a statement about the analysis, not about the robot.

## Troubleshooting

**Every preset is empty, including Zenoh Declare, on every window.** Check the routers
came up: `docker exec observer bash -ic 'ros2 node list'` should show the fleet, and
each robot runs its own `rmw_zenohd` under the default `perhost` topology.

**The capture goes quiet for a few seconds near the start.** That is expected. `scripts/workshop
observer capture start` bounces the observer's router so everything under it re-declares into the
capture, and the restart takes a moment to settle. The `Declare` burst follows.

**No fleet.** `healthy-zenoh.pcap.gz` shows a Zenoh session declaring key expressions
normally, which covers step 5. It cannot cover steps 3, 4 and 6, because it was recorded
on a clean link and there is no impairment in it. For those, read the Zenoh section of
[beyond-the-wire](../beyond-the-wire/README.md), where the whole ladder is plotted and
committed.

Next: [the puzzles](4_puzzles.md), which need no fleet. Tear this one down first:

```bash
scripts/workshop observer capture stop
scripts/workshop -t flat down
```

A full pass through this lab leaves a gigabyte or more of `.pcap` in
`lab2-on-the-wire/captures/`. To reclaim that space before the next lab, clear the
captures this harness recorded:

```bash
scripts/workshop observer capture clear
```

It asks before deleting and removes only the harness's own `live_*`/`stream_*` captures,
so any PCAP you copied in yourself stays put.
