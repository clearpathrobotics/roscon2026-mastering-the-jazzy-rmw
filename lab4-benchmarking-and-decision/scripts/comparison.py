#!/usr/bin/env python3
"""Evidence-aware Markdown and CSV comparison reports."""
from __future__ import annotations
import csv, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import benchmark_defs
from report_utils import compatibility_key, evidence_note, groups, requested_rmws, source_label, status, value_for

NOTES = {
    "A": {"latency_p99": "service round-trip time",
          "data_freshness": "generated pub/sub latency; not source-timestamp age",
          "reliability": "worst observed generated pub/sub latency",
          "throughput_eff": "received generated rate"},
    "B": {"latency_p99": "observed arrival gap; not source-timestamp latency",
          "data_freshness": "longest observed silence, including window boundaries",
          "reliability": "metadata-based estimate; not packet loss",
          "throughput_eff": "received sensor payload rate"},
}
CPU_NOTE = "receiver workload CPU; not isolated middleware overhead"

def load_results(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]

def fmt(value):
    if value is None: return "—"
    return f"{value:.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)

def build(results, defs):
    md = ["# Cross-RMW comparison", "", "Raw observed values are shown first. A dash means missing evidence, never zero.", ""]
    csv_rows = [["group", "repeat", "template", "topology", "scenario", "scale", "workload", "config_identity", "rmw", "status", "metric", "value", "coverage", "limitation"]]
    grouped = groups(results)
    for group_no, (_, rows) in enumerate(grouped, 1):
        template = rows[0].get("template", "?"); topology = rows[0].get("topology", "bridge"); scenario = rows[0].get("scenario", "?")
        rmws = requested_rmws(rows, defs); rmws += [r["rmw"] for r in rows if r.get("rmw") not in rmws]
        criteria = list(defs["decision"]["criteria"])
        md += [f"## Group {group_no}: Template {template} — {defs.get('templates', {}).get(template, {}).get('name', template)} — {topology} — Scenario {scenario}", "",
               f"Settings: scale={rows[0].get('scale','—')}; workload={rows[0].get('workload','—')}; duration={rows[0].get('duration','—')}; repeated cells are listed separately.", ""]
        header = ["Metric"] + [defs.get("rmws", {}).get(r, {}).get("label", r) for r in rmws] + ["Notes / interpretation"]
        md += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        for criterion in criteria:
            vals = []
            for rmw in rmws:
                candidates = [r for r in rows if r.get("rmw") == rmw]
                vals.append(fmt(value_for(candidates[0], template, criterion)) if len(candidates) == 1 else ("—" if not candidates else "see cells below"))
            note = CPU_NOTE if criterion == "cpu_overhead" else NOTES.get(template, {}).get(criterion, "")
            md.append("| " + source_label(template, criterion, defs) + " | " + " | ".join(vals) + " | " + note + " |")
        md += ["", "### Cells and coverage", "", "| Repeat | RMW | Status | " + " | ".join(source_label(template, c, defs) for c in criteria) + " |", "|---:|---|---|" + "---|" * len(criteria)]
        for repeat, row in enumerate(rows, 1):
            cells = []
            for criterion in criteria:
                source_value = value_for(row, template, criterion); source = criterion
                cells.append(f"{fmt(source_value)} ({'available' if source_value is not None else evidence_note(row, source)})")
                csv_rows.append([group_no, repeat, template, topology, scenario, row.get("scale"), row.get("workload"), row.get("bag_id") or row.get("config_id") or row.get("provenance", {}).get("bag_directory", ""), row.get("rmw"), status(row), criterion, "" if source_value is None else fmt(source_value), "available" if source_value is not None else "missing", "; ".join(row.get("instrumentation_limitations", []))])
            md.append("| " + str(repeat) + " | " + str(row.get("rmw", "?")) + " | " + status(row) + " | " + " | ".join(cells) + " |")
        if scenario != "S0":
            baseline = []
            for _, candidate_rows in grouped:
                for candidate in candidate_rows:
                    probe = dict(rows[0]); probe["scenario"] = "S0"
                    if candidate.get("scenario") == "S0" and compatibility_key(candidate) == compatibility_key(probe):
                        baseline.append(candidate)
            if baseline:
                md += ["", "### Raw S0-to-stressed deltas", "", "| RMW | Criterion | Delta (stressed − S0) | Percentage delta |", "|---|---|---:|---:|"]
                for row in rows:
                    matching = [b for b in baseline if b.get("rmw") == row.get("rmw")]
                    if len(matching) != 1: continue
                    for criterion in criteria:
                        current = value_for(row, template, criterion); base = value_for(matching[0], template, criterion)
                        delta = current - base if isinstance(current, (int,float)) and isinstance(base, (int,float)) else None
                        pct = ((delta / base) * 100) if delta is not None and base != 0 else None
                        md.append(f"| {row.get('rmw')} | {source_label(template, criterion, defs)} | {fmt(delta)} | {fmt(pct) if pct is not None else '— (baseline zero/missing)'} |")
        md += ["", "Missing evidence is not favourable performance. Legacy rows are historical and unverified; no statistical-significance claim is made.", ""]
    return "\n".join(md), csv_rows

def main(argv):
    if not argv: print("usage: comparison.py <sweep_dir|results.jsonl>", file=sys.stderr); return 2
    target = argv[0]; path = os.path.join(target, "results.jsonl") if os.path.isdir(target) else target
    if not os.path.exists(path): print(f"no results file: {path}", file=sys.stderr); return 1
    results = load_results(path)
    if not results: return 1
    md, rows = build(results, benchmark_defs.load()); out = os.path.dirname(os.path.abspath(path))
    Path(out, "comparison.md").write_text(md + "\n", encoding="utf-8")
    with open(Path(out, "comparison.csv"), "w", newline="", encoding="utf-8") as fh: csv.writer(fh).writerows(rows)
    print(f"wrote {Path(out, 'comparison.md')}"); print(f"wrote {Path(out, 'comparison.csv')}"); return 0
if __name__ == "__main__": raise SystemExit(main(sys.argv[1:]))
