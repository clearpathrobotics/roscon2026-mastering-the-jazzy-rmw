"""Unit tests for the pure-numpy top-down compositor (no ROS required)."""

import math

import numpy as np

from dynamic_image_publisher.compositor import (
    Compositor,
    SpriteAtlas,
    alpha_blit,
    rotate_rgba_about,
    world_to_pixel,
    yaw_from_quaternion,
)


def _solid_sprite(h=10, w=10, rgb=(200, 50, 50)):
    """Fully-opaque RGBA sprite of a solid colour."""
    sprite = np.zeros((h, w, 4), dtype=np.uint8)
    sprite[:, :, 0] = rgb[0]
    sprite[:, :, 1] = rgb[1]
    sprite[:, :, 2] = rgb[2]
    sprite[:, :, 3] = 255
    return sprite


def test_world_to_pixel_origin():
    """World origin maps exactly to the recorded origin pixel."""
    meta = {"meters_per_pixel": 0.01, "origin_px": [100.0, 200.0]}
    col, row = world_to_pixel(meta, 0.0, 0.0)
    assert col == 100.0
    assert row == 200.0


def test_world_to_pixel_axes():
    """+X (forward) moves up (row-), +Y (left) moves left (col-)."""
    meta = {"meters_per_pixel": 0.1, "origin_px": [100.0, 200.0]}
    # +X by 1 m -> row decreases by 10 px.
    _, row = world_to_pixel(meta, 1.0, 0.0)
    assert math.isclose(row, 190.0)
    # +Y by 1 m -> col decreases by 10 px.
    col, _ = world_to_pixel(meta, 0.0, 1.0)
    assert math.isclose(col, 90.0)


def test_yaw_from_quaternion_identity():
    """Identity quaternion has zero yaw; +90 deg about z ~ pi/2."""
    assert math.isclose(yaw_from_quaternion(0, 0, 0, 1), 0.0, abs_tol=1e-9)
    s = math.sin(math.pi / 4)
    c = math.cos(math.pi / 4)
    assert math.isclose(yaw_from_quaternion(0, 0, s, c), math.pi / 2, abs_tol=1e-6)


def test_rotate_identity_preserves_origin():
    """Zero rotation returns the same size and origin location."""
    sprite = _solid_sprite(8, 6)
    oc, orr = 3.0, 4.0
    out, out_oc, out_orr = rotate_rgba_about(sprite, oc, orr, 0.0)
    assert out.shape[:2] == sprite.shape[:2]
    assert math.isclose(out_oc, oc, abs_tol=1e-6)
    assert math.isclose(out_orr, orr, abs_tol=1e-6)


def test_rotate_90_swaps_dimensions():
    """A 90-degree rotation swaps width/height (within rounding)."""
    sprite = _solid_sprite(10, 4)
    out, _, _ = rotate_rgba_about(sprite, 2.0, 5.0, math.pi / 2)
    assert abs(out.shape[0] - 4) <= 1
    assert abs(out.shape[1] - 10) <= 1


def test_alpha_blit_opaque_overwrites():
    """A fully-opaque sprite overwrites the destination pixels it covers."""
    dst = np.zeros((20, 20, 3), dtype=np.uint8)
    sprite = _solid_sprite(6, 6, rgb=(255, 0, 0))
    rect = alpha_blit(dst, sprite, top=5, left=5)
    assert rect == (5, 5, 11, 11)
    assert np.all(dst[5:11, 5:11, 0] == 255)
    assert np.all(dst[0:5, :, :] == 0)  # untouched elsewhere


def test_alpha_blit_transparent_noop():
    """A fully-transparent sprite leaves the destination unchanged."""
    dst = np.full((10, 10, 3), 123, dtype=np.uint8)
    sprite = _solid_sprite(4, 4)
    sprite[:, :, 3] = 0
    alpha_blit(dst, sprite, top=2, left=2)
    assert np.all(dst == 123)


def test_alpha_blit_offscreen_returns_none():
    """A placement fully outside the destination returns None."""
    dst = np.zeros((10, 10, 3), dtype=np.uint8)
    sprite = _solid_sprite(4, 4)
    assert alpha_blit(dst, sprite, top=-10, left=-10) is None


def test_alpha_blit_clips_partial():
    """A partially off-image placement clips to the valid region."""
    dst = np.zeros((10, 10, 3), dtype=np.uint8)
    sprite = _solid_sprite(6, 6, rgb=(0, 255, 0))
    rect = alpha_blit(dst, sprite, top=-3, left=-3)
    assert rect == (0, 0, 3, 3)
    assert np.all(dst[0:3, 0:3, 1] == 255)


def test_alpha_blit_half_alpha_blends():
    """50 percent alpha blends halfway between src and dst."""
    dst = np.zeros((8, 8, 3), dtype=np.uint8)
    sprite = _solid_sprite(4, 4, rgb=(200, 200, 200))
    sprite[:, :, 3] = 128
    alpha_blit(dst, sprite, top=2, left=2)
    # 128/255 * 200 ~= 100.
    assert np.all(np.abs(dst[2:6, 2:6].astype(int) - 100) <= 2)


def test_compositor_dirty_rect_leaves_no_residue():
    """After moving the sprite, the previous location is restored to background."""
    bg = np.full((40, 40, 3), 30, dtype=np.uint8)
    comp = Compositor(bg)
    sprite = _solid_sprite(6, 6, rgb=(255, 255, 255))

    # Place at one location, then a far-away location.
    comp.render(sprite, 3.0, 3.0, robot_col=10.0, robot_row=10.0, yaw=0.0)
    frame = comp.render(sprite, 3.0, 3.0, robot_col=30.0, robot_row=30.0, yaw=0.0)

    # The first location must be back to background (no white residue).
    assert np.all(frame[7:14, 7:14] == 30)
    # The new location has the sprite.
    assert np.any(frame[27:34, 27:34] == 255)


def test_compositor_does_not_mutate_pristine():
    """Compositing must not corrupt the pristine background copy."""
    bg = np.full((30, 30, 3), 50, dtype=np.uint8)
    comp = Compositor(bg)
    sprite = _solid_sprite(6, 6, rgb=(255, 255, 255))
    comp.render(sprite, 3.0, 3.0, robot_col=15.0, robot_row=15.0, yaw=0.7)
    assert np.all(comp.pristine == 50)


def test_atlas_bucket_wraps():
    """Yaw buckets are evenly spaced and wrap around 2*pi."""
    sprite = _solid_sprite(6, 6)
    atlas = SpriteAtlas(sprite, 3.0, 3.0, num_angles=8)
    assert atlas.bucket(0.0) == 0
    assert atlas.bucket(2 * math.pi) == 0  # wraps to 0
    assert atlas.bucket(math.pi / 4) == 1  # 45 deg -> bucket 1 of 8
    assert atlas.bucket(-math.pi / 4) == 7  # negative wraps


def test_atlas_lookup_matches_direct_rotation():
    """An atlas entry equals a direct rotate at that bucket's angle."""
    sprite = _solid_sprite(10, 8, rgb=(10, 220, 90))
    atlas = SpriteAtlas(sprite, 4.0, 5.0, num_angles=16)
    idx, rot, oc, orr = atlas.lookup(math.pi / 8)  # exactly bucket 1
    angle = 2 * math.pi * idx / 16
    direct, doc, dorr = rotate_rgba_about(sprite, 4.0, 5.0, angle)
    assert rot.shape == direct.shape
    assert np.array_equal(rot, direct)
    assert math.isclose(oc, doc)
    assert math.isclose(orr, dorr)


def test_render_pose_requires_atlas():
    """render_pose without an atlas is a programming error."""
    comp = Compositor(np.zeros((20, 20, 3), dtype=np.uint8))
    try:
        comp.render_pose(5.0, 5.0, 0.0)
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError without an atlas")


def test_render_pose_skips_unchanged_pose():
    """An unchanged pose reports changed=False and skips work the 2nd time."""
    bg = np.full((40, 40, 3), 30, dtype=np.uint8)
    sprite = _solid_sprite(6, 6, rgb=(255, 255, 255))
    atlas = SpriteAtlas(sprite, 3.0, 3.0, num_angles=64)
    comp = Compositor(bg, atlas=atlas, position_epsilon=0.5)

    assert comp.render_pose(10.0, 10.0, 0.0) is True  # first render changes
    assert comp.render_pose(10.0, 10.0, 0.0) is False  # identical -> skipped
    # Sub-epsilon move stays in the same key and is also skipped.
    assert comp.render_pose(10.2, 10.1, 0.0) is False


def test_render_pose_detects_motion():
    """A move beyond the epsilon (or a new angle) recomposites."""
    bg = np.full((60, 60, 3), 30, dtype=np.uint8)
    sprite = _solid_sprite(6, 6, rgb=(255, 255, 255))
    atlas = SpriteAtlas(sprite, 3.0, 3.0, num_angles=64)
    comp = Compositor(bg, atlas=atlas, position_epsilon=0.5)

    assert comp.render_pose(10.0, 10.0, 0.0) is True
    assert comp.render_pose(30.0, 30.0, 0.0) is True  # big translation
    # Previous location left no residue; new location has the sprite.
    assert np.all(comp.frame[7:14, 7:14] == 30)
    assert np.any(comp.frame[27:34, 27:34] == 255)
    # Same position, new orientation bucket -> recomposite.
    assert comp.render_pose(30.0, 30.0, math.pi / 2) is True

