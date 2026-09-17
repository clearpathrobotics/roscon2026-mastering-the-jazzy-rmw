"""Deterministic report and Pugh-scoring acceptance fixtures."""
from __future__ import annotations
import json, tempfile, unittest
from pathlib import Path
import benchmark_defs, comparison, pugh, plot_comparison
from report_utils import compatibility_key, groups

DEFS = benchmark_defs.load()

def row(rmw, *, scenario="S0", scale=3, value=10.0, status="ok", schema=2, bag="bag-a", repeat=None):
    return {"schema_version": schema, "template": "B", "topology": "bridge", "scenario": scenario,
            "rmw": rmw, "rmw_impl": rmw, "scale": scale, "workload": "bag", "engine": "mcap",
            "duration": 20, "bag_id": bag, "status": status, "requested_rmws": ["cyclone", "fastdds"],
            "metrics": {"sensor_estimated_delivery_shortfall_pct": value, "control_arrival_gap_p99_ms": value,
                        "state_max_silence_ms": value, "throughput_mbps": value, "cpu_pct": value}}

class ReportScoringTests(unittest.TestCase):
    def test_partition_preserves_duplicate_and_mismatched_scale_bag(self):
        rows = [row("cyclone"), row("cyclone"), row("fastdds", scale=1), row("fastdds", bag="bag-b")]
        self.assertEqual([len(items) for _, items in groups(rows)], [2, 1, 1])
        self.assertNotEqual(compatibility_key(rows[0]), compatibility_key(rows[2]))

    def test_runtime_namespaces_and_rmw_settings_do_not_split_candidates(self):
        rows = [row("cyclone"), row("fastdds")]
        for index, item in enumerate(rows, 1):
            item["provenance"] = {
                "metadata": {"sha256": "bag-hash"}, "storage_files": [{"sha256": "part-hash"}],
                "replica_namespaces": [f"/robot_{index}"], "image_ids": {f"/robot_{index}": "sha256:image"},
                "effective_settings": {"rmw": item["rmw"], "rmw_implementation": item["rmw"], "scenario": "S0"},
            }
        self.assertEqual(len(groups(rows)), 1)

    def test_missing_invalid_and_legacy_are_visible_and_block_ranking(self):
        rows = [row("cyclone", value=0.0), row("fastdds", status="ok")]
        rows[1]["metrics"]["control_arrival_gap_p99_ms"] = None
        rows[1]["metrics"]["state_max_silence_ms"] = float("nan")
        rows[1]["metrics"]["sensor_estimated_delivery_shortfall_pct"] = None
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"; path.write_text("\n".join(json.dumps(x, allow_nan=True) for x in rows) + "\n")
            self.assertEqual(pugh.main([directory]), 0)
            report = (Path(directory) / "pugh.md").read_text()
            self.assertIn("Ranking suppressed", report); self.assertIn("Available scores remain visible", report)
            rows[1]["schema_version"] = 1; rows[1]["status"] = "ok"
            md, csv_rows = comparison.build(rows, DEFS)
            self.assertIn("legacy/unverified", md); self.assertTrue(any(r[-2] == "missing" for r in csv_rows[1:]))

    def test_ties_and_singletons_are_neutral_and_manual_scores_are_scenario_specific(self):
        rows = [row("cyclone", scenario="S2", value=5.0), row("fastdds", scenario="S2", value=5.0)]
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "results.jsonl").write_text("\n".join(json.dumps(x) for x in rows) + "\n")
            Path(directory, "manual_scores.yaml").write_text("B:\n  S2:\n    cyclone:\n      ease_config: 5\n    fastdds:\n      ease_config: 1\n")
            pugh.main([directory]); report = Path(directory, "pugh.md").read_text()
        self.assertIn("5.0", report); self.assertIn("1.0", report); self.assertIn("3.0", report)
        self.assertIn("†", report)
        self.assertEqual(pugh.normalize({"cyclone": 2.0}, "lower"), {"cyclone": 3.0})

    def test_plot_and_csv_keep_missing_as_missing(self):
        rows = [row("cyclone", value=2.0), row("fastdds", status="invalid", value=None)]
        rows[1]["metrics"]["control_arrival_gap_p99_ms"] = None
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "results.jsonl").write_text("\n".join(json.dumps(x) for x in rows) + "\n")
            comparison.main([directory]); self.assertTrue(plot_comparison.main([directory]) == 0)
            csv_text = Path(directory, "comparison.csv").read_text()
            self.assertIn(",missing,", csv_text); self.assertTrue(Path(directory, "comparison.png").stat().st_size > 0)

    def test_raw_delta_omits_percent_when_baseline_zero(self):
        rows = [row("cyclone", value=0.0), row("cyclone", scenario="S2", value=4.0)]
        md, _ = comparison.build(rows, DEFS)
        self.assertIn("Raw S0-to-stressed deltas", md); self.assertIn("baseline zero/missing", md)

    def test_manual_criteria_use_display_label_not_raw_key(self):
        md, _ = comparison.build([row("cyclone")], DEFS)
        self.assertNotIn("ease_config", md); self.assertNotIn("discovery_robust", md); self.assertNotIn("loss_jitter_behaviour", md)
        self.assertIn("Ease of config & debugging", md); self.assertIn("Discovery / connectivity robustness", md)

    def test_template_a_notes_do_not_claim_delivery_shortfall_or_freshness(self):
        item = row("cyclone")
        item.update(template="A", workload="synthetic", scale=2,
                    template_a_metrics={"service_rtt_p99_ms": 1.0,
                                        "pubsub_latency_mean_ms": 2.0,
                                        "pubsub_latency_max_ms": 3.0,
                                        "pubsub_received_hz": 4.0})
        md, _ = comparison.build([item], DEFS)
        self.assertIn("worst observed generated pub/sub latency", md)
        self.assertNotIn("delivery shortfall (estimated for Template B)", md)
        self.assertNotIn("template-specific freshness", md)

if __name__ == "__main__": unittest.main()
