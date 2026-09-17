# urdf_raycast_sensors

Lightweight synthesis of range sensors by **analytic raycasting against URDF collision
geometry**. No physics engine and no renderer — just closed-form ray–primitive
intersection. The first deliverable is a single 2D `sensor_msgs/LaserScan` publisher
that raycasts against `box` collision links defined in a URDF.

Because the sensor pose is read from **tf2**, moving the sensor link in TF moves the
virtual laser — you can drive a link around a URDF "room" and watch the scan update.

## How it works

```
URDF (boxes) ──► urdf_geometry.boxes_from_urdf() ──► list[Box]  (oriented boxes in fixed_frame)
                                                        │
tf2: fixed_frame ─► sensor_frame ──► sensor pose ──►  raycast.cast()  ──► ranges ──► LaserScan
```

1. **Parse the world.** On startup the node reads a URDF (from the `robot_description`
   parameter, or by subscribing to the latched `/robot_description` topic published by
   `robot_state_publisher`). `urdf_geometry.boxes_from_urdf()` uses the standard ROS
   `urdf_parser_py` package to extract every link whose **collision** geometry is a
   `box`, composes each collision origin with the chain of joints back to the root
   (at their zero configuration), and returns a list of oriented boxes expressed in
   the `fixed_frame`. The sensor link itself is excluded.
2. **Track the sensor.** Each tick the node looks up the `fixed_frame -> sensor_frame`
   transform from tf2 to get the ray origin and orientation. If the transform is not
   yet available the tick is skipped (with a throttled warning).
3. **Cast rays.** A fan of unit ray directions in the sensor's XY plane is precomputed
   once from the scan parameters (`ray_directions_2d`), rotated into the fixed frame,
   and passed to `raycast.cast()`. For each box the rays are transformed into the
   box's local frame and intersected with the **slab method**; the nearest positive
   hit across all boxes becomes the range, clamped to `[range_min, range_max]`.
4. **Publish.** The ranges are packed into a `sensor_msgs/LaserScan` stamped with the
   current time and `frame_id = sensor_frame`, and published on the scan topic.

The math core (`raycast.py`) and the URDF parsing (`urdf_geometry.py`) are pure Python
and unit-tested without ROS.

## Package contents

| File | Purpose |
|------|---------|
| `urdf_raycast_sensors/raycast.py` | Analytic ray–box (slab) intersection; `Box`, `intersect_box`, `cast`, `ray_directions_2d`. Pure math, no ROS. |
| `urdf_raycast_sensors/urdf_geometry.py` | Parse URDF box collisions into oriented `Box` objects via `urdf_parser_py`. |
| `urdf_raycast_sensors/laserscan_node.py` | The `LaserScanNode` — tf2 pose tracking, raycasting, `LaserScan` publishing. |
| `urdf_raycast_sensors/demo_mover.py` | Demo `DemoMover` node that broadcasts a moving `world -> laser` transform (circle). |
| `urdf_raycast_sensors/pose_broadcaster.py` | Interactive `PoseBroadcaster` node that broadcasts `world -> laser` from live `x`/`y`/`z`/`yaw` parameters. |
| `launch/laserscan.launch.py` | Brings up `robot_state_publisher`, a mover, the laserscan node, and (optionally) `foxglove_bridge`. |
| `urdf/demo_walls.urdf.xacro` | Sample room: four box walls + one rotated interior obstacle. |
| `test/` | Unit tests for the math core and URDF parsing. |

## Node: `laserscan_node`

Publishes `sensor_msgs/LaserScan` on the scan topic (default `scan`).

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `fixed_frame` | string | `world` | Frame the URDF obstacles are resolved in. |
| `sensor_frame` | string | `laser` | TF frame of the virtual laser (the moving link). |
| `scan_topic` | string | `scan` | Output `LaserScan` topic. |
| `angle_min` | double | `-π` | Start angle of the scan (rad). |
| `angle_max` | double | `π` | End angle of the scan (rad). |
| `angle_increment` | double | `π/360` | Angular resolution (rad ≈ 0.5°). |
| `range_min` | double | `0.05` | Minimum valid range (m); closer hits are rejected. |
| `range_max` | double | `30.0` | Maximum valid range (m); farther hits are misses. |
| `rate_hz` | double | `10.0` | Publish rate (Hz). |
| `robot_description` | string | `""` | URDF as a string. If empty, the node subscribes to `/robot_description`. |
| `range_on_miss` | string | `max` | Value for missed rays: `max` (report `range_max`) or `inf`. |

## Using the launch file

The demo launch runs the whole pipeline: it expands the demo URDF, publishes the wall
TF and `/robot_description` via `robot_state_publisher`, drives the sensor with the
selected mover, starts the laserscan node, and (by default) a `foxglove_bridge` so the
`/scan` topic and TF tree are visible in Lichtblick.

```bash
# From a colcon workspace whose src/ contains this package:
colcon build --symlink-install --packages-select urdf_raycast_sensors
source install/setup.bash

ros2 launch urdf_raycast_sensors laserscan.launch.py
```

### Launch arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `urdf` | `urdf/demo_walls.urdf.xacro` | Path to the URDF/xacro obstacle world. |
| `fixed_frame` | `world` | Frame the URDF obstacles are resolved in. |
| `sensor_frame` | `laser` | TF frame of the virtual laser (moved by the mover). |
| `mover` | `circle` | Sensor mover: `circle` (auto), `manual` (live params), or `none` (supply your own TF). |
| `bridge` | `true` | Run `foxglove_bridge` (port 8765) so `/scan` + TF show in Lichtblick. |
| `x`, `y`, `z`, `yaw` | `0`, `0`, `0.5`, `0` | Initial sensor pose when `mover:=manual`. |

### Interactive testing (manual mover)

Drive the sensor by hand and watch `/scan` change as the sensor frame moves:

```bash
ros2 launch urdf_raycast_sensors laserscan.launch.py mover:=manual

# In another shell, move the sensor live — the transform and /scan update immediately:
ros2 param set /urdf_raycast_pose_broadcaster x 3.0
ros2 param set /urdf_raycast_pose_broadcaster y 1.0
ros2 param set /urdf_raycast_pose_broadcaster yaw 1.57
```

Visualize in Lichtblick (already served on <http://localhost:8080>): add a **Foxglove
WebSocket** connection to `ws://localhost:8765`, then open a **3D** panel to see the
TF tree + walls and a **Plot**/**Raw Messages** panel on `/scan`.

Examples with your own world / other movers:

```bash
# Auto-circling sensor (default):
ros2 launch urdf_raycast_sensors laserscan.launch.py mover:=circle

# Your own obstacle world, supply the sensor TF yourself:
ros2 launch urdf_raycast_sensors laserscan.launch.py \
    urdf:=/path/to/my_world.urdf.xacro mover:=none
ros2 run tf2_ros static_transform_publisher --x 0 --y 0 --z 0.5 \
    --frame-id world --child-frame-id laser
```

Inspect the output from the CLI:

```bash
ros2 topic echo /scan --once
ros2 topic hz /scan
```

## Running the tests

```bash
colcon build --symlink-install --packages-select urdf_raycast_sensors
source install/setup.bash
python3 -m pytest src/urdf_raycast_sensors/test -v
```

`test/test_raycast.py` needs only Python + numpy; `test/test_urdf_geometry.py`
additionally requires `urdf_parser_py` (provided by the `urdfdom_py` package).

## Containerized build + test + run

`docker/raycast_test.yml` reuses the same `ubuntu-headless` image as `mock-robot-1`
and, in one service, builds the package, runs the unit tests, and launches the nodes:

```bash
# Terminal 1 — Lichtblick web UI on http://localhost:8080
docker compose -f docker/lichtblick.yml --profile lichtblick up

# Terminal 2 — build + test + launch (manual mover + foxglove bridge on 8765)
docker compose -f docker/raycast_test.yml --profile raycast up --build
```

Then in Lichtblick add a Foxglove WebSocket connection to `ws://localhost:8765`, and
move the sensor live from a third shell:

```bash
docker exec -it raycast-test bash -lc \
  'source /ws/install/setup.bash && ros2 param set /urdf_raycast_pose_broadcaster x 3.0'
```

## Dependencies

- `rclpy`, `tf2_ros`, `sensor_msgs`, `geometry_msgs`
- `urdfdom_py` (provides the `urdf_parser_py` Python module)
- `robot_state_publisher`, `xacro` (for the demo launch)
- `foxglove_bridge` (for visualization in Lichtblick)
- `python3-numpy`

## Roadmap

The package is named and structured to grow along two axes without renaming:

- **Output types**: single 2D `LaserScan` (now) → multi-scan stack → `PointCloud2`.
- **Geometry types**: `BOX` (now) → `CYLINDER`, `SPHERE` → `MESH` links whose
  collision is a supported primitive. Only collision geometry is raycast; visual
  meshes are ignored.
