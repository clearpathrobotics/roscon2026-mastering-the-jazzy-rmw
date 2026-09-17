#!/usr/bin/env python3
"""Offline top-down world-map renderer for ``dynamic_image_publisher``.

Renders a top-down (orthographic, looking down ``-Z``) background image of the mock
"world" — the four walls + interior box defined in
``urdf_raycast_sensors/urdf/demo_walls.urdf.xacro`` — so the runtime node can blit the
robot sprite onto it. Dev-time tool: run once (inside ``ubuntu-sprite-render``) and
commit the result; the runtime node just loads the PNG + JSON.

Boxes are drawn as their oriented top-view footprints (4 corners projected to pixels),
filled with each visual's URDF material colour, on a light "floor" background. The
output metadata JSON records ``meters_per_pixel`` and the pixel coordinate of the world
origin so the runtime overlay can map any ``world`` (x, y) to a pixel:

    col = origin_px[0] - y / meters_per_pixel      # +Y (left) -> left
    row = origin_px[1] - x / meters_per_pixel      # +X (forward) -> up

This matches the sprite convention (robot forward = up), so the sprite scales and
places consistently against the map.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np


# --------------------------------------------------------------------------- #
# URDF parsing helpers (shared conventions with render_sprites.py)
# --------------------------------------------------------------------------- #
def _rpy_to_matrix(roll: float, pitch: float, yaw: float) -> np.ndarray:
    """URDF (roll, pitch, yaw) -> 3x3 rotation matrix (Rz @ Ry @ Rx)."""
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], dtype=float)
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], dtype=float)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]], dtype=float)
    return rz @ ry @ rx


def _origin_to_matrix(origin) -> np.ndarray:
    """urdf_parser_py Pose (xyz + rpy) -> 4x4 homogeneous transform."""
    mat = np.eye(4, dtype=float)
    if origin is None:
        return mat
    xyz = getattr(origin, "xyz", None) or [0.0, 0.0, 0.0]
    rpy = getattr(origin, "rpy", None) or [0.0, 0.0, 0.0]
    mat[:3, :3] = _rpy_to_matrix(*(float(v) for v in rpy))
    mat[:3, 3] = [float(v) for v in xyz]
    return mat


def _link_root_transforms(robot) -> Dict[str, np.ndarray]:
    """Transform of every link relative to the URDF root (joints at zero config)."""
    parent_of: Dict[str, str] = {}
    joint_tf: Dict[str, np.ndarray] = {}
    for joint in robot.joints:
        parent_of[joint.child] = joint.parent
        joint_tf[joint.child] = _origin_to_matrix(joint.origin)

    transforms: Dict[str, np.ndarray] = {}

    def resolve(link_name: str) -> np.ndarray:
        if link_name in transforms:
            return transforms[link_name]
        parent = parent_of.get(link_name)
        transforms[link_name] = (
            np.eye(4) if parent is None else resolve(parent) @ joint_tf[link_name]
        )
        return transforms[link_name]

    for link in robot.links:
        resolve(link.name)
    return transforms


def _iter_visuals(link):
    """Yield visual elements for a link across urdf_parser_py versions."""
    visuals = getattr(link, "visuals", None)
    if visuals:
        yield from visuals
        return
    single = getattr(link, "visual", None)
    if single is not None:
        yield single


def _material_colors(robot) -> Dict[str, np.ndarray]:
    """Map top-level URDF material name -> RGBA (0..1) float array."""
    colors: Dict[str, np.ndarray] = {}
    for material in getattr(robot, "materials", []) or []:
        color = getattr(material, "color", None)
        if color is not None and getattr(color, "rgba", None) is not None:
            colors[material.name] = np.asarray(color.rgba, dtype=float)
    return colors


def _expand_xacro(urdf_xacro: Path) -> str:
    """Run ``xacro`` and return the expanded URDF XML string."""
    result = subprocess.run(
        ["xacro", str(urdf_xacro)], capture_output=True, text=True, check=True
    )
    return result.stdout


# --------------------------------------------------------------------------- #
# Box footprint extraction
# --------------------------------------------------------------------------- #
class Footprint:
    """An oriented box top-view footprint in the world frame."""

    def __init__(self, corners_xy: np.ndarray, rgba: np.ndarray) -> None:
        self.corners_xy = corners_xy  # (4, 2)
        self.rgba = rgba              # (4,) 0..1


def collect_footprints(
    urdf_xml: str,
    root_link: str,
) -> List[Footprint]:
    """Extract oriented box footprints (world XY) with colour from URDF visuals."""
    from urdf_parser_py.urdf import URDF, Box as UrdfBox

    robot = URDF.from_xml_string(urdf_xml)
    link_tf = _link_root_transforms(robot)
    mat_colors = _material_colors(robot)

    if root_link not in link_tf:
        raise RuntimeError(
            f"root_link '{root_link}' not found. Links: {sorted(link_tf)}"
        )
    root_inv = np.linalg.inv(link_tf[root_link])

    # Local top-view corners (unit box, scaled per-box below).
    unit = np.array(
        [[0.5, 0.5], [0.5, -0.5], [-0.5, -0.5], [-0.5, 0.5]], dtype=float
    )

    footprints: List[Footprint] = []
    for link in robot.links:
        link_world = root_inv @ link_tf.get(link.name, np.eye(4))
        for visual in _iter_visuals(link):
            geometry = getattr(visual, "geometry", None)
            if not isinstance(geometry, UrdfBox):
                continue
            size = np.asarray(geometry.size, dtype=float).reshape(3)
            box_world = link_world @ _origin_to_matrix(getattr(visual, "origin", None))
            rot = box_world[:2, :2]        # top-view (XY) rotation
            center = box_world[:2, 3]
            corners = (unit * size[:2].reshape(1, 2)) @ rot.T + center.reshape(1, 2)

            rgba = np.array([0.6, 0.6, 0.6, 1.0])
            material = getattr(visual, "material", None)
            if material is not None:
                own = getattr(material, "color", None)
                if own is not None and getattr(own, "rgba", None) is not None:
                    rgba = np.asarray(own.rgba, dtype=float)
                elif getattr(material, "name", None) in mat_colors:
                    rgba = mat_colors[material.name]
            footprints.append(Footprint(corners, rgba))

    if not footprints:
        raise RuntimeError("No box visual geometry found to render.")
    return footprints


# --------------------------------------------------------------------------- #
# Rasterization
# --------------------------------------------------------------------------- #
def render_world(
    footprints: List[Footprint],
    meters_per_pixel: float,
    padding_px: int,
    supersample: int,
    floor_color: Tuple[int, int, int],
    edge_color: Optional[Tuple[int, int, int]],
) -> Tuple["object", Dict[str, float]]:
    """Rasterize box footprints into an RGB world map + metadata dict."""
    from PIL import Image, ImageDraw

    all_xy = np.concatenate([f.corners_xy for f in footprints], axis=0)
    x_min, x_max = float(all_xy[:, 0].min()), float(all_xy[:, 0].max())
    y_min, y_max = float(all_xy[:, 1].min()), float(all_xy[:, 1].max())

    mpp = meters_per_pixel
    pad = padding_px
    width = int(np.ceil((y_max - y_min) / mpp)) + 2 * pad
    height = int(np.ceil((x_max - x_min) / mpp)) + 2 * pad

    # Pixel of the world origin (x=y=0); runtime maps any (x, y) from these.
    origin_col = (y_max - 0.0) / mpp + pad
    origin_row = (x_max - 0.0) / mpp + pad

    def to_pixel(xy: np.ndarray) -> List[Tuple[float, float]]:
        # +X world -> up (row decreases); +Y world -> left (col decreases).
        cols = origin_col - xy[:, 1] / mpp
        rows = origin_row - xy[:, 0] / mpp
        return [(float(c), float(r)) for c, r in zip(cols, rows)]

    ss = max(int(supersample), 1)
    canvas = Image.new(
        "RGBA", (width * ss, height * ss),
        (floor_color[0], floor_color[1], floor_color[2], 255),
    )
    draw = ImageDraw.Draw(canvas)

    for fp in footprints:
        poly = [(c * ss, r * ss) for c, r in to_pixel(fp.corners_xy)]
        fill = (
            int(np.clip(fp.rgba[0] * 255, 0, 255)),
            int(np.clip(fp.rgba[1] * 255, 0, 255)),
            int(np.clip(fp.rgba[2] * 255, 0, 255)),
            255,
        )
        outline = tuple(edge_color) if edge_color is not None else None
        draw.polygon(poly, fill=fill, outline=outline, width=max(ss, 1))

    if ss > 1:
        canvas = canvas.resize((width, height), Image.LANCZOS)

    meta = {
        "meters_per_pixel": mpp,
        "width": width,
        "height": height,
        "origin_px": [origin_col, origin_row],
        "forward_axis": "up",
        "left_axis": "left",
        "x_range": [x_min, x_max],
        "y_range": [y_min, y_max],
    }
    return canvas.convert("RGB"), meta


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--world-xacro",
        type=Path,
        default=Path("/ws/src/urdf_raycast_sensors/urdf/demo_walls.urdf.xacro"),
        help="Path to the world description xacro (walls + obstacles).",
    )
    parser.add_argument(
        "--root-link",
        default="world",
        help="Root link the map is expressed in (default: world).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/ws/src/dynamic_image_publisher/assets/world"),
        help="Where to write world.png and world.json.",
    )
    parser.add_argument(
        "--name", default="world", help="Output basename (default: world)."
    )
    parser.add_argument(
        "--meters-per-pixel",
        type=float,
        default=0.01,
        help="World metres per output pixel (must match the sprite renderer).",
    )
    parser.add_argument("--padding-px", type=int, default=20)
    parser.add_argument("--supersample", type=int, default=4)
    parser.add_argument(
        "--floor-color",
        type=int,
        nargs=3,
        metavar=("R", "G", "B"),
        default=[235, 235, 235],
        help="Background floor RGB (0..255).",
    )
    parser.add_argument(
        "--edge-color",
        type=int,
        nargs=3,
        metavar=("R", "G", "B"),
        default=[60, 60, 60],
        help="Box outline RGB (0..255). Use -1 -1 -1 to disable.",
    )
    args = parser.parse_args()

    edge_color: Optional[Tuple[int, int, int]] = tuple(args.edge_color)
    if edge_color == (-1, -1, -1):
        edge_color = None

    try:
        print(f"[world] expanding {args.world_xacro.name}")
        urdf_xml = _expand_xacro(args.world_xacro)
        print(f"[world] collecting box footprints (root_link='{args.root_link}')")
        footprints = collect_footprints(urdf_xml, args.root_link)
        print(f"[world] {len(footprints)} footprint(s)")
        image, meta = render_world(
            footprints,
            args.meters_per_pixel,
            args.padding_px,
            args.supersample,
            tuple(args.floor_color),
            edge_color,
        )
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"[world] FAILED: {exc}", file=sys.stderr)
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    png_path = args.output_dir / f"{args.name}.png"
    json_path = args.output_dir / f"{args.name}.json"
    npy_path = args.output_dir / f"{args.name}.npy"
    image.save(png_path)
    # Raw RGB array for the runtime node (no image codec needed at runtime).
    np.save(npy_path, np.asarray(image.convert("RGB"), dtype=np.uint8))
    json_path.write_text(json.dumps(meta, indent=2))
    print(
        f"[world] wrote {png_path} ({meta['width']}x{meta['height']}) "
        f"+ {json_path.name} + {npy_path.name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
