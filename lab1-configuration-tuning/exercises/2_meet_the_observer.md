# 2. Meet the observer

The **observer** is the operator-side vantage. In this exercise you open a shell on it and
use the `ros2` CLI to see the graph from there.

Runs with any RMW. Continue from [Exercise 1](1_bring_up_your_first_robot.md), or bring the
fleet up first with `scripts/workshop -t flat up`.

> **What you will visualize:** the ROS graph as text — topics, nodes, and TF — from the
> observer. On the flat bus every node hears every other node, so both the observer and the
> robots see the whole graph

## Steps

1. Bring up the default flat fleet (three robots) if it is not already running, and start
   the bridge:

   ```bash
   scripts/workshop -t flat up
   scripts/workshop observer bridge
   ```

2. Open an interactive shell on the observer:

   ```bash
   scripts/workshop shell observer
   ```

3. Inside the observer, source ROS and the workspace, then list the graph:

   ```bash
   source /opt/ros/jazzy/setup.bash
   source /mock_robot_ws/install/setup.bash
   ros2 topic list
   ros2 node list
   ```

   You should see topics namespaced per robot — `/robot_1/...`, `/robot_2/...`,
   `/robot_3/...` — because on the flat bus the observer discovers every robot.

4. Check a single topic is actually flowing, and inspect the TF the operator view draws:

   ```bash
   ros2 topic hz /robot_1/scan
   ros2 topic list | grep tf
   ```

   Use Ctrl-C to stop `hz`.

5. Now look at the same graph from a **robot**. Open a shell on one and list its graph:

   ```bash
   exit                                   # leave the observer shell
   scripts/workshop shell mock-robot-1
   source /opt/ros/jazzy/setup.bash
   ros2 topic list
   ```

   On the flat bus `mock-robot-1` sees **all** the robots' topics, not just its own — every
   node shares one broadcast domain, so discovery reaches everyone. Exercise 3 switches to
   the star, where each robot is isolated and only the observer keeps this full view.


**Next:** [3. Configure the RMW for the star](3_add_robots_and_watch_discovery.md)
