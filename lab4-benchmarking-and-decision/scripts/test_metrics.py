#!/usr/bin/env python3
"""Metric reducer fixtures; no ROS, Docker, or wall-clock timing required."""
from __future__ import annotations

import unittest
import subprocess
import tempfile
import os
from pathlib import Path

from metrics import (classify_inventory, expected_rates_from_inventory, reduce_class_observations,
                     reduce_cpu_samples, reduce_topic_observations)


class MetricReducerFixtures(unittest.TestCase):
    def test_inventory_rates_survive_without_legacy_metadata_argument(self):
        expected = {"/robot_1/camera": {"message_count": 20}}
        self.assertEqual(expected_rates_from_inventory(expected, 10.0, 1.0),
                         {"/robot_1/camera": 2.0})

    def reduce(self, receipts, minimum=2):
        return reduce_topic_observations(receipts, 0.0, 10.0,
                                         {topic: 1.0 for topic in receipts}, minimum)["topics"]

    def test_normal_and_delayed_first_delivery(self):
        result = self.reduce({"/normal": [1, 2, 3], "/delayed": [4, 5, 6]})
        self.assertEqual(result["/normal"]["received_count"], 3)
        self.assertEqual(result["/normal"]["first_receipt_offset_s"], 1.0)
        self.assertEqual(result["/delayed"]["first_receipt_offset_s"], 4.0)
        self.assertEqual(result["/normal"]["maximum_silence_ms"], 7000.0)
        self.assertEqual(result["/delayed"]["maximum_silence_ms"], 4000.0)

    def test_early_stoppage_complete_silence_and_missing_replica(self):
        result = self.reduce({"/stops": [1, 2], "/silent": []})
        self.assertEqual(result["/stops"]["terminal_silence_ms"], 8000.0)
        self.assertEqual(result["/silent"]["maximum_silence_ms"], 10000.0)
        self.assertIsNone(result["/silent"]["arrival_gap_p95_ms"])
        inventory = [{"topic": "/robot_1/cmd", "type": "x"},
                     {"topic": "/robot_2/cmd", "type": "x"}]
        classified = classify_inventory(inventory, {"/robot_1/cmd": ["x"]}, ["/robot_1/cmd"])
        self.assertEqual(classified["expected_count"], 2)
        self.assertEqual(classified["matched_count"], 1)
        self.assertEqual(classified["received_count"], 1)

    def test_insufficient_samples_and_burst_delivery(self):
        result = self.reduce({"/few": [2], "/burst": [2, 2.01, 2.02, 2.03]}, minimum=3)
        self.assertFalse(result["/few"]["gap_metrics_available"])
        self.assertIsNone(result["/few"]["arrival_gap_p99_ms"])
        self.assertTrue(result["/burst"]["gap_metrics_available"])
        self.assertEqual(result["/burst"]["arrival_gap_p99_ms"], 10.0)

    def test_worst_topic_silence_wins_class_summary(self):
        topics = self.reduce({"/busy": [1, 2, 3], "/quiet": [4, 5]})
        summary = reduce_class_observations(topics, {"/busy": "state", "/quiet": "state"})
        self.assertEqual(summary["state"]["maximum_silence_ms"], 7000.0)

    def test_cpu_samples_must_overlap_recorded_window(self):
        cpu = reduce_cpu_samples([(-1, 90), (2, 10), (5, 30), (11, 99)], 0, 10)
        self.assertEqual(cpu["sample_count"], 2)
        self.assertEqual(cpu["mean_cpu_pct"], 20.0)
        self.assertTrue(all(0 <= s["timestamp"] <= 10 for s in cpu["samples"]))

    def test_zero_reception_report_frames_remain_in_template_a_rate_window(self):
        # This is the same frame discriminator used by bench/pubsub.sh.  A
        # zero-reception frame is still one elapsed report interval.
        frames = "\n".join([
            "a|0|c|d|e|f|g|h|0.1|0.05|k|l",
            "a|5|c|d|e|f|g|h|0.1|0.05|k|l",
            "a|0|c|d|e|f|g|h|0.1|0.05|k|l",
        ]) + "\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frames.log"
            path.write_text(frames, encoding="utf-8")
            result = subprocess.run([
                "awk", "-F|", "NF == 12 && $2 ~ /^ *[0-9]+ *$/ { total += $2; frames += 1 } END { print total, frames }", str(path)
            ], check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), "5 3")

    def test_pubsub_default_docker_name_does_not_recurse(self):
        script = Path(__file__).with_name("bench") / "pubsub.sh"
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "docker"
            fake.write_text("#!/usr/bin/env bash\nexit 42\n", encoding="utf-8")
            fake.chmod(0o755)
            env = dict(os.environ, PATH=f"{directory}:{os.environ['PATH']}",
                       LAB4_DOCKER_BIN="docker")
            result = subprocess.run(
                ["bash", str(script), "publisher", "receiver", "best_effort", "1"],
                env=env, capture_output=True, text=True, timeout=5,
            )
        self.assertEqual(result.returncode, 42, result.stderr)


if __name__ == "__main__":
    unittest.main()
