#!/usr/bin/env python3
"""Run-integrity contract tests: validation, cleanup, and result accounting; no Docker or ROS runtime is required."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pugh
import shaping_state


HERE = Path(__file__).resolve().parent


class RunIntegrityResultTests(unittest.TestCase):
    def test_shaping_rejects_unavailable_and_wrong_parameters(self):
        clean=json.dumps([{"kind":"noqueue","root":True}])
        links=json.dumps([{"ifname":"eth0","flags":["UP"]}])
        self.assertTrue(shaping_state.validate(clean,"[]",links,clean,"none","")[0])
        self.assertFalse(shaping_state.validate("","[]",links,clean,"none","")[0])
        self.assertFalse(shaping_state.validate("not json","[]",links,clean,"none","")[0])
        options={"delay":{"delay":.03,"jitter":.01},"loss-gemodel":{"p":.05,"r":.95,"1-h":1,"1-k":0},"rate":{"rate":2500000}}
        q={"kind":"netem","root":True,"options":options}
        ingress=json.dumps([{"actions":[{"kind":"mirred","mirred_action":"redirect","direction":"egress","to_dev":"ifb0"}]}])
        links=json.dumps([{"ifname":"eth0","flags":["UP"]},{"ifname":"ifb0","flags":["UP"]}])
        def check(): return shaping_state.validate(json.dumps([q]),ingress,links,json.dumps([dict(q,dev="ifb0")]),"heavy","20mbit")
        self.assertTrue(check()[0])
        options["delay"]["delay"]=.005
        self.assertIn("egress_delay_mismatch",check()[1])
        options["delay"]["delay"]=.03; options["loss-gemodel"]["p"]=.001
        self.assertIn("ifb_loss_mismatch",check()[1])

    def test_emitter_is_versioned_finite_and_explicit_about_missing_metrics(self):
        env = os.environ.copy()
        env.update({
            "R_CELL_ID": "run_B_bridge_S2_cyclone_3x",
            "R_TEMPLATE": "B", "R_TOPOLOGY": "bridge", "R_SCENARIO": "S2",
            "R_RMW": "cyclone", "R_STATUS": "invalid",
            "R_REASONS": "shaping_ingress_mismatch,metric_unavailable",
            "R_SENSOR_DROP": "nan", "R_CONTROL_P99": "Infinity",
            "R_STATE_FRESH": "4.5", "R_THROUGHPUT": "n/a", "R_CPU": "2.0",
            "R_MEASUREMENT_WINDOW": '{"cell_started":"a","cell_ended":"b"}',
            "R_ARTIFACTS": '{"shaping":"shaping.jsonl"}',
            "R_METRIC_AVAILABILITY": '{"state_freshness_ms":true}',
        })
        completed = subprocess.run(
            [sys.executable, str(HERE / "emit_result.py")],
            env=env, check=True, capture_output=True, text=True,
        )
        row = json.loads(completed.stdout)
        self.assertEqual(row["schema_version"], 2)
        self.assertEqual(row["status"], "invalid")
        self.assertIsNone(row["metrics"]["sensor_drop_pct"])
        self.assertIsNone(row["metrics"]["control_p99_ms"])
        self.assertEqual(row["metrics"]["state_freshness_ms"], 4.5)
        self.assertNotIn("NaN", completed.stdout)
        self.assertNotIn("Infinity", completed.stdout)

    def test_failed_execution_suppresses_pugh_ranking(self):
        rows = [
            {"template": "B", "topology": "bridge", "scenario": "S0", "rmw": "cyclone",
             "status": "ok", "metrics": {"control_p99_ms": 1.0, "state_freshness_ms": 1.0,
             "sensor_drop_pct": 1.0}},
            {"template": "B", "topology": "bridge", "scenario": "S0", "rmw": "fastdds",
             "status": "failed", "reasons": ["probe_timeout"], "metrics": {"control_p99_ms": None}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            self.assertEqual(pugh.main([directory]), 0)
            report = (Path(directory) / "pugh.md").read_text(encoding="utf-8")
        self.assertIn("Ranking suppressed", report)
        self.assertNotIn("**Ranking:**", report)


if __name__ == "__main__":
    unittest.main()
