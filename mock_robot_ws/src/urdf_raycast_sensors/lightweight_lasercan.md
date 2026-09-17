# Implementation Plan — `urdf_raycast_sensors`

A lightweight ROS 2 package that synthesizes range sensors by **analytic raycasting
against URDF collision geometry**. No physics engine, no renderer — just closed-form
ray–primitive intersection.

The first deliverable is a single 2D `sensor_msgs/LaserScan` publisher: walls are
defined as URDF links with primitive collision geometry, a sensor link is moved around
(via TF), and range samples are computed analytically at specified angles. The package
is named and structured so it can grow to multi-scan → `PointCloud2` output and to all
primitive collision types without renaming.

## Scope roadmap

Designed to grow along two axes without churn:

- **Output types**: single 2D `LaserScan` (first) → multi-scan stack → `PointCloud2`.
- **Geometry types**: `BOX` (first) → `CYLINDER`, `SPHERE` → `MESH` links whose
  **collision** is a supported primitive (box/cylinder/sphere). Visual meshes are
  ignored; only collision geometry is raycast.

## Goals

- Parse a URDF and extract every link with supported **primitive collision geometry**
  (box first; cylinder/sphere later) with size + pose.
- Track a configurable **sensor link** pose from **tf2**, so moving the link in TF
  moves the virtual sensor.
- Compute ranges via **analytic ray–primitive intersection** for each sample angle.
- Publish a valid `sensor_msgs/LaserScan` at a configurable rate (first output type).
- Zero simulator dependencies (only `rclpy`, `tf2_ros`, `urdf_parser_py`, `numpy`).

## Non-goals (keep it lightweight)

- No noise modelling, multi-echo, or intensity realism (optional flat intensity only).
- Non-box primitives (cylinder/sphere) and mesh-collision support are **planned but
  staged** — box only in the first version.
- No 3D full-sphere scanning in v1 — planar 2D scan in the sensor frame (z-plane
  slice). Multi-scan/pointcloud comes later.

## Package layout (ament_python, matches sibling packages)

```
urdf_raycast_sensors/
  package.xml
  setup.py
  setup.cfg
  resource/urdf_raycast_sensors
  urdf_raycast_sensors/
    __init__.py
    laserscan_node.py          # ROS node: single 2D scan (params, tf2, timer, publisher)
    pointcloud_node.py         # (future) multi-scan stacker → PointCloud2
    raycast.py                 # pure-math ray–primitive intersection (unit-testable)
                               #   ray_box (v1), ray_cylinder / ray_sphere (later)
    urdf_geometry.py           # URDF parsing → list of oriented primitives
                               #   (box v1; cylinder/sphere + mesh-with-primitive-collision later)
  launch/
    laserscan.launch.py
  urdf/
    demo_walls.urdf.xacro      # sample world of primitive-collision "walls" + a sensor link
  test/
    test_raycast.py            # unit tests for the math (no ROS needed)
```

## Dependencies

- `rclpy`
- `tf2_ros` (sensor link pose lookup)
- `sensor_msgs` (`LaserScan`; `PointCloud2` later)
- `geometry_msgs` / `tf2_geometry_msgs` (pose math where useful)
- `urdf_parser_py` (parse URDF collision primitives + origins)
- `numpy` (vectorized ray math)

## Core math — analytic ray–primitive intersection

Each obstacle is an **oriented primitive**: center pose `T_world_prim` (from the URDF
link/collision origin, resolved through the kinematic tree) and shape parameters. For a
**box** (v1) the parameters are half-extents `(hx, hy, hz)` from `<box size="x y z">`.
Cylinder (`radius`, `length`) and sphere (`radius`) follow the same
"transform ray into local frame, intersect analytically" pattern.

For each sample ray:

1. Ray origin `o` and direction `d` are known in the **world/fixed frame** from the
   sensor link pose (tf2) plus the sample angle.
2. Transform the ray into each primitive's **local frame**: `o' = R^T (o - c)`,
   `d' = R^T d`. In local frame the primitive is axis-aligned / canonical.
3. Intersect analytically in local frame:
   - **Box** — **slab method**: for each axis compute `t1 = (-h - o')/d'`,
     `t2 = (+h - o')/d'`; track `t_near = max(min(t1,t2))`, `t_far = min(max(t1,t2))`.
     Hit iff `t_near <= t_far` and `t_far >= 0`; range candidate is `t_near`
     (or `t_far` if origin inside).
   - **Cylinder / sphere** (later) — quadratic in `t`, take smallest positive root
     within caps/extent.
4. The reported range for the ray is the **minimum positive `t`** across all
   primitives, clamped to `[range_min, range_max]`; misses report `range_max`
   (or `inf`).

Handle `d' == 0` (ray parallel to a slab) with the standard divide-by-zero guard.
Vectorize across rays and/or primitives with numpy.

For a **2D planar scan**, take the sensor z-plane: rays lie in the sensor XY plane at
angles `angle_min + i*angle_increment`; only intersect primitives whose z-extent
contains the sensor z (or ignore z for a pure 2D projection — a parameter decides).

## ROS node behaviour (`laserscan_node.py`)

Parameters (declared with defaults):

| Param | Type | Default | Meaning |
|-------|------|---------|---------|
| `fixed_frame` | string | `world` | Frame the primitives/URDF are resolved in |
| `sensor_frame` | string | `laser` | TF frame of the virtual sensor (the moving link) |
| `scan_topic` | string | `scan` | Output `LaserScan` topic |
| `angle_min` | double | `-pi` | rad |
| `angle_max` | double | `pi` | rad |
| `angle_increment` | double | `pi/360` | rad (0.5°) |
| `range_min` | double | `0.05` | m |
| `range_max` | double | `30.0` | m |
| `rate_hz` | double | `10.0` | publish rate |
| `urdf` / `robot_description` | string | — | URDF source (param or topic) |
| `use_z_slab` | bool | `true` | respect primitive z-extent vs. pure 2D projection |
| `range_on_miss` | string | `max` | `max` or `inf` |

Flow:

1. On startup, read the URDF (from a `robot_description` parameter or the
   `/robot_description` topic) and build the list of oriented primitives via
   `urdf_geometry.py`. Resolve each primitive link's pose in `fixed_frame` (static
   parts via URDF tree; dynamic parts can be refreshed from TF if a link is movable).
2. Create a `tf2_ros.Buffer` + `TransformListener`.
3. On each timer tick (`rate_hz`):
   - Look up `fixed_frame -> sensor_frame` transform (skip tick + warn on failure).
   - Refresh any dynamic primitive poses from TF if configured.
   - Build the ray set from scan params; run `raycast` intersection.
   - Populate and publish `LaserScan` (stamp = now, `frame_id = sensor_frame`).

## Sample world (`urdf/demo_walls.urdf.xacro`)

- A `world` root link.
- Four `box`-collision links forming a rectangular room (thin long boxes as walls).
- One or two interior obstacles (box collision in v1; cylinder/sphere later).
- A `laser` link (the sensor) attached via a joint so it can be moved (e.g. a floating
  joint driven by a small TF broadcaster, or repositioned in a demo script).

## Launch (`launch/laserscan.launch.py`)

- `robot_state_publisher` with the demo URDF (publishes static primitive TF +
  robot_description).
- Optional small **TF broadcaster** to move the `laser` link in a path (demonstrates
  "move a link around").
- The `laserscan_node` with default params.
- Optional RViz config showing the URDF + `LaserScan`.

## Testing

- `test/test_raycast.py`: pure unit tests for `raycast.py` (no ROS):
  - ray hitting an axis-aligned box straight on → known range.
  - ray missing the box → miss.
  - ray parallel to a slab → correct (no false hit).
  - rotated (oriented) box → correct range after rotation.
  - origin inside box → uses `t_far`.
  - multiple primitives → nearest hit wins.
  - (later) cylinder/sphere hit + miss cases.

## Milestones

1. **Math core** — `raycast.py` ray–box + unit tests (no ROS). Verifiable standalone.
2. **URDF parsing** — `urdf_geometry.py` extracts box primitives (size + resolved pose).
3. **Node** — params, tf2 lookup, timer, `LaserScan` publishing.
4. **Demo world + launch** — `demo_walls.urdf.xacro` + launch file + optional mover.
5. **Polish** — RViz config, README, param documentation.
6. **(Future) More primitives** — cylinder/sphere in `raycast.py` + `urdf_geometry.py`,
   plus mesh links whose collision is a supported primitive.
7. **(Future) PointCloud2** — `pointcloud_node.py` stacks multiple scan rings into a
   `PointCloud2`.

## Open questions

- Should movable primitive links be refreshed from TF every tick, or are all obstacles
  static and only the sensor moves? (Default: sensor moves; obstacles static —
  simplest.)
- 2D-only (z ignored) vs. z-slab respected as default? (Plan defaults to z-slab on.)
- URDF source: `robot_description` topic (matches `robot_state_publisher`) vs. file
  path parameter? (Plan supports the topic; file path optional.)
