#!/usr/bin/env python3
"""Evidence-aware weighted Pugh scorer for Lab 4."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parent))
import benchmark_defs
from report_utils import groups, legacy, requested_rmws, source_label, status, value_for, finite, required_criteria

NEUTRAL = 3.0

def load_results(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(x) for x in fh if x.strip()]

def normalize(values, better):
    if len(values) < 2 or len(set(values.values())) < 2: return {k: NEUTRAL for k in values}
    lo, hi = min(values.values()), max(values.values()); span = hi - lo
    return {k: 1 + 4 * ((v - lo) / span if better == "higher" else (hi - v) / span) for k, v in values.items()}

def manual_value(manual, template, scenario, rmw, criterion):
    node = manual.get(template, {}) if isinstance(manual, dict) else {}
    inherited = False
    if scenario in node and isinstance(node[scenario], dict): node = node[scenario]
    else: inherited = True
    value = node.get(rmw, {}).get(criterion) if isinstance(node.get(rmw), dict) else None
    if value is None and inherited:
        old = manual.get(template, {}).get(rmw, {})
        value = old.get(criterion) if isinstance(old, dict) else None
    if value is None: return NEUTRAL, True, False
    if not finite(value) or not 1 <= float(value) <= 5: raise ValueError(f"manual score {template}/{scenario}/{rmw}/{criterion} must be 1-5")
    return float(value), False, inherited

def render(defs, template, scenario, rmws, rows, manual):
    criteria = required_criteria(defs, template); weights = defs["decision"]["weights"].get(template, {})
    measured = {}; blocked = []
    for rmw in rmws:
        matching = [r for r in rows if r.get("rmw") == rmw]
        if len(matching) != 1 or status(matching[0]) != "ok" or legacy(matching[0]): blocked.append(f"{rmw}: status/legacy")
        for criterion in criteria:
            if len(matching) != 1 or value_for(matching[0], template, criterion) is None: blocked.append(f"{rmw}: {criterion}")
    scores = {}; provisional = []; inherited = []
    for criterion, spec in criteria.items():
        vals = {r: value_for(next(x for x in rows if x.get("rmw") == r), template, criterion) for r in rmws if any(x.get("rmw") == r for x in rows) and value_for(next(x for x in rows if x.get("rmw") == r), template, criterion) is not None}
        scores[criterion] = normalize(vals, spec.get("better", "higher"))
    for criterion, spec in defs["decision"]["criteria"].items():
        if criterion in criteria: continue
        scores[criterion] = {}
        for rmw in rmws:
            value, is_provisional, is_inherited = manual_value(manual, template, scenario, rmw, criterion)
            scores[criterion][rmw] = value; provisional += [f"{rmw}/{criterion}"] if is_provisional else []
            inherited += [f"{rmw}/{criterion}"] if is_inherited and not is_provisional else []
    md = [f"## Template {template} — {defs['templates'][template]['name']} — Scenario {scenario}", "", "| Criterion | W | " + " | ".join(defs['rmws'].get(r, {}).get('label', r) for r in rmws) + " |", "|---|---:|" + "---|" * len(rmws)]
    totals = {r: 0.0 for r in rmws}
    for criterion, spec in defs["decision"]["criteria"].items():
        cells = []
        for rmw in rmws:
            score = scores[criterion].get(rmw, NEUTRAL); totals[rmw] += float(weights.get(criterion, 0)) * score; cells.append(f"{score:.1f}")
        is_manual = criterion not in criteria
        for index, rmw in enumerate(rmws):
            marker = "†" if f"{rmw}/{criterion}" in provisional else ("‡" if f"{rmw}/{criterion}" in inherited else "")
            cells[index] += marker
        tag = " *(manual)*" if is_manual else f" — {source_label(template, criterion)}"
        md.append(f"| {spec['label']}{tag} | {float(weights.get(criterion, 0)):.0f} | " + " | ".join(cells) + " |")
    md.append("| **Weighted total** | | " + " | ".join(f"**{totals[r]:.1f}**" for r in rmws) + " |")
    if blocked: md += ["", "**Ranking suppressed:** required measured evidence is incomplete: " + ", ".join(sorted(set(blocked))) + ".", "Available scores remain visible; missing evidence is not zero or neutral ranking evidence."]
    elif len(rmws) < 2 or len(set(totals.values())) < 2:
        md += ["", "**Ranking:** no ordering (singleton or tie)."]
    else:
        ranking = sorted(rmws, key=lambda r: totals[r], reverse=True); md += ["", "**Ranking:** " + ", ".join(f"{defs['rmws'].get(r, {}).get('label', r)} ({totals[r]:.1f})" for r in ranking)]
    md += ["", "† provisional neutral manual score; ‡ inherited legacy template-wide manual score.",
           "> Raw measurements belong in comparison.md first. Ties and singletons receive neutral normalization and provide no ordering; this report makes no statistical-significance claim.", ""]
    return "\n".join(md)

def main(argv):
    if not argv: print("usage: pugh.py <sweep_dir>", file=sys.stderr); return 2
    directory = argv[0]; path = os.path.join(directory, "results.jsonl")
    if not os.path.exists(path): return 1
    defs = benchmark_defs.load(); results = load_results(path); manual = {}
    manual_path = os.path.join(directory, "manual_scores.yaml")
    if os.path.exists(manual_path):
        with open(manual_path, encoding="utf-8") as fh: manual = yaml.safe_load(fh) or {}
    sections = ["# Weighted Pugh decision matrix", ""]
    for _, rows in groups(results):
        template, scenario = rows[0].get("template"), rows[0].get("scenario", "?")
        rmws = requested_rmws(rows, defs); rmws += [r["rmw"] for r in rows if r.get("rmw") not in rmws]
        if template in defs.get("templates", {}): sections.append(render(defs, template, scenario, rmws, rows, manual))
    Path(directory, "pugh.md").write_text("\n".join(sections) + "\n", encoding="utf-8"); print(f"wrote {Path(directory, 'pugh.md')}"); return 0
if __name__ == "__main__": raise SystemExit(main(sys.argv[1:]))
