#!/usr/bin/env python3
"""Validate a rosbag2 directory and build Lab 4's expected workload inventory.

This module is deliberately independent of the ROS graph.  The bag metadata is
the source of workload truth; replica namespaces are supplied by the runner
after Docker has created the actual replicas.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml


class InventoryError(ValueError):
    """An input cannot describe one replayable, self-consistent bag."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_bag_directory(raw: str | os.PathLike[str]) -> Path:
    """Resolve exactly one bag directory, rejecting missing/ambiguous input."""
    path = Path(raw).expanduser()
    if not path.exists():
        raise InventoryError(f"bag path does not exist: {path}")
    if not path.is_dir():
        raise InventoryError(f"bag path is not a directory: {path}")
    if (path / "metadata.yaml").is_file():
        return path.resolve()
    candidates = sorted(p for p in path.iterdir() if p.is_dir() and (p / "metadata.yaml").is_file())
    if not candidates:
        raise InventoryError(f"no bag directory with metadata.yaml found under: {path}")
    if len(candidates) != 1:
        names = ", ".join(str(p) for p in candidates)
        raise InventoryError(f"ambiguous bag selection; expected one directory, found: {names}")
    return candidates[0].resolve()


def _info(metadata_path: Path) -> dict[str, Any]:
    try:
        document = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise InventoryError(f"cannot read bag metadata {metadata_path}: {exc}") from exc
    info = (document or {}).get("rosbag2_bagfile_information") if isinstance(document, dict) else None
    if not isinstance(info, dict):
        raise InventoryError("metadata.yaml lacks rosbag2_bagfile_information")
    return info


def inspect_bag(raw: str | os.PathLike[str]) -> dict[str, Any]:
    """Return hashes, storage files, duration, and topic counts from metadata."""
    bag = resolve_bag_directory(raw)
    metadata_path = bag / "metadata.yaml"
    info = _info(metadata_path)
    relative_files = info.get("relative_file_paths")
    if not isinstance(relative_files, list) or not relative_files or any(not isinstance(x, str) or not x for x in relative_files):
        raise InventoryError("metadata must list one or more relative_file_paths")
    if len(set(relative_files)) != len(relative_files):
        raise InventoryError("metadata lists duplicate storage files")

    files: list[dict[str, Any]] = []
    for relative in relative_files:
        candidate = (bag / relative).resolve()
        if Path(relative).is_absolute() or bag not in candidate.parents or not candidate.is_file():
            raise InventoryError(f"metadata-listed storage file is missing or escapes the bag: {relative}")
        files.append({"path": relative, "sha256": _sha256(candidate), "bytes": candidate.stat().st_size})

    listed = {(bag / x).resolve() for x in relative_files}
    extras = sorted(p.name for p in bag.iterdir() if p.is_file() and p.suffix in {".mcap", ".db3", ".bag"} and p.resolve() not in listed)
    if extras:
        raise InventoryError(f"storage files are not listed in metadata: {', '.join(extras)}")

    try:
        duration_ns = int(info["duration"]["nanoseconds"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InventoryError("metadata has no valid duration.nanoseconds") from exc
    if duration_ns < 0:
        raise InventoryError("bag duration cannot be negative")

    topics = info.get("topics_with_message_count")
    if not isinstance(topics, list) or not topics:
        raise InventoryError("metadata must list topics_with_message_count")
    topic_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in topics:
        meta = record.get("topic_metadata") if isinstance(record, dict) else None
        if not isinstance(meta, dict) or not isinstance(meta.get("name"), str) or not isinstance(meta.get("type"), str):
            raise InventoryError("each metadata topic needs a name and type")
        name = meta["name"]
        if not name.startswith("/") or name in seen:
            raise InventoryError(f"invalid or duplicate metadata topic: {name}")
        seen.add(name)
        try:
            count = int(record["message_count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InventoryError(f"invalid message count for topic {name}") from exc
        if count < 0:
            raise InventoryError(f"negative message count for topic {name}")
        topic_records.append({"name": name, "type": meta["type"], "count": count,
                              "serialization_format": meta.get("serialization_format"),
                              "offered_qos_profiles": meta.get("offered_qos_profiles", [])})

    return {
        "bag_directory": str(bag),
        "metadata": {"path": "metadata.yaml", "sha256": _sha256(metadata_path)},
        "storage_identifier": info.get("storage_identifier"),
        "storage_files": files,
        "duration_ns": duration_ns,
        "duration_s": duration_ns / 1e9,
        "topics": topic_records,
    }


def build_inventory(raw: str | os.PathLike[str], namespaces: list[str] | None = None,
                    image_ids: dict[str, str] | None = None, requested_replicas: int | None = None,
                    replay_rate: float = 1.0, qos: dict[str, Any] | None = None,
                    benchmark_config: str | None = None, benchmark: dict[str, Any] | None = None) -> dict[str, Any]:
    base = inspect_bag(raw)
    namespaces = namespaces or []
    if requested_replicas is not None and len(namespaces) != requested_replicas:
        raise InventoryError(f"requested {requested_replicas} replicas, found {len(namespaces)}")
    if len(set(namespaces)) != len(namespaces) or any(not n.startswith("/") for n in namespaces):
        raise InventoryError("replica namespaces must be unique absolute names")
    expected = []
    for namespace in namespaces:
        for topic in base["topics"]:
            expected.append({"topic": namespace.rstrip("/") + topic["name"],
                             "source_topic": topic["name"], "type": topic["type"], "replica": namespace,
                             "message_count": topic["count"]})
    base.update({
        "replay_rate": replay_rate,
        "qos": qos or {},
        "replica_namespaces": namespaces,
        "image_ids": image_ids or {},
        "requested_replicas": requested_replicas,
        "expected_topics": expected,
        "benchmark_config": benchmark_config,
        "benchmark": benchmark or {},
        "instrumentation_limitations": ["unknown message types are reported by the receiver probe"]
    })
    return base


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bag_dir")
    parser.add_argument("--namespaces-json", default="[]")
    parser.add_argument("--image-ids-json", default="{}")
    parser.add_argument("--requested-replicas", type=int)
    parser.add_argument("--rate", type=float, default=1.0)
    parser.add_argument("--qos-json", default="{}")
    parser.add_argument("--benchmark-config", default=None)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = build_inventory(args.bag_dir, json.loads(args.namespaces_json), json.loads(args.image_ids_json),
                                 args.requested_replicas, args.rate, json.loads(args.qos_json), args.benchmark_config)
    except (InventoryError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
