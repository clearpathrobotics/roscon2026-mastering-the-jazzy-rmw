"""Parse URDF collision geometry into oriented primitives for raycasting.

Uses the standard ROS ``urdf_parser_py`` package (rosdep key ``urdfdom_py``) to parse
the URDF rather than hand-rolling XML handling. Input is expected to be already-expanded
URDF XML (e.g. the output of ``xacro`` published on ``/robot_description``).

v1 supports ``box`` collision geometry. Each box link's collision origin is composed
with the chain of joints back to the root (at their zero configuration) so the box is
expressed in the URDF root frame. Cylinder/sphere and mesh links whose collision is a
supported primitive can be added here later without touching the node.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from .raycast import Box


def _rpy_to_matrix(roll: float, pitch: float, yaw: float) -> np.ndarray:
    """Convert URDF (roll, pitch, yaw) to a 3x3 rotation matrix (Rz @ Ry @ Rx)."""
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)

    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], dtype=float)
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], dtype=float)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]], dtype=float)
    return rz @ ry @ rx


def _origin_to_matrix(origin) -> np.ndarray:
    """Convert a urdf_parser_py ``Pose`` (xyz + rpy) to a 4x4 homogeneous transform."""
    mat = np.eye(4, dtype=float)
    if origin is None:
        return mat
    xyz = getattr(origin, "xyz", None) or [0.0, 0.0, 0.0]
    rpy = getattr(origin, "rpy", None) or [0.0, 0.0, 0.0]
    mat[:3, :3] = _rpy_to_matrix(*(float(v) for v in rpy))
    mat[:3, 3] = [float(v) for v in xyz]
    return mat


def _link_root_transforms(robot) -> Dict[str, np.ndarray]:
    """Compute each link's transform relative to the root via the joint chain.

    Joints are traversed at their zero configuration. For static walls plus a
    separately-tracked sensor link this yields the correct resting pose of every
    obstacle link in the root frame.
    """
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
        if parent is None:
            transforms[link_name] = np.eye(4, dtype=float)
        else:
            transforms[link_name] = resolve(parent) @ joint_tf[link_name]
        return transforms[link_name]

    for link in robot.links:
        resolve(link.name)
    return transforms


def _iter_collisions(link):
    """Yield collision elements for a link across urdf_parser_py versions."""
    collisions = getattr(link, "collisions", None)
    if collisions:
        yield from collisions
        return
    single = getattr(link, "collision", None)
    if single is not None:
        yield single


def boxes_from_urdf(
    urdf_xml: str,
    exclude_links: Optional[List[str]] = None,
) -> List[Box]:
    """Extract oriented boxes from a URDF string.

    Parameters
    ----------
    urdf_xml:
        The (xacro-expanded) URDF document as a string.
    exclude_links:
        Link names to skip (e.g. the sensor link itself).

    Returns
    -------
    list[Box]
        Boxes expressed in the URDF root frame.
    """
    from urdf_parser_py.urdf import URDF, Box as UrdfBox

    exclude = set(exclude_links or [])
    robot = URDF.from_xml_string(urdf_xml)
    link_tf = _link_root_transforms(robot)

    boxes: List[Box] = []
    for link in robot.links:
        if link.name in exclude:
            continue
        link_world = link_tf.get(link.name, np.eye(4))
        for collision in _iter_collisions(link):
            geometry = getattr(collision, "geometry", None)
            if not isinstance(geometry, UrdfBox):
                continue
            size = np.asarray(geometry.size, dtype=float).reshape(3)
            collision_world = link_world @ _origin_to_matrix(
                getattr(collision, "origin", None)
            )
            boxes.append(
                Box(
                    center=collision_world[:3, 3].copy(),
                    half_extents=size / 2.0,
                    rotation=collision_world[:3, :3].copy(),
                )
            )
    return boxes
