"""Analytic ray-primitive intersection for synthesizing range sensors.

Pure math, no ROS dependencies, so it can be unit-tested standalone. The first
supported primitive is an oriented box (OBB); cylinder and sphere follow the same
"transform the ray into the primitive's local frame, intersect analytically" pattern
and can be added here later.

Conventions
-----------
- A primitive's pose is given by a rotation matrix ``R`` (primitive -> world) and a
  translation ``center`` (world). A point ``p_world`` maps to the local frame via
  ``p_local = R.T @ (p_world - center)``.
- Rays are ``origin + t * direction`` with ``t >= 0``. Directions need not be unit
  length, but ranges are only meaningful (in metres) when they are.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Rays whose direction component along an axis is smaller than this magnitude are
# treated as parallel to that axis' slab.
_PARALLEL_EPS = 1e-12


@dataclass(frozen=True)
class Box:
    """An oriented box obstacle.

    Parameters
    ----------
    center:
        ``(3,)`` box centre in the world/fixed frame.
    half_extents:
        ``(3,)`` positive half sizes along the box's local x/y/z axes
        (i.e. ``size / 2`` from a URDF ``<box size="x y z">``).
    rotation:
        ``(3, 3)`` rotation matrix mapping box-local coordinates into the world
        frame. Defaults to identity (axis-aligned).
    """

    center: np.ndarray
    half_extents: np.ndarray
    rotation: np.ndarray = field(
        default_factory=lambda: np.eye(3, dtype=float)
    )

    def __post_init__(self) -> None:
        """Coerce the pose fields to float numpy arrays of the expected shape."""
        object.__setattr__(self, "center", np.asarray(self.center, dtype=float).reshape(3))
        object.__setattr__(
            self, "half_extents", np.asarray(self.half_extents, dtype=float).reshape(3)
        )
        object.__setattr__(
            self, "rotation", np.asarray(self.rotation, dtype=float).reshape(3, 3)
        )


def intersect_box(
    origin: np.ndarray,
    directions: np.ndarray,
    box: Box,
) -> np.ndarray:
    """Intersect a bundle of rays sharing one origin against a single box.

    Parameters
    ----------
    origin:
        ``(3,)`` common ray origin in the world frame.
    directions:
        ``(N, 3)`` ray directions in the world frame (or ``(3,)`` for a single ray).
    box:
        The :class:`Box` to test against.

    Returns
    -------
    numpy.ndarray
        ``(N,)`` array of hit distances ``t`` along each ray. Misses are ``+inf``.
        For an origin inside the box the exit distance (``t_far``) is returned.

    Notes
    -----
    The computation preserves the dtype of ``directions`` (promoted to at least
    ``float32``), so passing ``float32`` rays keeps the whole slab test in single
    precision, which roughly halves the memory bandwidth of the ``(N, 3)`` temporaries.
    """
    directions = np.atleast_2d(np.asarray(directions))
    work_dtype = np.result_type(directions.dtype, np.float32)
    directions = directions.astype(work_dtype, copy=False)
    origin = np.asarray(origin, dtype=work_dtype).reshape(3)

    # Transform ray into the box's local frame, where the box is axis-aligned
    # over [-half_extents, +half_extents].
    rot = box.rotation.astype(work_dtype, copy=False)
    center = box.center.astype(work_dtype, copy=False)
    h = box.half_extents.astype(work_dtype, copy=False)

    o_local = rot.T @ (origin - center)  # (3,)
    d_local = directions @ rot  # (N, 3)  == (rot.T @ d) per row

    with np.errstate(divide="ignore", invalid="ignore"):
        inv_d = np.reciprocal(d_local)  # (N, 3); +-inf where parallel
        t1 = inv_d * (-h - o_local)  # (N, 3)
        t2 = inv_d * (h - o_local)  # (N, 3)

    # Reuse the t1/t2 buffers: t_small is a fresh min, t_big overwrites t2 in place.
    t_small = np.minimum(t1, t2)  # (N, 3)
    t_big = np.maximum(t1, t2, out=t2)  # (N, 3), reuses t2

    # Axes where the ray is parallel to the slab: no constraint if the origin is
    # inside the slab, otherwise an impossible interval. Only touch the (usually few)
    # parallel entries instead of rebuilding the whole array with np.where.
    parallel = np.abs(d_local) < _PARALLEL_EPS  # (N, 3)
    if parallel.any():
        inside = np.broadcast_to(
            (o_local >= -h) & (o_local <= h), d_local.shape
        )
        t_small[parallel] = np.where(inside[parallel], -np.inf, np.inf)
        t_big[parallel] = np.where(inside[parallel], np.inf, -np.inf)

    t_near = t_small.max(axis=1)  # (N,)
    t_far = t_big.min(axis=1)  # (N,)

    hit = (t_near <= t_far) & (t_far >= 0.0)

    # Nearest forward intersection: t_near if in front of the origin, else t_far
    # (origin is inside the box).
    t_hit = np.where(t_near >= 0.0, t_near, t_far)
    miss = work_dtype.type(np.inf)
    return np.where(hit, t_hit, miss)


def cast(
    origin: np.ndarray,
    directions: np.ndarray,
    boxes,
    range_min: float = 0.0,
    range_max: float = float("inf"),
    range_on_miss: float = float("inf"),
) -> np.ndarray:
    """Cast rays against a collection of boxes and return per-ray ranges.

    Parameters
    ----------
    origin:
        ``(3,)`` common ray origin in the world frame.
    directions:
        ``(N, 3)`` unit ray directions in the world frame.
    boxes:
        Iterable of :class:`Box`.
    range_min, range_max:
        Valid measurement window in metres. Hits closer than ``range_min`` are
        ignored; hits beyond ``range_max`` are treated as misses.
    range_on_miss:
        Value reported for rays that hit nothing within range (e.g. ``range_max``
        or ``inf``).

    Returns
    -------
    numpy.ndarray
        ``(N,)`` range per ray.
    """
    directions = np.atleast_2d(np.asarray(directions))
    work_dtype = np.result_type(directions.dtype, np.float32)
    directions = directions.astype(work_dtype, copy=False)
    n = directions.shape[0]

    miss = work_dtype.type(np.inf)
    best = np.full(n, miss, dtype=work_dtype)
    for box in boxes:
        t = intersect_box(origin, directions, box)
        # Reject hits closer than range_min in place (no extra full-size array).
        t[t < range_min] = miss
        np.minimum(best, t, out=best)

    # Anything beyond range_max is a miss.
    best[best > range_max] = miss
    rom = np.asarray(range_on_miss, dtype=work_dtype)
    return np.where(np.isfinite(best), best, rom)


def ray_directions_2d(
    angle_min: float,
    angle_increment: float,
    count: int,
) -> np.ndarray:
    """Build ``(count, 3)`` unit directions in the sensor XY plane.

    Angles increase from ``angle_min`` by ``angle_increment`` and lie in the z=0
    plane (``z`` component is 0), matching a planar 2D LaserScan.
    """
    angles = angle_min + np.arange(count, dtype=float) * angle_increment
    dirs = np.zeros((count, 3), dtype=float)
    dirs[:, 0] = np.cos(angles)
    dirs[:, 1] = np.sin(angles)
    return dirs
