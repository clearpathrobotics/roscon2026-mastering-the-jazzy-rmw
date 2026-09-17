# 5. After the workshop

You now know the three primitives and the one command that drives them. These are
self-serve — no one else needs to be in the room. Each builds on the same
`scripts/workshop` verbs you have already used.

## Drive a robot with the joystick panel

Lichtblick ships with the teleop extensions pre-installed. Bring the fleet up, open the
operator view, and add the **Joystick** / **Joy** panel to drive a robot's `cmd_vel`. Watch
its TF and camera update as it moves.

```bash
scripts/workshop -t flat up 1
scripts/workshop observer bridge
scripts/workshop lichtblick up
# http://localhost:8080/?ds=foxglove-websocket&ds.url=ws://localhost:8765
```

## Try different robot models

Each robot can be a different platform. A single `--model` value applies to every robot; a
comma-separated list is assigned to robots 1..N in order and cycles when shorter than N.

```bash
scripts/workshop --model r100 -t flat up 3                 # all three are r100
scripts/workshop --model a300,r100,j100 -t flat up 3       # one of each
```

## Edit the workspace and rebuild in-container

The robot and observer mount `mock_robot_ws/src` read-only. To run your own edits to the
mock nodes, build the editable workspace in the container at startup with `--build`:

```bash
scripts/workshop --build -t flat up 1
```

## Compare the star against the flat bus

Bring the flat bus up at larger counts and switch RMWs between runs, then contrast it with
the hand-configured star from [Exercise 3](3_add_robots_and_watch_discovery.md). This is the
same trade-off Lab 3 stress-tests and Lab 4 turns into a decision matrix — try to predict
which middleware will hurt first as N grows.

```bash
scripts/workshop -t flat up 12 zenoh
scripts/workshop observer bridge
```

## Read the generated configs

Every `workshop up` regenerates `docker/rmw_configuration/<topology>/`. Diff the flat
topology's plain-multicast configs against the star's pinned ones to see how interface
pinning and peer lists differ:

```bash
ls docker/rmw_configuration/flat/cyclone
ls docker/rmw_configuration/star/cyclone
```

---

**Next:** [Lab 2 — ROS 2 on the Wire](../../lab2-on-the-wire/README.md).
