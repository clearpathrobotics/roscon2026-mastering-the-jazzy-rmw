#!/usr/bin/env python3
"""Evidence-aware raw-value plots; missing measurements are not zero."""
from __future__ import annotations
import json, math, os, sys
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, str(Path(__file__).resolve().parent))
import benchmark_defs
from report_utils import groups, requested_rmws, source_label, template_metric_sources, value_for

COLORS = {"cyclone": "tab:blue", "fastdds": "tab:orange", "zenoh": "tab:green", "zenoh-lowlat": "tab:red"}

def main(argv):
    if not argv: print("usage: plot_comparison.py <sweep_dir>", file=sys.stderr); return 2
    directory = argv[0]; path = os.path.join(directory, "results.jsonl")
    if not os.path.exists(path): return 1
    defs = benchmark_defs.load()
    with open(path, encoding="utf-8") as fh: results = [json.loads(x) for x in fh if x.strip()]
    criteria = list(defs["decision"]["criteria"]); grouped = groups(results)
    templates = list(dict.fromkeys(row.get("template") for row in results))
    panels = [(template, criterion) for template in templates for criterion in criteria
              if criterion in template_metric_sources(template)]
    fig, axes = plt.subplots((len(panels)+1)//2, 2, figsize=(14, 3.8*((len(panels)+1)//2)), squeeze=False); axes = axes.flat
    for mi, (panel_template, criterion) in enumerate(panels):
        ax = axes[mi]; labels=[]; panel_groups=[]; all_rmws=[]
        for group_no, (_, rows) in enumerate(grouped, 1):
            template=rows[0].get("template"); scenario=rows[0].get("scenario", "?"); rmws=requested_rmws(rows, defs); rmws += [r["rmw"] for r in rows if r.get("rmw") not in rmws]
            if template != panel_template: continue
            labels.append(f"G{group_no}/{scenario}"); panel_groups.append(rows); all_rmws.extend(rmws)
        width=0.8/max(1,len(set(all_rmws)))
        unique=list(dict.fromkeys(all_rmws))
        for si, rmw in enumerate(unique):
            vals=[]
            for rows in panel_groups:
                candidates=[row for row in rows if row.get("rmw")==rmw]
                value=value_for(candidates[0], panel_template, criterion) if len(candidates)==1 else None
                vals.append(value if isinstance(value,(int,float)) and math.isfinite(value) else float("nan"))
            x=list(range(len(labels))); offset=(si-(len(unique)-1)/2)*width
            bars=ax.bar([v+offset for v in x], vals, width, label=defs.get("rmws",{}).get(rmw,{}).get("label",rmw), color=COLORS.get(rmw), edgecolor="black")
            for bar, value in zip(bars, vals):
                if not math.isfinite(value): bar.set_hatch("//"); bar.set_facecolor("white"); bar.set_label("_nolegend_"); ax.text(bar.get_x()+bar.get_width()/2, 0, "n/a", ha="center", va="bottom", fontsize=7)
        ax.set_title(f"Template {panel_template}: {source_label(panel_template, criterion)} (raw; missing=n/a)"); ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8); ax.grid(axis="y", alpha=.3)
        if mi==0: ax.legend(fontsize=8)
    for ax in list(axes)[len(panels):]: ax.axis("off")
    fig.suptitle("RMW comparison — raw observed values; no significance claim"); fig.tight_layout(rect=(0,0,1,.96)); fig.savefig(os.path.join(directory,"comparison.png"), dpi=130); plt.close(fig); print(f"wrote {os.path.join(directory,'comparison.png')}"); return 0
if __name__ == "__main__": raise SystemExit(main(sys.argv[1:]))
