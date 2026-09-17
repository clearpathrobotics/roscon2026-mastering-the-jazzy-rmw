#!/usr/bin/env python3
"""Regression tests for scenario-specific Pugh scoring."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pugh


class PughTests(unittest.TestCase):
    def test_separates_scenarios_and_rewards_lower_gap_metrics(self) -> None:
        rows = [
            result("S0", "cyclone", 1.0, 10.0),
            result("S0", "zenoh", 5.0, 50.0),
            result("S2", "cyclone", 5.0, 50.0),
            result("S2", "zenoh", 1.0, 10.0),
        ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            results_path = Path(temporary_directory) / "results.jsonl"
            results_path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
            )

            self.assertEqual(pugh.main([temporary_directory]), 0)
            report = (Path(temporary_directory) / "pugh.md").read_text(encoding="utf-8")

        self.assertIn("Scenario S0", report)
        self.assertIn("Scenario S2", report)
        s0, s2 = report.split("## Template B", 2)[1:]
        self.assertIn("**Ranking:** Cyclone DDS", s0)
        self.assertIn("**Ranking:** Zenoh", s2)


def result(scenario: str, rmw: str, drop_percentage: float, freshness_ms: float) -> dict:
    return {
        "template": "B",
        "topology": "bridge",
        "scenario": scenario,
        "rmw": rmw,
        "metrics": {
            "sensor_drop_pct": drop_percentage,
            "control_p99_ms": freshness_ms,
            "state_freshness_ms": freshness_ms,
            "throughput_mbps": 10.0 if rmw == "cyclone" else 5.0,
            "cpu_pct": freshness_ms,
        },
    }


if __name__ == "__main__":
    unittest.main()
