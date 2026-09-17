# 1. Bring up your first robot

Bring up the smallest useful setup: the **observer plus one mock robot**.
Start the observer's Foxglove bridge and view the robot in **Lichtblick**.

Runs with any RMW. Start from the repository root.

> **What you will visualize:** one mock robot's sensor topics and TF tree, streamed from
> the observer to Lichtblick. Later exercises add robots, swap the RMW, and drive the
> robot; here you just confirm the pipeline end to end.

## Steps

1. Bring up the **flat** topology with a **single** robot, so you start exactly `observer`
   and `mock-robot-1`. The flat bus is the easiest place to start: every node shares one
   bridge with plain multicast discovery, so nothing has to be hand-wired.

   ```bash
   scripts/workshop -t flat up 1
   ```

   The robot launches the mock bringup on startup. The observer comes up **idle**, so it
   will not subscribe to anything until you start the Foxglove bridge.

2. Start the observer's Foxglove bridge:

   ```bash
   scripts/workshop observer bridge
   ```

   It publishes on host port `8765`. The command prints the exact connect URL.

3. Bring up Lichtblick (builds the image on first run):

   ```bash
   scripts/workshop lichtblick up
   ```

4. Open Lichtblick pre-connected to the observer's bridge:

   ```
   http://localhost:8080/?ds=foxglove-websocket&ds.url=ws://localhost:8765
   ```

   > Use the full URL. The plain `http://localhost:8080` does not select the data source.

5. Confirm the robot's graph appears. You should see topics under `/robot_1/...` (for
   example `/robot_1/scan` and `/robot_1/camera/image_raw`) and a TF tree rooted at the
   robot's frame. Add a **3D** panel for the TF tree and an **Image** panel on the camera
   topic to inspect the mock sensor data.

## Tear down

Leave everything up for [Exercise 2](2_meet_the_observer.md), or tear it down:

```bash
scripts/workshop lichtblick down
scripts/workshop -t flat down
```

**Next:** [2. Meet the observer](2_meet_the_observer.md)
