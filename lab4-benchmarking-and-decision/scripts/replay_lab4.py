#!/usr/bin/env python3
"""Lab 4-only rosbag2 replay entrypoint; shared playback remains unchanged."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from replay_inventory import InventoryError, inspect_bag


def default_namespace() -> str:
    address = subprocess.run(["hostname", "-I"], check=False, capture_output=True, text=True).stdout.split()
    if address and address[0].count(".") == 3:
        return "/robot_" + address[0].rsplit(".", 1)[1]
    return "/robot_" + (subprocess.run(["hostname"], check=False, capture_output=True, text=True).stdout.strip() or "unknown")


def build_play_command(bag_dir: str, rate: float, namespace: str, topics: list[dict]) -> list[str]:
    command = ["ros2", "bag", "play", bag_dir, "--loop", "--rate", str(rate)]
    if namespace:
        prefix = namespace.rstrip("/")
        remaps = [f"{topic['name']}:={prefix}{topic['name']}" for topic in topics]
        if remaps:
            # ros2 bag accepts one --remap followed by all rules. Repeating the
            # option replaces earlier rules, leaving only the final topic mapped.
            command.extend(["--remap", *remaps])
    return command


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag-dir", default="/bags")
    parser.add_argument("--rate", type=float, default=1.0)
    parser.add_argument("--namespace", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        inventory = inspect_bag(args.bag_dir)
    except InventoryError as exc:
        print(f"lab4 replay rejected bag: {exc}", file=sys.stderr)
        return 2
    if args.rate <= 0:
        print("lab4 replay rejected non-positive rate", file=sys.stderr)
        return 2
    print(f"lab4 replay: {args.bag_dir} files={len(inventory['storage_files'])} rate={args.rate:g}", flush=True)
    if args.dry_run:
        return 0
    namespace = args.namespace or default_namespace()
    command = build_play_command(args.bag_dir, args.rate, namespace, inventory["topics"])
    return subprocess.call(command, env=os.environ.copy())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
