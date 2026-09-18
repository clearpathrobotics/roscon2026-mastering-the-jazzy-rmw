# 4. Select and configure the RMW

The whole workshop is about middleware choice. Here you flip the fleet between **Cyclone
DDS**, **Fast DDS**, and **Zenoh** with one argument, inspect the per-node configs the
harness generates, and see that the RMW binds at node startup — so switching it means
recreating the fleet.

Runs on the flat topology. Start from the repository root.

> **What you will visualize:** the same graph, unchanged, carried by three different
> middlewares — and the generated configuration files that put every node on the shared bus.
> Labs 2–4 then measure how these three behave on the wire, under stress, and side by side.

## Steps

1. Bring the fleet up on the default RMW (Cyclone DDS) and confirm it in the graph:

   ```bash
   cd "$(git rev-parse --show-toplevel)"
   scripts/workshop -t flat up 3
   scripts/workshop observer bridge
   ```

   Check the active RMW from the observer:

   ```bash
   scripts/workshop shell observer
   echo "$RMW_IMPLEMENTATION"              # rmw_cyclonedds_cpp
   exit
   ```

2. Inspect the generated per-node config. `workshop up` writes one file per node, per
   vendor, under `docker/rmw_configuration/flat/`:

   ```bash
   ls docker/rmw_configuration/flat/cyclone
   cat docker/rmw_configuration/flat/cyclone/mock-robot.xml
   ```

   Note how the file puts the robot on the shared bus with plain multicast discovery — this
   is what makes the flat bus plug-and-play.

3. Switch the whole fleet to **Fast DDS**. The third argument to `up` sets
   `RMW_IMPLEMENTATION` for every robot and the observer, and recreates the stack:

   ```bash
   scripts/workshop -t flat up 3 fastdds
   scripts/workshop observer bridge
   ```

   Look at the matching config and confirm the graph is identical, just carried by a
   different middleware:

   ```bash
   ls docker/rmw_configuration/flat/fast
   ```

4. Switch the fleet to **Zenoh** and inspect its config, which is a router-based session
   config rather than a DDS profile:

   ```bash
   scripts/workshop -t flat up 3 zenoh
   scripts/workshop observer bridge
   cat docker/rmw_configuration/flat/zenoh/mock-robot.json5
   ```

5. Refresh Lichtblick after each switch. The operator view looks the same every time — the
   RMW is invisible at the application layer. What differs is discovery and transport
   underneath, which is exactly what the later labs bring to the surface.

<details>
<summary>Answer: why switching the RMW recreates the fleet</summary>

`RMW_IMPLEMENTATION` and every QoS setting bind when a node creates its participant and
endpoints; ROS 2 has no API to renegotiate them on a running node. So there is no live
"flip the RMW" — `workshop up <N> <rmw>` regenerates the per-node configs for that vendor
and recreates the containers. The application graph is unchanged across all three, which is
the point: the RMW is an implementation detail the app does not see, until it changes
discovery cost, fragmentation, retransmission, or freshness — the behaviours Labs 2, 3, and
4 measure. If you want a mixed setup, the observer can be pointed at a different RMW
independently through `OBSERVER_RMW_IMPLEMENTATION` and its `OBSERVER_*_URI` config vars.

</details>

## Tear down

```bash
scripts/workshop -t flat down
```

**Next:** [5. After the workshop](5_after_the_workshop.md)
