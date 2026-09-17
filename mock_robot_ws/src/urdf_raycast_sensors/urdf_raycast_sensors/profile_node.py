"""CLI helper: profile the CPU and RAM usage of a running ROS 2 node process.

Finds the target node's OS process (by matching its executable/command line),
samples CPU% and resident memory (RSS) at a fixed interval, and reports summary
statistics (mean / p95 / peak). Intended to quantify the cost of ``laserscan_node``
but works for any node whose process command line contains the given match string.

Run it inside the same container / PID namespace as the node, e.g.::

    ros2 run urdf_raycast_sensors profile_node
    ros2 run urdf_raycast_sensors profile_node --match laserscan_node --duration 15

To contrast the static-pose cache (sensor still) against the full raycast (sensor
moving), drive the pose_broadcaster while sampling::

    ros2 run urdf_raycast_sensors profile_node --compare
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from typing import Callable, List, Optional

import psutil


def _find_process(match: str) -> Optional[psutil.Process]:
    """Return the first process whose command line contains ``match``.

    Skips this process and all of its ancestors, so the profiler never matches its
    own launcher (e.g. the ``ros2 run ... --match <name>`` command whose command line
    also contains ``match``).
    """
    me = psutil.Process()
    exclude = {me.pid}
    for ancestor in me.parents():
        exclude.add(ancestor.pid)
    for proc in psutil.process_iter(["pid", "cmdline"]):
        if proc.info["pid"] in exclude:
            continue
        cmdline = proc.info.get("cmdline") or []
        if any(match in part for part in cmdline):
            return proc
    return None


def _percentile(values: List[float], pct: float) -> float:
    """Return the ``pct`` (0-100) percentile of ``values`` using nearest-rank."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(int(round(pct / 100.0 * len(ordered))) - 1, 0)
    return ordered[rank]


def _mib(num_bytes: int) -> float:
    """Convert a byte count to MiB."""
    return num_bytes / (1024.0 * 1024.0)


class _PoseMover:
    """Drive a ``pose_broadcaster`` node's pose parameters to move the sensor frame.

    Uses an rclpy parameter client to set the ``x``/``y`` parameters of the target
    broadcaster node on each call, oscillating the sensor position so the
    ``laserscan_node`` static-pose cache misses every tick (i.e. the full raycast runs).
    rclpy is imported lazily so the profiler has no ROS dependency unless movement is
    actually requested.
    """

    def __init__(self, node_name: str, radius: float = 2.0) -> None:
        """Connect a parameter client to ``node_name`` (e.g. the pose broadcaster)."""
        import rclpy
        from rclpy.parameter_client import AsyncParameterClient

        self._rclpy = rclpy
        self._radius = radius
        rclpy.init()
        self._node = rclpy.create_node("profile_node_mover")
        self._client = AsyncParameterClient(self._node, node_name)
        if not self._client.wait_for_services(timeout_sec=5.0):
            self.close()
            raise RuntimeError(
                f"Parameter services for '{node_name}' unavailable. "
                "Is the pose_broadcaster running (mover:=manual)?"
            )

    def __call__(self, i: int) -> None:
        """Move the sensor to a new point on a circle for sample index ``i``."""
        from rclpy.parameter import Parameter

        theta = 0.4 * i  # radians; steps guarantee a change well above the epsilon
        x = self._radius * math.cos(theta)
        y = self._radius * math.sin(theta)
        future = self._client.set_parameters(
            [
                Parameter("x", Parameter.Type.DOUBLE, x),
                Parameter("y", Parameter.Type.DOUBLE, y),
            ]
        )
        self._rclpy.spin_until_future_complete(self._node, future, timeout_sec=1.0)

    def close(self) -> None:
        """Tear down the rclpy node and context."""
        try:
            self._node.destroy_node()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass
        if self._rclpy.ok():
            self._rclpy.shutdown()


def sample(
    proc: psutil.Process,
    duration: float,
    interval: float,
    use_uss: bool,
    on_tick: Optional[Callable[[int], None]] = None,
) -> dict:
    """Sample CPU% and memory of ``proc`` for ``duration`` seconds at ``interval``.

    If ``on_tick`` is given it is called with the 0-based sample index immediately
    before each CPU measurement window, allowing the caller to perturb the system
    (e.g. move the sensor frame) so the measurement covers the non-cached path.

    Returns a dict of summary statistics. CPU% is reported relative to a single core
    (so it can exceed 100% for multi-threaded processes). Memory uses RSS by default,
    or USS (unique/private set) when ``use_uss`` is set.
    """
    proc.cpu_percent(interval=None)  # prime the CPU counter

    cpu_samples: List[float] = []
    mem_samples: List[float] = []

    end = time.monotonic() + duration
    i = 0
    while time.monotonic() < end:
        if on_tick is not None:
            on_tick(i)
        cpu_samples.append(proc.cpu_percent(interval=interval))
        if use_uss:
            mem_samples.append(_mib(proc.memory_full_info().uss))
        else:
            mem_samples.append(_mib(proc.memory_info().rss))
        i += 1

    return {
        "n": len(cpu_samples),
        "cpu_mean": sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0.0,
        "cpu_p95": _percentile(cpu_samples, 95.0),
        "cpu_max": max(cpu_samples) if cpu_samples else 0.0,
        "mem_mean": sum(mem_samples) / len(mem_samples) if mem_samples else 0.0,
        "mem_peak": max(mem_samples) if mem_samples else 0.0,
    }


def _print_report(title: str, stats: dict, mem_label: str) -> None:
    """Print one labelled block of CPU/memory summary statistics."""
    print(f"[{title}] samples={stats['n']}")
    print(
        f"    CPU  mean={stats['cpu_mean']:.1f}%  "
        f"p95={stats['cpu_p95']:.1f}%  max={stats['cpu_max']:.1f}%  (per core)"
    )
    print(
        f"    {mem_label}  mean={stats['mem_mean']:.1f} MiB  "
        f"peak={stats['mem_peak']:.1f} MiB"
    )


def main(argv: Optional[List[str]] = None) -> int:
    """Parse arguments, locate the node process, sample it, and print a report."""
    parser = argparse.ArgumentParser(
        description="Profile CPU% and RAM (RSS/USS) of a running ROS 2 node process."
    )
    parser.add_argument(
        "--match",
        default="laserscan_node",
        help="Substring to match against process command lines (default: laserscan_node).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Total sampling duration in seconds, per window (default: 10).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="Seconds between samples; also the CPU averaging window (default: 0.5).",
    )
    parser.add_argument(
        "--uss",
        action="store_true",
        help="Report USS (unique/private RAM) instead of RSS. Needs /proc smaps access.",
    )
    parser.add_argument(
        "--move",
        action="store_true",
        help="Move the sensor while sampling (forces the non-cached raycast path).",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Sample a static (cached) window then a moving (non-cached) window.",
    )
    parser.add_argument(
        "--move-node",
        default="/urdf_raycast_pose_broadcaster",
        help="Pose broadcaster node to drive when moving (default: "
        "/urdf_raycast_pose_broadcaster).",
    )
    args = parser.parse_args(argv)

    proc = _find_process(args.match)
    if proc is None:
        print(
            f"No process found matching '{args.match}'. "
            "Is the node running in this PID namespace?",
            file=sys.stderr,
        )
        return 1

    mem_label = "USS" if args.uss else "RSS"
    print(
        f"Profiling PID {proc.pid} (match='{args.match}') "
        f"for {args.duration:.0f}s @ {args.interval:.2f}s, cores={psutil.cpu_count()}"
    )

    mover: Optional[_PoseMover] = None
    try:
        if args.move or args.compare:
            try:
                mover = _PoseMover(args.move_node)
            except Exception as exc:  # noqa: BLE001 - surface a helpful message
                print(f"Could not start pose mover: {exc}", file=sys.stderr)
                return 1

        if args.compare:
            static_stats = sample(proc, args.duration, args.interval, args.uss)
            _print_report("static (cache hit)", static_stats, mem_label)
            moving_stats = sample(
                proc, args.duration, args.interval, args.uss, on_tick=mover
            )
            _print_report("moving (cache miss)", moving_stats, mem_label)
            delta = moving_stats["cpu_mean"] - static_stats["cpu_mean"]
            print(
                f"[delta] moving - static CPU mean = {delta:+.1f}%  "
                "(cost of the raycast the cache avoids)"
            )
        else:
            stats = sample(
                proc,
                args.duration,
                args.interval,
                args.uss,
                on_tick=mover if args.move else None,
            )
            label = "moving (cache miss)" if args.move else "static (cache hit)"
            _print_report(label, stats, mem_label)
    except psutil.NoSuchProcess:
        print("The target process exited during sampling.", file=sys.stderr)
        return 1
    except psutil.AccessDenied:
        hint = " (USS needs elevated access to /proc/<pid>/smaps)" if args.uss else ""
        print(f"Access denied reading process stats{hint}.", file=sys.stderr)
        return 1
    finally:
        if mover is not None:
            mover.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
