"""Scenario/scale resolution and dry-run acceptance fixtures."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import benchmark_defs
from report_utils import compatibility_key, groups

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_sweep.sh"
DEFS = benchmark_defs.load()


class ScenarioResolutionTests(unittest.TestCase):
    def cells(self, templates="B", scenarios=None, rmws="cyclone,fastdds", scale=7):
        return benchmark_defs.resolve_cells(DEFS, templates.split(","), scenarios,
                                            rmws.split(","), scale)

    def test_omitted_scenario_is_clean_s0(self):
        cells = self.cells(templates="B")
        self.assertEqual({c["scenario"] for c in cells}, {"S0"})
        self.assertEqual({c["scale"] for c in cells}, {7})
        self.assertTrue(all(c["scale_source"] == "cli" for c in cells))

    def test_explicit_and_all_follow_template_configuration(self):
        self.assertEqual({c["scenario"] for c in self.cells("A,B", "S0")}, {"S0"})
        all_cells = self.cells("A,B", "all", scale=9)
        self.assertEqual({c["scenario"] for c in all_cells if c["template"] == "A"}, {"S0"})
        self.assertEqual({c["scenario"] for c in all_cells if c["template"] == "B"},
                         {"S0", "S1", "S2", "S3", "constrained"})

    def test_s1_expands_configured_replica_counts_and_ignores_cli_scale(self):
        cells = self.cells(scenarios="S1", scale=99)
        self.assertEqual([c["scale"] for c in cells], [1, 1, 3, 3])
        self.assertTrue(all(c["scale_source"] == "scenario-config" for c in cells))

    def test_template_a_is_pair_and_unsupported_mixes_are_rejected(self):
        cells = self.cells("A", scale=99)
        self.assertEqual({c["scale"] for c in cells}, {2})
        self.assertTrue(all(c["scale_source"] == "template-a-pair" for c in cells))
        with self.assertRaisesRegex(ValueError, "unsupported template/scenario"):
            self.cells("A,B", "S1")

    def test_scale_is_report_identity(self):
        rows = [{"template": "B", "topology": "bridge", "scenario": "S1",
                 "scale": 1, "workload": "bag", "engine": "mcap"},
                {"template": "B", "topology": "bridge", "scenario": "S1",
                 "scale": 3, "workload": "bag", "engine": "mcap"}]
        self.assertEqual(len(groups(rows)), 2)
        self.assertNotEqual(compatibility_key(rows[0]), compatibility_key(rows[1]))

    def test_dry_run_does_not_invoke_docker_and_prints_cells(self):
        env = dict(os.environ, LAB4_DOCKER_BIN="/definitely/not-a-docker")
        proc = subprocess.run(["bash", str(RUNNER), "--template", "B", "--scenario", "S1",
                               "--rmw", "cyclone,fastdds", "--scale", "88", "--dry-run"],
                              cwd=HERE.parents[2], env=env, text=True,
                              capture_output=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("scale=1 (scenario-config)", proc.stdout)
        self.assertIn("scale=3 (scenario-config)", proc.stdout)
        self.assertNotIn("88 (cli)", proc.stdout)
        self.assertNotIn("/definitely/not-a-docker", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
