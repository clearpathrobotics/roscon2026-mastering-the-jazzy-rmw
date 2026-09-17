"""Pure-numpy top-down compositor for ``dynamic_image_publisher``.

No OpenCV / PIL / cv_bridge at runtime: assets are loaded from ``.npy`` (pre-rendered
offline by ``tools/render_world.py`` and ``tools/render_sprites.py``) and all image ops
are numpy. The compositor keeps a pristine background and, each frame, restores only the
previous sprite rectangle before blitting the sprite at its new pose (dirty-rectangle),
so per-frame cost scales with sprite area, not background area.

Coordinate conventions (shared with the render tools):
  * The map/sprite images use +X (robot forward) -> up, +Y (robot left) -> left.
  * ``meters_per_pixel`` and ``origin_px`` (col, row of the world/robot origin) come
    from the assets' JSON sidecars.
  * A world point (x, y) maps to a map pixel via
        col = origin_px[0] - y / mpp
        row = origin_px[1] - x / mpp
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np


# --------------------------------------------------------------------------- #
# Asset loading
# --------------------------------------------------------------------------- #
def load_meta(json_path: Path) -> Dict:
    """Load an asset's JSON sidecar (meters_per_pixel, origin_px, size, ...)."""
    return json.loads(Path(json_path).read_text())


def load_rgb(npy_path: Path) -> np.ndarray:
    """Load a background as a contiguous ``HxWx3`` uint8 RGB array."""
    arr = np.load(npy_path)
    if arr.ndim != 3 or arr.shape[2] < 3:
        raise ValueError(f"Expected HxWx3 RGB array, got shape {arr.shape}")
    return np.ascontiguousarray(arr[:, :, :3], dtype=np.uint8)


def load_rgba(npy_path: Path) -> np.ndarray:
    """Load a sprite as a contiguous ``hxwx4`` uint8 RGBA array."""
    arr = np.load(npy_path)
    if arr.ndim != 3 or arr.shape[2] != 4:
        raise ValueError(f"Expected hxwx4 RGBA array, got shape {arr.shape}")
    return np.ascontiguousarray(arr, dtype=np.uint8)


# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #
def world_to_pixel(
    meta: Dict, x: float, y: float
) -> Tuple[float, float]:
    """Map a world ``(x, y)`` (metres) to a fractional map pixel ``(col, row)``."""
    mpp = float(meta["meters_per_pixel"])
    oc, orr = meta["origin_px"]
    return oc - y / mpp, orr - x / mpp


def yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    """Extract the Z (yaw) angle in radians from a quaternion."""
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


# --------------------------------------------------------------------------- #
# Rotation (bilinear, about an arbitrary origin)
# --------------------------------------------------------------------------- #
def rotate_rgba_about(
    rgba: np.ndarray,
    origin_col: float,
    origin_row: float,
    yaw: float,
) -> Tuple[np.ndarray, float, float]:
    """Rotate an RGBA sprite by ``yaw`` (rad) about ``(origin_col, origin_row)``.

    Returns the rotated sprite (tightly bounded) and the pixel location of the
    rotated origin within it, so the caller can place the origin at the robot pixel.

    The mapping is derived so that at ``yaw = 0`` the sprite is unchanged and, as the
    robot rotates CCW about +Z in the world (which is CCW in the top-down image), the
    sprite's "up" (forward) direction rotates toward "left" (+Y), matching the map.
    """
    h, w = rgba.shape[:2]
    cos_t, sin_t = math.cos(yaw), math.sin(yaw)

    # Forward map of a sprite offset (u, v) = (col, row) from the origin to a dest
    # offset from the placed origin:  dcol = cos*u + sin*v ;  drow = -sin*u + cos*v.
    # Corners are the extreme pixel centres (0..w-1, 0..h-1) relative to the origin.
    corners = np.array(
        [
            [-origin_col, -origin_row],
            [w - 1 - origin_col, -origin_row],
            [w - 1 - origin_col, h - 1 - origin_row],
            [-origin_col, h - 1 - origin_row],
        ],
        dtype=float,
    )
    du = cos_t * corners[:, 0] + sin_t * corners[:, 1]
    dv = -sin_t * corners[:, 0] + cos_t * corners[:, 1]
    min_du, max_du = float(du.min()), float(du.max())
    min_dv, max_dv = float(dv.min()), float(dv.max())

    out_w = int(round(max_du - min_du)) + 1
    out_h = int(round(max_dv - min_dv)) + 1
    out_oc = -min_du  # origin location within the output image
    out_orr = -min_dv

    # Dest grid (offsets from the placed origin).
    jj, ii = np.meshgrid(np.arange(out_w), np.arange(out_h))
    dcol = jj - out_oc
    drow = ii - out_orr

    # Inverse map dest -> sprite:  u = cos*dcol - sin*drow ;  v = sin*dcol + cos*drow.
    src_col = (cos_t * dcol - sin_t * drow) + origin_col
    src_row = (sin_t * dcol + cos_t * drow) + origin_row

    out = _bilinear_sample_rgba(rgba, src_col, src_row)
    return out, out_oc, out_orr


def _bilinear_sample_rgba(
    rgba: np.ndarray, src_col: np.ndarray, src_row: np.ndarray
) -> np.ndarray:
    """Bilinearly sample ``rgba`` at fractional ``(src_col, src_row)`` grids.

    Samples fully outside the source are transparent (alpha 0).
    """
    h, w = rgba.shape[:2]
    x0 = np.floor(src_col).astype(np.intp)
    y0 = np.floor(src_row).astype(np.intp)
    x1 = x0 + 1
    y1 = y0 + 1
    wx = (src_col - x0)[..., None]
    wy = (src_row - y0)[..., None]

    # Validity per corner (inside the source grid).
    def gather(xs: np.ndarray, ys: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        valid = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        xc = np.clip(xs, 0, w - 1)
        yc = np.clip(ys, 0, h - 1)
        vals = rgba[yc, xc].astype(np.float32)
        vals[~valid] = 0.0  # transparent + black outside
        return vals, valid

    c00, _ = gather(x0, y0)
    c10, _ = gather(x1, y0)
    c01, _ = gather(x0, y1)
    c11, _ = gather(x1, y1)

    top = c00 * (1.0 - wx) + c10 * wx
    bot = c01 * (1.0 - wx) + c11 * wx
    out = top * (1.0 - wy) + bot * wy
    return np.clip(out, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
# Blit + compositor
# --------------------------------------------------------------------------- #
Rect = Tuple[int, int, int, int]  # (y0, x0, y1, x1)


def alpha_blit(dst_rgb: np.ndarray, src_rgba: np.ndarray, top: int, left: int) -> Optional[Rect]:
    """Alpha-composite ``src_rgba`` onto ``dst_rgb`` at ``(top, left)``; clip to bounds.

    Returns the affected destination rectangle, or ``None`` if fully off-image.
    """
    h, w = src_rgba.shape[:2]
    dh, dw = dst_rgb.shape[:2]
    y0 = max(0, top)
    x0 = max(0, left)
    y1 = min(dh, top + h)
    x1 = min(dw, left + w)
    if y0 >= y1 or x0 >= x1:
        return None

    sub = src_rgba[y0 - top:y1 - top, x0 - left:x1 - left]
    a = sub[:, :, 3:4].astype(np.float32) / 255.0
    region = dst_rgb[y0:y1, x0:x1].astype(np.float32)
    blended = a * sub[:, :, :3].astype(np.float32) + (1.0 - a) * region
    dst_rgb[y0:y1, x0:x1] = np.clip(blended, 0, 255).astype(np.uint8)
    return (y0, x0, y1, x1)


class SpriteAtlas:
    """Pre-rotated sprite table: rotation becomes a lookup instead of a per-frame op.

    At construction the sprite is rotated once into ``num_angles`` evenly spaced
    orientations (the classic 2D-engine trick: bake rotations offline so the runtime
    only indexes an array). Each entry stores the rotated RGBA and the pixel location
    of the robot origin within it, so the compositor can place the origin at the robot
    pixel without any per-frame trig or bilinear resampling.
    """

    def __init__(
        self,
        sprite_rgba: np.ndarray,
        origin_col: float,
        origin_row: float,
        num_angles: int = 256,
    ) -> None:
        if num_angles < 1:
            raise ValueError("num_angles must be >= 1")
        self.num_angles = int(num_angles)
        self._entries = []  # (rot_rgba, out_origin_col, out_origin_row)
        for k in range(self.num_angles):
            yaw = 2.0 * math.pi * k / self.num_angles
            rot, oc, orr = rotate_rgba_about(sprite_rgba, origin_col, origin_row, yaw)
            self._entries.append((np.ascontiguousarray(rot), oc, orr))

    def bucket(self, yaw: float) -> int:
        """Return the atlas index of the orientation nearest to ``yaw`` (radians)."""
        frac = (yaw / (2.0 * math.pi)) % 1.0
        return int(round(frac * self.num_angles)) % self.num_angles

    def lookup(self, yaw: float) -> Tuple[int, np.ndarray, float, float]:
        """Return ``(index, rot_rgba, origin_col, origin_row)`` for ``yaw``."""
        idx = self.bucket(yaw)
        rot, oc, orr = self._entries[idx]
        return idx, rot, oc, orr


class Compositor:
    """Keep a pristine background and blit the rotated sprite each frame (dirty-rect).

    Two render paths:
      * :meth:`render` — resamples the sprite every call (used by tests / no atlas).
      * :meth:`render_pose` — uses a :class:`SpriteAtlas` lookup plus pose change
        detection, so an unchanged pose (same sub-pixel position and orientation
        bucket) costs nothing and reports ``changed=False`` so the caller can skip
        re-publishing.
    """

    def __init__(
        self,
        background_rgb: np.ndarray,
        atlas: Optional[SpriteAtlas] = None,
        position_epsilon: float = 0.5,
    ) -> None:
        self.pristine = np.ascontiguousarray(background_rgb, dtype=np.uint8)
        self.frame = self.pristine.copy()
        self._prev_rect: Optional[Rect] = None
        self.atlas = atlas
        self.position_epsilon = max(float(position_epsilon), 1e-6)
        self._last_key: Optional[Tuple[int, int, int]] = None
        self.changed = True

    @property
    def size(self) -> Tuple[int, int]:
        """Return ``(height, width)`` of the composited frame."""
        return self.frame.shape[0], self.frame.shape[1]

    def render(
        self,
        sprite_rgba: np.ndarray,
        sprite_origin_col: float,
        sprite_origin_row: float,
        robot_col: float,
        robot_row: float,
        yaw: float,
    ) -> np.ndarray:
        """Composite the sprite at the robot pixel/orientation and return the frame."""
        rot, roc, rorr = rotate_rgba_about(
            sprite_rgba, sprite_origin_col, sprite_origin_row, yaw
        )
        top = int(round(robot_row - rorr))
        left = int(round(robot_col - roc))

        # Restore only the previously dirtied region from the pristine background.
        if self._prev_rect is not None:
            y0, x0, y1, x1 = self._prev_rect
            self.frame[y0:y1, x0:x1] = self.pristine[y0:y1, x0:x1]

        self._prev_rect = alpha_blit(self.frame, rot, top, left)
        self.changed = True
        return self.frame

    def render_pose(self, robot_col: float, robot_row: float, yaw: float) -> bool:
        """Atlas-composite at ``(robot_col, robot_row, yaw)``; return whether it moved.

        Returns ``True`` if the frame was recomposited (pose changed beyond the
        position epsilon or into a new orientation bucket), ``False`` if the pose was
        unchanged and the frame left untouched. Requires an atlas.
        """
        if self.atlas is None:
            raise RuntimeError("render_pose requires a SpriteAtlas")

        idx, rot, roc, rorr = self.atlas.lookup(yaw)
        key = (
            int(round(robot_col / self.position_epsilon)),
            int(round(robot_row / self.position_epsilon)),
            idx,
        )
        if key == self._last_key:
            self.changed = False
            return False
        self._last_key = key

        top = int(round(robot_row - rorr))
        left = int(round(robot_col - roc))

        # Restore only the previously dirtied region from the pristine background.
        if self._prev_rect is not None:
            y0, x0, y1, x1 = self._prev_rect
            self.frame[y0:y1, x0:x1] = self.pristine[y0:y1, x0:x1]

        self._prev_rect = alpha_blit(self.frame, rot, top, left)
        self.changed = True
        return True
