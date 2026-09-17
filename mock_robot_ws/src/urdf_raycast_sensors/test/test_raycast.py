"""Unit tests for the analytic ray-box math core (no ROS required)."""

import math

import numpy as np
import pytest

from urdf_raycast_sensors.raycast import (
    Box,
    cast,
    intersect_box,
    ray_directions_2d,
)


def rot_z(theta: float) -> np.ndarray:
    """Return a 3x3 rotation matrix for a rotation of ``theta`` radians about z."""
    c, s = math.cos(theta), math.sin(theta)
    return np.array(
        [
            [c, -s, 0.0],
            [s, c, 0.0],
            [0.0, 0.0, 1.0],
        ]
    )


def test_head_on_hit_axis_aligned():
    """A head-on ray hits the near face of an axis-aligned box at the exact range."""
    # Unit box centred at x=5, ray from origin along +x hits the near face at 4.5.
    box = Box(center=[5.0, 0.0, 0.0], half_extents=[0.5, 0.5, 0.5])
    t = intersect_box([0.0, 0.0, 0.0], [1.0, 0.0, 0.0], box)
    assert t.shape == (1,)
    assert t[0] == pytest.approx(4.5)


def test_miss_returns_inf():
    """A ray pointing away from the box returns an infinite (miss) range."""
    box = Box(center=[5.0, 0.0, 0.0], half_extents=[0.5, 0.5, 0.5])
    # Ray points along +y, never reaches the box.
    t = intersect_box([0.0, 0.0, 0.0], [0.0, 1.0, 0.0], box)
    assert not np.isfinite(t[0])


def test_ray_parallel_to_slab_no_false_hit():
    """A ray parallel to a slab and outside its extent must not report a hit."""
    # Box sits above the ray line in y; a +x ray at y=2 is parallel to the x-slab
    # faces and must miss (its y is outside the box's y-extent).
    box = Box(center=[5.0, 0.0, 0.0], half_extents=[0.5, 0.5, 0.5])
    t = intersect_box([0.0, 2.0, 0.0], [1.0, 0.0, 0.0], box)
    assert not np.isfinite(t[0])


def test_rotated_box():
    """An oriented (rotated) box reports the correct range to its rotated face."""
    # Box rotated 45 deg about z, centred at x=5. A +x ray along y=0 still hits the
    # nearest corner face. Half-diagonal in x for a unit box rotated 45 deg is
    # 0.5*sqrt(2) ~= 0.7071, so the near face is at 5 - 0.7071.
    box = Box(
        center=[5.0, 0.0, 0.0],
        half_extents=[0.5, 0.5, 0.5],
        rotation=rot_z(math.pi / 4.0),
    )
    t = intersect_box([0.0, 0.0, 0.0], [1.0, 0.0, 0.0], box)
    assert t[0] == pytest.approx(5.0 - 0.5 * math.sqrt(2.0), abs=1e-9)


def test_origin_inside_box_returns_exit_distance():
    """A ray originating inside the box returns the exit (far) distance."""
    # Origin at the centre of a unit box, ray along +x exits at the far face (0.5).
    box = Box(center=[0.0, 0.0, 0.0], half_extents=[0.5, 0.5, 0.5])
    t = intersect_box([0.0, 0.0, 0.0], [1.0, 0.0, 0.0], box)
    assert t[0] == pytest.approx(0.5)


def test_nearest_hit_wins_across_boxes():
    """With multiple boxes, the nearest intersection is returned."""
    near = Box(center=[3.0, 0.0, 0.0], half_extents=[0.5, 0.5, 0.5])
    far = Box(center=[8.0, 0.0, 0.0], half_extents=[0.5, 0.5, 0.5])
    r = cast([0.0, 0.0, 0.0], [[1.0, 0.0, 0.0]], [far, near])
    assert r[0] == pytest.approx(2.5)


def test_range_max_miss_reports_sentinel():
    """A hit beyond ``range_max`` is treated as a miss and reports the sentinel."""
    box = Box(center=[50.0, 0.0, 0.0], half_extents=[0.5, 0.5, 0.5])
    r = cast(
        [0.0, 0.0, 0.0],
        [[1.0, 0.0, 0.0]],
        [box],
        range_max=30.0,
        range_on_miss=30.0,
    )
    assert r[0] == pytest.approx(30.0)


def test_range_min_rejects_too_close():
    """A hit closer than ``range_min`` is rejected and reported as a miss."""
    box = Box(center=[0.2, 0.0, 0.0], half_extents=[0.05, 0.5, 0.5])
    # Near face at 0.15 is inside range_min=0.5, so it should be rejected -> miss.
    r = cast(
        [0.0, 0.0, 0.0],
        [[1.0, 0.0, 0.0]],
        [box],
        range_min=0.5,
        range_max=30.0,
        range_on_miss=float("inf"),
    )
    assert not np.isfinite(r[0])


def test_vectorized_multi_ray_shapes():
    """Casting many rays returns one range per ray with at least one finite hit."""
    box = Box(center=[5.0, 0.0, 0.0], half_extents=[0.5, 0.5, 0.5])
    dirs = ray_directions_2d(-math.pi, math.pi / 180.0, 360)
    r = cast([0.0, 0.0, 0.0], dirs, [box], range_max=100.0, range_on_miss=100.0)
    assert r.shape == (360,)
    # At least the forward-facing rays should register a finite hit.
    assert np.isfinite(r).any()


def test_ray_directions_2d_are_planar_unit():
    """Generated 2D ray directions are unit length and lie in the z=0 plane."""
    dirs = ray_directions_2d(0.0, math.pi / 2.0, 4)
    assert dirs.shape == (4, 3)
    assert np.allclose(dirs[:, 2], 0.0)
    norms = np.linalg.norm(dirs, axis=1)
    assert np.allclose(norms, 1.0)
