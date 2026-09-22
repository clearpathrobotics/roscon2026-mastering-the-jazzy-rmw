# routed_zenoh_ap_hub — hub-and-spoke routed Zenoh config (N=3)

The routed Zenoh topology used by [Exercise 4](../../exercises/4_repeat_with_zenoh.md):
every robot runs its own `rmw_zenohd` router, and only genuinely remote traffic crosses
the shared AP.

Apply:

    scripts/workshop -t routed up 3 zenoh --rmw-directory lab3-stress-testing/fixtures/routed_zenoh_ap_hub

Topology: every robot's router uplinks to the `wifi-ap` hub (`connect: wifi-ap:7447`,
gossip/multicast off). Local ROS nodes connect to their own host's router over loopback,
so a robot's control loop never leaves the container. The observer is a peer that dials
the hub directly (this harness runs no router on the observer) and still sees the whole
fleet through the hub.

**N=3 only.** The override requires one config file per robot, so running at another N
fails loud with "missing required file". Rebuild the fixture for a different fleet size
if needed.
