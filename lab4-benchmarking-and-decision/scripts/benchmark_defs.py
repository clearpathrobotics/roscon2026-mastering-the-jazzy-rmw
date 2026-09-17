#!/usr/bin/env python3
"""Accessor for the Lab 4 benchmark configuration.

Single reader of the taxonomy. Importable as a module by the analysis tools
(comparison.py, pugh.py) and usable as a tiny CLI so bash (workshop.sh) can
query templates / scenarios / RMWs without embedding a YAML parser.

CLI examples:
    benchmark_defs.py rmw-impl cyclone        -> rmw_cyclonedds_cpp
    benchmark_defs.py rmw-label cyclone       -> Cyclone DDS
    benchmark_defs.py rmws                     -> cyclone fastdds zenoh
    benchmark_defs.py templates                -> A B
    benchmark_defs.py scenarios B              -> S0 S1 S2 S3 constrained
    benchmark_defs.py harness-executor A       -> synthetic
    benchmark_defs.py harness-profile B        -> fleet
    benchmark_defs.py harness-topology A       -> bridge
    benchmark_defs.py harness-workload B       -> bag
    benchmark_defs.py harness-impairment B     -> per_replica_netem
    benchmark_defs.py netem S2                 -> heavy
    benchmark_defs.py netem-link-rate S3       -> 20mbit
    benchmark_defs.py allowed B S2             -> exit 0 (legal) / 1 (illegal)
    benchmark_defs.py classes                  -> sensor control state
"""
from __future__ import annotations

import os
import json
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
CONTAINER_CONFIG = "/scripts/lab4/benchmark.yaml"
HOST_CONFIG = os.path.join(HERE, "benchmark.yaml")
DEFAULT_CONFIG = CONTAINER_CONFIG if os.path.isfile(CONTAINER_CONFIG) else HOST_CONFIG


def load(path: str | None = None) -> dict:
    """Load and return the parsed taxonomy."""
    target = path or os.environ.get("BENCHMARK_CONFIG", DEFAULT_CONFIG)
    with open(target, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# --- accessors ---------------------------------------------------------------
def rmw_impl(defs: dict, rmw: str) -> str:
    return defs["rmws"][rmw]["impl"]


def rmw_label(defs: dict, rmw: str) -> str:
    return defs["rmws"][rmw]["label"]


def rmw_zenoh_config(defs: dict, rmw: str) -> str:
    """Container path of the Zenoh session config for this RMW variant, or ''."""
    return defs["rmws"].get(rmw, {}).get("zenoh_config", "") or ""


def template_scenarios(defs: dict, template: str) -> list[str]:
    return list(defs["templates"][template].get("scenarios", []))


def template_harness_field(defs: dict, template: str, field: str) -> str:
    """Return one required execution-contract value for a template."""
    return str(defs["templates"][template]["harness"][field])


def scenario_netem(defs: dict, scenario: str) -> str:
    """Profile name from lab2-on-the-wire/scripts/netem_profile.sh, or 'none'."""
    return defs["scenarios"][scenario].get("netem", "none")


def scenario_netem_link_rate(defs: dict, scenario: str) -> str:
    """Optional LINK_RATE cap layered on top of the netem profile (e.g. '20mbit'), or ''."""
    return defs["scenarios"][scenario].get("netem_link_rate", "") or ""


def scenario_scales(defs: dict, scenario: str) -> list[int]:
    return [int(value) for value in defs["scenarios"][scenario].get("scale", [])]


def scenario_allowed(defs: dict, template: str, scenario: str) -> bool:
    """A scenario is legal for a template if the template lists it and (when the
    scenario constrains templates) the template is in that constraint."""
    if scenario not in template_scenarios(defs, template):
        return False
    limited = defs["scenarios"][scenario].get("templates")
    return template in limited if limited else True


def resolve_cells(defs: dict, templates: list[str], scenarios: str | None,
                  rmws: list[str], scale: int) -> list[dict]:
    """Resolve the user-facing matrix into concrete, executable cells.

    This is deliberately pure: it only reads the benchmark taxonomy and the
    requested values.  Docker setup, bags, and capture directories belong to
    the runner, not to scenario resolution.
    """
    known_templates = list(defs.get("templates", {}))
    known_rmws = list(defs.get("rmws", {}))
    for template in templates:
        if template not in known_templates:
            raise ValueError(f"unknown template: {template}")
    for rmw in rmws:
        if rmw not in known_rmws:
            raise ValueError(f"unknown RMW: {rmw}")
    if not templates or not rmws:
        raise ValueError("templates and RMWs must not be empty")
    if scale < 1:
        raise ValueError("scale must be a positive integer")

    requested = None if scenarios in (None, "") else scenarios.split(",")
    if requested == ["all"]:
        requested = None
        all_configured = True
    else:
        all_configured = False

    cells = []
    for template in templates:
        scenario_names = (template_scenarios(defs, template)
                          if all_configured else (requested or ["S0"]))
        if not scenario_names:
            raise ValueError(f"template {template} has no configured scenarios")
        for scenario in scenario_names:
            if scenario not in defs.get("scenarios", {}):
                raise ValueError(f"unknown scenario: {scenario}")
            if not scenario_allowed(defs, template, scenario):
                raise ValueError(f"unsupported template/scenario combination: {template}/{scenario}")
            executor = template_harness_field(defs, template, "executor")
            topology = template_harness_field(defs, template, "topology")
            workload = template_harness_field(defs, template, "workload")
            impairment = template_harness_field(defs, template, "impairment")
            if executor == "synthetic" and scenario != "S0":
                raise ValueError(f"unsupported impairment for Template A: {template}/{scenario}")
            if template == "A":
                scales = [2]
                scale_source = "template-a-pair"
            elif scenario == "S1":
                scales = list(defs["scenarios"][scenario].get("scale", []))
                if not scales:
                    raise ValueError("S1 has no configured replica scales")
                scale_source = "scenario-config"
            else:
                scales = [scale]
                scale_source = "cli"
            for cell_scale in scales:
                for rmw in rmws:
                    cells.append({
                        "template": template, "scenario": scenario, "rmw": rmw,
                        "scale": int(cell_scale), "scale_source": scale_source,
                        "executor": executor, "topology": topology,
                        "workload": workload, "impairment": impairment,
                        "netem": scenario_netem(defs, scenario),
                        "link_rate": scenario_netem_link_rate(defs, scenario),
                    })
    return cells


# --- CLI ---------------------------------------------------------------------
def _die(msg: str, code: int = 2) -> "None":
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def main(argv: list[str]) -> int:
    if not argv:
        _die("usage: benchmark_defs.py <query> [args]")
    defs = load()
    query, rest = argv[0], argv[1:]

    try:
        if query == "rmws":
            print(" ".join(defs["rmws"]))
        elif query == "templates":
            print(" ".join(defs["templates"]))
        elif query == "classes":
            print(" ".join(defs["topic_classes"]))
        elif query == "scenarios":
            print(" ".join(template_scenarios(defs, rest[0])))
        elif query == "rmw-impl":
            print(rmw_impl(defs, rest[0]))
        elif query == "rmw-label":
            print(rmw_label(defs, rest[0]))
        elif query == "rmw-zenoh-config":
            print(rmw_zenoh_config(defs, rest[0]))
        elif query == "harness-executor":
            print(template_harness_field(defs, rest[0], "executor"))
        elif query == "harness-profile":
            print(template_harness_field(defs, rest[0], "compose_profile"))
        elif query == "harness-topology":
            print(template_harness_field(defs, rest[0], "topology"))
        elif query == "harness-workload":
            print(template_harness_field(defs, rest[0], "workload"))
        elif query == "harness-impairment":
            print(template_harness_field(defs, rest[0], "impairment"))
        elif query == "netem":
            print(scenario_netem(defs, rest[0]))
        elif query == "netem-link-rate":
            print(scenario_netem_link_rate(defs, rest[0]))
        elif query == "scenario-scales":
            print(" ".join(str(x) for x in scenario_scales(defs, rest[0])))
        elif query == "allowed":
            return 0 if scenario_allowed(defs, rest[0], rest[1]) else 1
        elif query == "plan":
            if len(rest) != 4:
                _die("query 'plan' needs templates, scenarios, RMWs, scale")
            cells = resolve_cells(defs, [x for x in rest[0].split(",") if x],
                                  rest[1] or None, [x for x in rest[2].split(",") if x],
                                  int(rest[3]))
            for cell in cells:
                print(json.dumps(cell, sort_keys=True))
        else:
            _die(f"unknown query: {query}")
    except (KeyError, ValueError) as exc:
        _die(f"not found: {exc}")
    except IndexError:
        _die(f"query '{query}' needs more arguments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
