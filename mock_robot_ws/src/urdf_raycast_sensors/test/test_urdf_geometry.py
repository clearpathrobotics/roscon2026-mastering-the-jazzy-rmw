"""Unit tests for URDF box parsing (uses urdf_parser_py / urdfdom_py)."""

import math

import numpy as np
import pytest

from urdf_raycast_sensors.raycast import cast
from urdf_raycast_sensors.urdf_geometry import boxes_from_urdf


SIMPLE_URDF = """
<robot name="test">
  <link name="world"/>
  <link name="wall">
    <collision>
      <geometry><box size="0.2 4.0 1.0"/></geometry>
    </collision>
  </link>
  <joint name="wall_joint" type="fixed">
    <parent link="world"/>
    <child link="wall"/>
    <origin xyz="5.0 0.0 0.5" rpy="0 0 0"/>
  </joint>
</robot>
"""


def test_parses_single_box_pose_and_size():
    """A single box link parses to the expected centre, half-extents, and rotation."""
    boxes = boxes_from_urdf(SIMPLE_URDF)
    assert len(boxes) == 1
    box = boxes[0]
    assert np.allclose(box.center, [5.0, 0.0, 0.5])
    assert np.allclose(box.half_extents, [0.1, 2.0, 0.5])
    assert np.allclose(box.rotation, np.eye(3))


def test_parsed_box_is_hit_by_raycast():
    """A box parsed from URDF is hit at the expected range by a raycast."""
    boxes = boxes_from_urdf(SIMPLE_URDF)
    # Ray from origin along +x should hit the wall near face at 5.0 - 0.1 = 4.9.
    r = cast([0.0, 0.0, 0.5], [[1.0, 0.0, 0.0]], boxes, range_max=30.0)
    assert r[0] == pytest.approx(4.9)


def test_exclude_links_skips_sensor():
    """Links named in ``exclude_links`` are omitted from the parsed boxes."""
    boxes = boxes_from_urdf(SIMPLE_URDF, exclude_links=["wall"])
    assert boxes == []


def test_joint_origin_rotation_is_applied():
    """A joint origin's yaw is applied to the resulting box's rotation matrix."""
    urdf = """
    <robot name="test">
      <link name="world"/>
      <link name="b">
        <collision><geometry><box size="1 1 1"/></geometry></collision>
      </link>
      <joint name="j" type="fixed">
        <parent link="world"/>
        <child link="b"/>
        <origin xyz="4 0 0" rpy="0 0 0.7853981633974483"/>
      </joint>
    </robot>
    """
    boxes = boxes_from_urdf(urdf)
    assert len(boxes) == 1
    # 45 deg about z: rotation matrix top-left should be cos(45).
    assert boxes[0].rotation[0, 0] == pytest.approx(math.cos(math.pi / 4.0))
