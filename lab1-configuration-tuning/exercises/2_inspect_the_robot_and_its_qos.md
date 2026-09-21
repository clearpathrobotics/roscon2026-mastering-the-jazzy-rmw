# 2. Inspect the robot and its QoS

Now, we will go **inside a robot** and read its nodes using the ROS CLI.

In this exercise you open a shell on the robot container, list its nodes and topics, and
then use `ros2 topic info -v` to read the **QoS** each publisher offers.

> **What you will visualize:** the robot's nodes and topics as text, and the per-topic QoS
> profiles. You will contrast a **latched** config topic, a **reliable** state topic, and a
> **sensor** stream — and reason about which QoS is right on-board versus off-board.

## Steps

1. Bring up the flat fleet if it is not already running, then open a shell **on the robot**
   with the `shell` verb:

   ```bash
   MOCK_RUN_PILOT=false scripts/workshop -t flat up 1
   scripts/workshop shell mock-robot-1
   ```

2. Inside the robot, list the robot's **nodes**:

   ```bash
   ros2 node list
   ```

   You should see the robot's nodes: the state publishers, the localization/EKF node, the
   controllers, and the mock sensor drivers.

3. List the robot's **topics**:

   ```bash
   ros2 topic list
   ```

   Look for the ones namespaced under `/robot_1/...` (for example `/robot_1/scan`,
   `/robot_1/joint_states`, `/robot_1/sensor_0/camera/image_raw`, `/robot_1/robot_description`)
   plus the shared `/tf` and `/tf_static`.

4. Now read the **QoS** of the important topics with `-v` (verbose), which prints the
   offered/requested QoS for every publisher and subscriber:

   ```bash
   ros2 topic info -v /robot_1/robot_description
   ros2 topic info -v /tf_static
   ros2 topic info -v /robot_1/joint_states
   ros2 topic info -v /robot_1/sensor_0/camera/image_raw
   ```

### 4a. Latched / transient-local: `/tf_static` and `/robot_description`

Look at `/tf_static` and `/robot_description` first.

> **What you expect to see:** `RELIABLE`, `KEEP_LAST` with depth `1`, and durability
> `TRANSIENT_LOCAL`. These are published **once** (or rarely) and never again. The static
> transforms and the robot model don't change while the robot runs.

**What does `TRANSIENT_LOCAL` mean?** The publisher *keeps* its last sample and re-delivers it
to any subscriber that joins **after** it was published. Without it, a node that starts late
would sit forever with no static TF and no robot model because the one-time message already
went out before it was listening. `TRANSIENT_LOCAL` is a durability setting and decides whether
late joiners get history.

> The matching subscriber must request `VOLATILE` or `TRANSIENT_LOCAL`.
> A `VOLATILE` **publisher** can never satisfy a `TRANSIENT_LOCAL`
> subscriber, which is why latched topics are always published transient-local.

### 4b. Reliable state: `/robot_1/joint_states`

Now look at `/robot_1/joint_states`.

> **What you expect to see:** `RELIABLE`, `KEEP_LAST` with depth `1`, `VOLATILE`.

- **Why `RELIABLE`?** Joint states feed TF and the controllers. A dropped update means the
  model and the kinematics briefly disagree. Reliable delivery retransmits until the sample
  is confirmed, so consumers stay consistent.
- **Why `KEEP_LAST` (depth 1)?** Only the *newest* joint state matters. An old position is
  useless once a fresher one exists. `KEEP_LAST(1)` queues just the latest sample and lets
  older ones fall off, so you never build a backlog of stale state.
- **What `VOLATILE` means:** the publisher keeps **no** history for late joiners. Unlike the
  latched topics above, a subscriber that starts late does not get the previous value. It
  simply waits for the next joint state, which arrives almost immediately on a live stream.

### 4c. Sensor stream: `/robot_1/sensor_0/camera/image_raw`

Finally look at the camera. On this robot it is published `RELIABLE`, `KEEP_LAST(10)`,
`VOLATILE`.

Check how much bandwidth the image stream actually consumes:

```bash
ros2 topic bw /robot_1/sensor_0/camera/image_raw
```

Let it run for a few seconds to settle, then Ctrl-C. Unlike the tiny state topics above, raw
images move real data. Keep this figure in mind when you reason about pushing it off-board.

**Does `RELIABLE` make sense here?** *On the robot*, yes. Publisher and subscriber share the
same host with effectively zero loss and huge bandwidth, so reliable delivery is cheap and
you get every frame which works for on-board perception.

**But once it goes off-board**, streamed across the network to the observer, the answer flips.
A reliable image stream retransmits dropped frames, and on a congested or
lossy link that retransmission piles up into growing latency: you fall further and further
behind live. For a **remote viewer** the newest frame matters far more than every frame, so
the off-board subscriber should request **`BEST_EFFORT`**: take whatever arrives, drop what's
late, and stay current. A `RELIABLE` publisher still serves a `BEST_EFFORT` subscriber
(offered ≥ requested), so you can keep the on-board publisher reliable and let the remote
side opt into best-effort.

## Move on to the next exercise

First, leave the robot shell and bring the whole fleet down:

```bash
exit                              # leave the mock-robot-1 shell
```

```
scripts/workshop -t flat down
```

Then continue to [Exercise 3](3_fleet_discovery_and_domains.md).

**Next:** [3. Fleet discovery and domain isolation](3_fleet_discovery_and_domains.md)


## More Details about the QoS

### QoS policies

A QoS profile is a combination of these policies:

| Policy | Options | What it controls |
| --- | --- | --- |
| **History** | `KEEP_LAST` (depth N), `KEEP_ALL` | How many samples are queued before delivery. |
| **Depth** | integer | Queue size, used only with `KEEP_LAST`. |
| **Reliability** | `RELIABLE`, `BEST_EFFORT` | `RELIABLE` retransmits until confirmed; `BEST_EFFORT` may drop samples. |
| **Durability** | `VOLATILE`, `TRANSIENT_LOCAL` | `TRANSIENT_LOCAL` re-delivers the last samples to late joiners; `VOLATILE` does not. |
| **Deadline** | duration | Maximum expected gap between messages. |
| **Lifespan** | duration | How long a sample stays valid before it is dropped. |
| **Liveliness** | `AUTOMATIC`, `MANUAL_BY_TOPIC` | How a publisher is judged still alive. |
| **Lease Duration** | duration | Time within which a publisher must assert liveliness. |

### Default QoS profiles

ROS 2 ships predefined profiles for common cases:

| Profile | Reliability | History (Depth) | Durability | Use for |
| --- | --- | --- | --- | --- |
| **Default** (`rmw_qos_profile_default`) | `RELIABLE` | `KEEP_LAST` (10) | `VOLATILE` | Most standard topics. |
| **Sensor Data** (`rmw_qos_profile_sensor_data`) | `BEST_EFFORT` | `KEEP_LAST` (5) | `VOLATILE` | Cameras, lidar, IMU — latest data over guaranteed delivery. |
| **Parameters** (`rmw_qos_profile_parameters`) | `RELIABLE` | `KEEP_LAST` (1000) | `VOLATILE` | Parameter get/set bursts. |
| **Services** (`rmw_qos_profile_services_default`) | `RELIABLE` | `KEEP_LAST` (10) | `VOLATILE` | Request/response services. |
| **Parameter Events** (`rmw_qos_profile_parameter_events`) | `RELIABLE` | `KEEP_LAST` (1000) | `VOLATILE` | The `/parameter_events` topic. |
| **System Default** (`rmw_qos_profile_system_default`) | `SYSTEM_DEFAULT` | `SYSTEM_DEFAULT` | `SYSTEM_DEFAULT` | Let the RMW/DDS vendor config decide. |
| **Latched / Transient Local** (pattern) | `RELIABLE` | `KEEP_LAST` (1) | `TRANSIENT_LOCAL` | `/tf_static`, `/map`, `/robot_description`. |

### QoS compatibility

A connection forms only when the publisher (**offered**) and subscriber (**requested**) QoS
are compatible. The rule is **requested ≤ offered**: the publisher must offer a service level
at least as strong as the subscriber requests.

| Publisher (offered) | Subscriber (requested) | Reliability | Durability |
| --- | --- | --- | --- |
| `RELIABLE` / `TRANSIENT_LOCAL` | `RELIABLE` / `TRANSIENT_LOCAL` | ✅ | ✅ |
| `RELIABLE` / `TRANSIENT_LOCAL` | `BEST_EFFORT` / `VOLATILE` | ✅ | ✅ |
| `BEST_EFFORT` | `RELIABLE` | ❌ | — |
| `VOLATILE` | `TRANSIENT_LOCAL` | — | ❌ |

History/Depth, Lifespan, Deadline, and Liveliness differences do **not** block the common
reliability/durability connection.

### What happens on a QoS mismatch

When reliability or durability are incompatible, the connection is **silently never
established** — no messages flow and neither side prints an error by default. Both endpoints
still show up in `ros2 topic info`, but they never exchange samples. This is the most common
cause of "my node isn't receiving anything."

To detect it, compare both ends and look for `RELIABLE` vs `BEST_EFFORT` or `VOLATILE` vs
`TRANSIENT_LOCAL`:

```bash
ros2 topic info -v /robot_1/scan
```

In code, register QoS event callbacks — `RequestedIncompatibleQoS` on the subscriber and
`OfferedIncompatibleQoS` on the publisher — to be notified instead of silently receiving
nothing.

> **Matched but degraded:** a `RELIABLE` publisher *will* serve a `BEST_EFFORT` subscriber,
> but performs no retransmission repair for it — late samples are dropped rather than
> accumulating latency. That is exactly the on-board vs off-board trade-off from step 4c.

### Setting and overriding QoS profiles

**In code**, build a profile or use a predefined one:

```python
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy, QoSDurabilityPolicy

qos = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=5,
    durability=QoSDurabilityPolicy.VOLATILE,
)
self.create_subscription(Image, '/camera/image', self.cb, qos)

# Or a predefined profile:
from rclpy.qos import qos_profile_sensor_data
self.create_subscription(Image, '/camera/image', self.cb, qos_profile_sensor_data)
```

```cpp
auto qos      = rclcpp::SensorDataQoS();            // sensor data profile
auto reliable = rclcpp::QoS(10).reliable();         // KEEP_LAST depth 10, reliable
auto latched  = rclcpp::QoS(1).transient_local();   // latched
```

**Overriding QoS with parameters** lets you retune a node without recompiling. Opt the
endpoint in when you create it, then set the exposed `qos_overrides.*` parameters:

```python
from rclpy.qos_overriding_options import QoSOverridingOptions

self.create_subscription(
    Image, '/camera/image', self.cb, qos_profile_sensor_data,
    qos_overriding_options=QoSOverridingOptions.with_default_policies(),
)
```

```cpp
rclcpp::SubscriptionOptions options;
options.qos_overriding_options = rclcpp::QosOverridingOptions::with_default_policies();
create_subscription<sensor_msgs::msg::Image>(
  "/camera/image", rclcpp::SensorDataQoS(), cb, options);
```

Then override at launch via a parameters YAML — for example flipping the off-board image
subscriber to best-effort:

```yaml
/robot_1/image_viewer:
  ros__parameters:
    qos_overrides:
      /robot_1/sensor_0/camera/image_raw:
        subscription:
          reliability: best_effort
          history: keep_last
          depth: 5
```

Load it with `--params-file` (or `--ros-args -p ...`), so operators can retune QoS in the
field without touching source.

### References

- [ROS 2 QoS documentation](https://docs.ros.org/en/jazzy/Concepts/Intermediate/About-Quality-of-Service-Settings.html)
- [QoS overrides](https://docs.ros.org/en/jazzy/Concepts/Intermediate/About-Quality-of-Service-Settings.html#qos-profiles)
- [rmw QoS profiles (`rmw/qos_profiles.h`)](https://github.com/ros2/rmw/blob/jazzy/rmw/include/rmw/qos_profiles.h)

