#!/usr/bin/env python3
"""Replay and inventory boundary tests; no Docker or ROS runtime required."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from replay_inventory import InventoryError, build_inventory, inspect_bag, resolve_bag_directory
from replay_lab4 import build_play_command


def write_bag(root: Path, files=("recording.mcap",), topics=None, flat=False) -> Path:
    bag = root if flat else root / "bag"
    bag.mkdir(parents=True)
    for name in files:
        (bag / name).write_bytes(name.encode())
    topics = topics or [{"topic_metadata": {"name": "/cmd_vel", "type": "geometry_msgs/msg/Twist"}, "message_count": 4}]
    metadata = {"rosbag2_bagfile_information": {
        "storage_identifier": "mcap", "relative_file_paths": list(files),
        "duration": {"nanoseconds": 2_000_000_000}, "topics_with_message_count": topics}}
    (bag / "metadata.yaml").write_text(__import__("yaml").safe_dump(metadata), encoding="utf-8")
    return bag


class ReplayInventoryTests(unittest.TestCase):
    def test_replay_passes_every_topic_to_one_remap_option(self):
        topics = [{"name": "/camera"}, {"name": "/cmd_vel"}, {"name": "/tf"}]
        command = build_play_command("/bags", 1.0, "/robot_7", topics)
        self.assertEqual(command.count("--remap"), 1)
        self.assertEqual(command[command.index("--remap") + 1:], [
            "/camera:=/robot_7/camera", "/cmd_vel:=/robot_7/cmd_vel", "/tf:=/robot_7/tf",
        ])

    def test_compose_replay_sources_ros_environment(self):
        compose = Path(__file__).parents[2] / "docker" / "docker-compose.yml"
        text = compose.read_text(encoding="utf-8")
        self.assertIn("source /opt/ros/jazzy/setup.bash && exec python3 /scripts/lab4/replay_lab4.py", text)

    def test_single_and_split_files_are_all_hashed(self):
        with tempfile.TemporaryDirectory() as td:
            one = inspect_bag(write_bag(Path(td)))
            self.assertEqual([f["path"] for f in one["storage_files"]], ["recording.mcap"])
            split = inspect_bag(write_bag(Path(td) / "split", ("part-0.mcap", "part-1.mcap")))
            self.assertEqual(len(split["storage_files"]), 2)
            self.assertTrue(all(len(f["sha256"]) == 64 for f in split["storage_files"]))

    def test_missing_extra_and_ambiguous_storage_are_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bag = write_bag(root, ("missing.mcap",))
            (bag / "missing.mcap").unlink()
            with self.assertRaisesRegex(InventoryError, "missing"):
                inspect_bag(bag)
            bag = write_bag(root / "extra", ("listed.mcap",))
            (bag / "unlisted.mcap").write_bytes(b"x")
            with self.assertRaisesRegex(InventoryError, "not listed"):
                inspect_bag(bag)
            parent = root / "many"
            write_bag(parent / "a", flat=True)
            write_bag(parent / "b", flat=True)
            with self.assertRaisesRegex(InventoryError, "ambiguous"):
                resolve_bag_directory(parent)

    def test_unknown_type_is_inventory_truth_and_expected_topics_are_namespaced(self):
        with tempfile.TemporaryDirectory() as td:
            topic = {"topic_metadata": {"name": "/mystery", "type": "missing_pkg/msg/Unknown"}, "message_count": 3}
            result = build_inventory(write_bag(Path(td), topics=[topic]), ["/robot_7", "/robot_8"],
                                     {"/robot_7": "sha256:a", "/robot_8": "sha256:b"}, 2,
                                     qos={"sensor": {"reliability": "best_effort"}},
                                     benchmark_config="benchmark.yaml")
            self.assertEqual([x["topic"] for x in result["expected_topics"]], ["/robot_7/mystery", "/robot_8/mystery"])
            self.assertEqual(result["topics"][0]["type"], "missing_pkg/msg/Unknown")
            self.assertEqual(result["requested_replicas"], 2)

    def test_replica_count_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(InventoryError, "requested 3 replicas"):
                build_inventory(write_bag(Path(td)), ["/robot_1"], requested_replicas=3)


if __name__ == "__main__":
    unittest.main()
