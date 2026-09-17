# Implementation Plan — `dynamic_image_publisher`

A lightweight ROS 2 package that synthesizes a **video-like image stream** by
compositing a moving **sprite** (a PNG with an alpha channel) over a static
**background image**, publishing the result as `sensor_msgs/Image` every frame.

Conceptually a "poor man's camera": there is no simulator and no real device — each
published frame is the background with the sprite blitted at a new position, so a
subscriber sees smooth motion (a bouncing/orbiting sprite) as if watching a video.
The package is inspired by `image_pipeline/image_publisher` but is a self-contained
`ament_python` node so it matches the sibling workshop packages.

## Motivation

- Provide a **deterministic, dependency-free image source** for RMW / QoS / transport
  experiments in the workshop (no webcam, no bag, no Gazebo).
- Generate **controllable, repeatable motion** so bandwidth and latency behaviour is
  predictable across runs.
- Exercise `image_transport` / compressed transports with realistic frame sizes.

## Scope roadmap

Designed to grow without churn:

- **Motion patterns**: `bounce` (first) → `linear`, `circular`/`orbit`, `waypoints`.
- **Sprites**: single sprite (first) → multiple sprites with independent motion.
- **Output**: raw `sensor_msgs/Image` (`bgr8`) first → optional `CameraInfo` +
  compressed transport via `image_transport`.

## Goals

- Load a **background** image (any size) and a **sprite** PNG **with alpha** (BGRA).
- Alpha-composite the sprite over the background each frame at an updated position.
- Move the sprite by a small delta per frame so the topic reads as smooth video.
- Publish a valid `sensor_msgs/Image` at a configurable rate.
- Use the **dirty-rectangle** technique so per-frame cost scales with *sprite* area,
  not *background* area (see Performance).
- Zero simulator dependencies (only `rclpy`, `cv_bridge`, OpenCV, `numpy`).

## Non-goals (keep it lightweight)

- No real camera intrinsics/distortion modelling (flat `CameraInfo` only, optional).
- No sprite rotation/scaling in v1 (translation only; rotation can come later).
- No physics — motion is a simple analytic rule, not a rigid-body sim.

## Package layout (ament_python, matches sibling packages)

```
dynamic_image_publisher/
  package.xml
  setup.py
  setup.cfg
  resource/dynamic_image_publisher
  dynamic_image_publisher/
    __init__.py
    dynamic_image_node.py      # ROS node: params, timer, publisher, frame assembly
    compositor.py              # pure image ops: load assets, alpha-blend, dirty-rect
                               #   (unit-testable, no ROS)
    motion.py                  # motion models: bounce (v1), linear/circular (later)
  launch/
    dynamic_image.launch.py
  assets/
    background.png             # sample background
    sprite.png                 # sample sprite (RGBA / alpha)
  test/
    test_compositor.py         # unit tests for blend + dirty-rect math (no ROS)
    test_motion.py             # unit tests for motion update rules
```

## Dependencies

- `rclpy`
- `sensor_msgs` (`Image`; `CameraInfo` optional/later)
- `cv_bridge` (OpenCV `Mat` ↔ `sensor_msgs/Image`)
- `python3-opencv` (imread with alpha, blending, ROI ops)
- `numpy` (vectorized alpha blend)
- `image_transport` (later, for compressed transports)

## Parameters

| Parameter        | Type     | Default          | Description                                        |
| ---------------- | -------- | ---------------- | -------------------------------------------------- |
| `background_path`| string   | `""`             | Path to background image; blank → solid color fill |
| `sprite_path`    | string   | `""`             | Path to RGBA sprite PNG                            |
| `width`          | int      | `640`            | Output width (background resized/filled to fit)    |
| `height`         | int      | `480`            | Output height                                       |
| `publish_rate`   | double   | `30.0`           | Frames per second                                   |
| `frame_id`       | string   | `camera`         | Header frame id                                     |
| `topic`          | string   | `image_raw`      | Output image topic                                  |
| `motion`         | string   | `bounce`         | `bounce` \| `linear` \| `circular`                 |
| `velocity_px`    | int[2]   | `[4, 3]`         | Per-frame sprite delta (bounce/linear)             |
| `start_xy`       | int[2]   | `[0, 0]`         | Initial sprite top-left                             |

## Core loop (per timer tick)

```
on_timer():
    pos = motion.update(pos)                  # new sprite top-left (dx, dy)
    frame = compositor.render(pos)            # background + sprite via dirty-rect
    msg = cv_bridge.cv2_to_imgmsg(frame, "bgr8")
    msg.header.stamp = now();  msg.header.frame_id = frame_id
    publisher.publish(msg)
```

### Alpha compositing (compositor.py)

For the sprite ROI only, with normalized alpha `a = sprite_alpha / 255`:

```
out = a * sprite_bgr + (1 - a) * background_roi
```

Vectorized with numpy over the `w_s × h_s × 3` sprite region. Clipping keeps the ROI
valid when the sprite is partially off-frame.

### Dirty-rectangle optimization

Keep one **pristine** copy of the background. Each frame:

1. Restore the *previous* sprite rectangle from the pristine background (small copy).
2. Alpha-blend the sprite at the *new* rectangle (small blend).
3. Publish; remember the new rectangle as "previous".

This makes per-frame compositing cost proportional to **sprite area** (independent of
resolution), instead of copying the full background every tick.

## Performance notes

For a 1080p `bgr8` frame (`1920×1080×3 ≈ 6.2 MB`):

- **RAM**: pristine background + working frame + outgoing message ≈ **~19 MB** steady
  state (≈ 3 MB at 640×480). Sprite buffer is negligible.
- **CPU**: the alpha blend over a small sprite ROI is well under 1% of a core. The
  dominant cost is the `cv_bridge` copy + transport/serialization of the *full* frame
  each tick (~2 full-frame copies/frame). At 30 fps / 1080p that is a **few % of one
  core**; at 640×480 it is negligible.
- Takeaway: the sprite overlay itself is cheap; frame size × publish rate drives cost.
  Prefer intra-process comms or a modest resolution when bandwidth matters.

## Testing

- `test_compositor.py`: alpha blend correctness (fully opaque/transparent pixels),
  dirty-rect restore leaves no residue, off-frame clipping stays in-bounds.
- `test_motion.py`: bounce reflects at edges; linear/circular produce expected deltas.
- Manual: `ros2 run rqt_image_view rqt_image_view` (or Lichtblick) to confirm smooth
  motion on the published topic.

## Milestones

1. **v0.1** — package skeleton, solid background + bouncing sprite, raw `Image` at
   configurable rate; unit tests for compositor + motion.
2. **v0.2** — background image loading/resizing, dirty-rect optimization, launch file
   with sample assets.
3. **v0.3** — optional `CameraInfo`, `image_transport` compressed publishing, extra
   motion patterns (`linear`, `circular`).
