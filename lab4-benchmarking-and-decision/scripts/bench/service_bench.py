#!/usr/bin/env python3
"""Service round-trip benchmark client.

Calls example_interfaces/AddTwoInts on the server (assumed running in
another container on the same DDS domain) N times, records per-call
round-trip time, prints one line to stdout:  `mean_ms max_ms recv_hz p99_ms`.
The first three fields match pubsub.sh; the trailing p99 is appended so
existing 3-field readers keep working. recv_hz here is calls/s.
"""

import math
import sys
import time
from statistics import mean

import rclpy
from example_interfaces.srv import AddTwoInts


def _percentile(values, pct):
    """Nearest-rank percentile (pct in 0..100) over a non-empty list."""
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, math.ceil(pct / 100.0 * len(ordered)) - 1))
    return ordered[k]


def main():
    n_calls = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    timeout_s = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0

    rclpy.init()
    node = rclpy.create_node("bench_service_client")
    client = node.create_client(AddTwoInts, "add_two_ints")

    if not client.wait_for_service(timeout_sec=timeout_s):
        print("n/a n/a n/a")
        node.destroy_node()
        rclpy.shutdown()
        return 0

    latencies_ms = []
    req = AddTwoInts.Request()
    req.a = 1
    req.b = 2

    wall_start = time.monotonic()
    for _ in range(n_calls):
        t0 = time.monotonic()
        fut = client.call_async(req)
        rclpy.spin_until_future_complete(node, fut, timeout_sec=timeout_s)
        t1 = time.monotonic()
        if fut.result() is None:
            latencies_ms.append(float("nan"))
        else:
            latencies_ms.append((t1 - t0) * 1000.0)
    wall_end = time.monotonic()

    node.destroy_node()
    rclpy.shutdown()

    good = [x for x in latencies_ms if x == x]  # drop NaN
    if not good:
        print("n/a n/a n/a")
        return 0

    mean_ms = mean(good)
    max_ms = max(good)
    p99_ms = _percentile(good, 99)
    hz = len(good) / max(wall_end - wall_start, 1e-6)
    print(f"{mean_ms:.3f} {max_ms:.3f} {hz:.0f} {p99_ms:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
