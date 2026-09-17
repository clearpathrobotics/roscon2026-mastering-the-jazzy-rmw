#!/usr/bin/env python3
"""Offline top-down robot sprite renderer for ``dynamic_image_publisher``.

Renders a metric, top-down (orthographic, looking straight down ``-Z``) RGBA sprite
of a mock robot's **visual meshes** so it can be overlaid on the top-down world map at
runtime. This is a *dev-time* tool: it is run once (inside the ``ubuntu-sprite-render``
image) to produce committed PNGs; the runtime node never imports it.

Rendering is done with a pure-software painter's-algorithm rasterizer (``trimesh`` to
load STL/DAE meshes + Pillow to draw), so **no OpenGL / OSMesa / display** is required.

Pipeline per model:
  1. ``xacro`` expand the model's ``*.urdf.xacro`` (resolves ${...} origins).
  2. Parse links/joints/visuals with ``urdf_parser_py``.
  3. Compose every link's pose relative to ``base_link`` (joints at zero config).
  4. Load each visual mesh, apply mesh scale + visual origin + link pose.
  5. Colour each face (URDF material colour, else the mesh's own colour, else grey)
     and shade by face-normal ``z`` (light from directly above).
  6. Orthographically project to pixels at a fixed metres-per-pixel and rasterize
     back-to-front (painter's algorithm) with supersampled anti-aliasing.
  7. Save ``<model>.png`` (transparent background) + ``<model>.json`` metadata
     (metres-per-pixel and the pixel coordinate of the robot origin) so the runtime
     overlay can place/scale/rotate the sprite exactly.

Image convention (matches the top-down world map): world ``+X`` (robot forward) points
**up** the image, world ``+Y`` (robot left) points **left**. The runtime node rotates
the sprite by the robot yaw about the recorded origin pixel.
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
# URDF parsing helpers
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


# --------------------------------------------------------------------------- #
# xacro expansion
# --------------------------------------------------------------------------- #
def _expand_xacro(urdf_xacro: Path, tf_prefix: str, robot_name: str) -> str:
    """Run ``xacro`` and return the expanded URDF XML string."""
    cmd = [
        "xacro",
        str(urdf_xacro),
        f"robot_name:={robot_name}",
        f"tf_prefix:={tf_prefix}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout


# --------------------------------------------------------------------------- #
# Mesh loading
# --------------------------------------------------------------------------- #
def _resolve_mesh_path(uri: str, description_share: Path) -> Optional[Path]:
    """Resolve a ``package://mock_robot_description/...`` URI to a filesystem path."""
    prefix = "package://mock_robot_description/"
    if uri.startswith(prefix):
        return description_share / uri[len(prefix):]
    # Allow already-resolved absolute/relative paths too.
    candidate = Path(uri)
    return candidate if candidate.exists() else None


def _load_faces(
    mesh_path: Path,
    mesh_scale: np.ndarray,
    link_to_base: np.ndarray,
    visual_origin: np.ndarray,
    base_color: Optional[np.ndarray],
) -> Tuple[np.ndarray, np.ndarray]:
    """Load a mesh and return (triangles Nx3x3 in base_link, per-face RGBA Nx4 0..1)."""
    import trimesh

    loaded = trimesh.load(mesh_path, force="mesh", process=False)
    if loaded is None or not hasattr(loaded, "vertices") or len(loaded.faces) == 0:
        return np.zeros((0, 3, 3)), np.zeros((0, 4))

    verts = np.asarray(loaded.vertices, dtype=float) * mesh_scale.reshape(1, 3)

    # Compose: base_link <- link <- visual_origin, then apply to vertices.
    tf = link_to_base @ visual_origin
    verts_h = np.hstack([verts, np.ones((verts.shape[0], 1))])
    verts_base = (tf @ verts_h.T).T[:, :3]

    faces = np.asarray(loaded.faces, dtype=int)
    tris = verts_base[faces]  # (N, 3, 3)

    # Colour priority: URDF material -> mesh's own face colours -> neutral grey.
    if base_color is not None:
        rgba = np.tile(base_color.reshape(1, 4), (faces.shape[0], 1))
    else:
        rgba = _mesh_face_colors(loaded, faces.shape[0])
    return tris, rgba


def _mesh_face_colors(mesh, n_faces: int) -> np.ndarray:
    """Best-effort per-face RGBA (0..1) from a trimesh's own visuals."""
    default = np.tile(np.array([0.6, 0.6, 0.6, 1.0]), (n_faces, 1))
    visual = getattr(mesh, "visual", None)
    if visual is None:
        return default
    try:
        face_colors = getattr(visual, "face_colors", None)
        if face_colors is not None and len(face_colors) == n_faces:
            return np.asarray(face_colors, dtype=float) / 255.0
        main = getattr(visual, "main_color", None)
        if main is not None:
            return np.tile(np.asarray(main, dtype=float) / 255.0, (n_faces, 1))
    except Exception:  # noqa: BLE001 - visuals are best-effort only
        pass
    return default


def collect_robot_faces(
    urdf_xml: str,
    description_share: Path,
    base_link: str,
) -> Tuple[np.ndarray, np.ndarray]:
    """Parse URDF and gather all visual-mesh triangles in the base_link frame."""
    from urdf_parser_py.urdf import URDF, Mesh as UrdfMesh

    robot = URDF.from_xml_string(urdf_xml)
    link_tf = _link_root_transforms(robot)
    mat_colors = _material_colors(robot)

    if base_link not in link_tf:
        raise RuntimeError(
            f"base_link '{base_link}' not found. Links: {sorted(link_tf)}"
        )
    root_to_base_inv = np.linalg.inv(link_tf[base_link])

    all_tris: List[np.ndarray] = []
    all_rgba: List[np.ndarray] = []

    for link in robot.links:
        link_to_base = root_to_base_inv @ link_tf.get(link.name, np.eye(4))
        for visual in _iter_visuals(link):
            geometry = getattr(visual, "geometry", None)
            if not isinstance(geometry, UrdfMesh):
                continue
            mesh_path = _resolve_mesh_path(geometry.filename, description_share)
            if mesh_path is None or not mesh_path.exists():
                print(f"  ! skip missing mesh: {geometry.filename}", file=sys.stderr)
                continue
            scale = np.asarray(
                getattr(geometry, "scale", None) or [1.0, 1.0, 1.0], dtype=float
            ).reshape(3)

            base_color = None
            material = getattr(visual, "material", None)
            if material is not None:
                own = getattr(material, "color", None)
                if own is not None and getattr(own, "rgba", None) is not None:
                    base_color = np.asarray(own.rgba, dtype=float)
                elif getattr(material, "name", None) in mat_colors:
                    base_color = mat_colors[material.name]

            tris, rgba = _load_faces(
                mesh_path,
                scale,
                link_to_base,
                _origin_to_matrix(getattr(visual, "origin", None)),
                base_color,
            )
            if len(tris):
                all_tris.append(tris)
                all_rgba.append(rgba)

    if not all_tris:
        raise RuntimeError("No visual mesh geometry found to render.")
    return np.concatenate(all_tris, axis=0), np.concatenate(all_rgba, axis=0)


# --------------------------------------------------------------------------- #
# Top-down rasterization
# --------------------------------------------------------------------------- #
def _add_outline(image, outline_px: int, color: Tuple[int, int, int], ss: int):
    """Return ``image`` with a solid outline drawn *behind* its alpha silhouette.

    Baked into the sprite once here so the runtime overlay pays no per-frame cost:
    the outline simply rotates and blits with the rest of the sprite.
    """
    from PIL import Image, ImageFilter

    if outline_px <= 0:
        return image
    alpha = image.getchannel("A")
    mask = alpha.point(lambda a: 255 if a > 16 else 0)
    radius = max(int(round(outline_px * ss)), 1)
    dilated = mask.filter(ImageFilter.MaxFilter(radius * 2 + 1))
    outline_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    solid = Image.new("RGBA", image.size, (color[0], color[1], color[2], 255))
    outline_layer.paste(solid, (0, 0), dilated)
    # Sprite composited on top so the outline only shows as a border.
    return Image.alpha_composite(outline_layer, image)


def _draw_arrow(
    image,
    origin_px: Tuple[float, float],
    color: Tuple[int, int, int],
    scale: float,
    ss: int,
) -> None:
    """Draw a heading arrow (robot forward = up) onto ``image`` in place.

    Baked into the sprite once so orientation is always legible regardless of the
    robot's top-down colour, at zero per-frame overlay cost.
    """
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    oc = origin_px[0] * ss
    orow = origin_px[1] * ss
    dim = min(image.size)  # already supersampled
    length = scale * dim
    head_len = 0.4 * length
    head_w = 0.30 * length
    shaft_w = max(int(round(0.10 * length)), 2)
    fill = (color[0], color[1], color[2], 255)

    tip = (oc, orow - length)
    head_base = orow - length + head_len
    # Shaft from just behind the origin to the base of the arrowhead.
    draw.line([(oc, orow + 0.15 * length), (oc, head_base)], fill=fill, width=shaft_w)
    # Arrowhead triangle.
    draw.polygon(
        [tip, (oc - head_w / 2, head_base), (oc + head_w / 2, head_base)],
        fill=fill,
    )


def render_sprite(
    tris: np.ndarray,
    rgba: np.ndarray,
    meters_per_pixel: float,
    padding_px: int,
    supersample: int,
    ambient: float,
    outline_px: int = 1,
    outline_color: Tuple[int, int, int] = (30, 30, 30),
    draw_arrow: bool = True,
    arrow_scale: float = 0.42,
    arrow_color: Tuple[int, int, int] = (255, 40, 40),
) -> Tuple["object", Dict[str, float]]:
    """Rasterize triangles top-down into an RGBA Pillow image + metadata dict.

    Returns the image and a metadata dict describing metres-per-pixel and the pixel
    coordinate (col, row) of the robot origin (base_link at x=y=0), so the runtime
    overlay can place and rotate the sprite about the correct point.
    """
    from PIL import Image, ImageDraw

    xs, ys = tris[:, :, 0], tris[:, :, 1]
    x_min, x_max = float(xs.min()), float(xs.max())
    y_min, y_max = float(ys.min()), float(ys.max())

    mpp = meters_per_pixel
    pad = padding_px

    # Image size (metres span / mpp) + padding on all sides.
    width = int(np.ceil((y_max - y_min) / mpp)) + 2 * pad
    height = int(np.ceil((x_max - x_min) / mpp)) + 2 * pad

    def to_pixel(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        # +X world -> up (row decreases); +Y world -> left (col decreases).
        col = (y_max - y) / mpp + pad
        row = (x_max - x) / mpp + pad
        return np.stack([col, row], axis=-1)

    # Origin (base_link, x=y=0) pixel location, for placement/rotation at runtime.
    origin_col = (y_max - 0.0) / mpp + pad
    origin_row = (x_max - 0.0) / mpp + pad

    ss = max(int(supersample), 1)
    canvas = Image.new("RGBA", (width * ss, height * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Shading from a light directly above: intensity = ambient + (1-ambient)*max(0,nz).
    v0, v1, v2 = tris[:, 0, :], tris[:, 1, :], tris[:, 2, :]
    normals = np.cross(v1 - v0, v2 - v0)
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    nz = (normals / norms)[:, 2]
    shade = ambient + (1.0 - ambient) * np.clip(np.abs(nz), 0.0, 1.0)

    # Painter's algorithm: draw lowest (smallest mean z) first so tops land on top.
    order = np.argsort(tris[:, :, 2].mean(axis=1))

    px = to_pixel(tris[:, :, 0], tris[:, :, 1]) * ss  # (N, 3, 2) in supersampled px

    for i in order:
        color = rgba[i]
        r = int(np.clip(color[0] * shade[i] * 255, 0, 255))
        g = int(np.clip(color[1] * shade[i] * 255, 0, 255))
        b = int(np.clip(color[2] * shade[i] * 255, 0, 255))
        a = int(np.clip(color[3] * 255, 0, 255))
        poly = [(float(px[i, k, 0]), float(px[i, k, 1])) for k in range(3)]
        draw.polygon(poly, fill=(r, g, b, a))

    # Bake the outline + heading arrow into the sprite once (at supersampled
    # resolution for clean edges). These rotate/blit with the sprite at runtime,
    # so per-frame overlay cost is unaffected.
    canvas = _add_outline(canvas, outline_px, outline_color, ss)
    if draw_arrow:
        _draw_arrow(canvas, (origin_col, origin_row), arrow_color, arrow_scale, ss)

    if ss > 1:
        canvas = canvas.resize((width, height), Image.LANCZOS)

    meta = {
        "meters_per_pixel": mpp,
        "width": width,
        "height": height,
        "origin_px": [origin_col, origin_row],
        "forward_axis": "up",  # +X (robot forward) points up in the image
        "left_axis": "left",   # +Y (robot left) points left in the image
    }
    return canvas, meta


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
MODEL_URDF = {
    "a300": "a300_mock_robot.urdf.xacro",
    "r100": "r100_mock_robot.urdf.xacro",
    "j100": "j100_mock_robot.urdf.xacro",
}


def render_model(
    model: str,
    urdf_dir: Path,
    description_share: Path,
    output_dir: Path,
    tf_prefix: str,
    robot_name: str,
    meters_per_pixel: float,
    padding_px: int,
    supersample: int,
    ambient: float,
    outline_px: int,
    outline_color: Tuple[int, int, int],
    draw_arrow: bool,
    arrow_scale: float,
    arrow_color: Tuple[int, int, int],
) -> None:
    """Render a single model's sprite PNG + metadata JSON."""
    from PIL import Image  # noqa: F401 - ensure Pillow present before heavy work

    urdf_xacro = urdf_dir / MODEL_URDF[model]
    print(f"[{model}] expanding {urdf_xacro.name}")
    urdf_xml = _expand_xacro(urdf_xacro, tf_prefix, robot_name)

    base_link = f"{tf_prefix}/base_link"
    print(f"[{model}] collecting visual meshes (base_link='{base_link}')")
    tris, rgba = collect_robot_faces(urdf_xml, description_share, base_link)
    print(f"[{model}] {len(tris)} triangles")

    image, meta = render_sprite(
        tris,
        rgba,
        meters_per_pixel,
        padding_px,
        supersample,
        ambient,
        outline_px=outline_px,
        outline_color=outline_color,
        draw_arrow=draw_arrow,
        arrow_scale=arrow_scale,
        arrow_color=arrow_color,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / f"{model}.png"
    json_path = output_dir / f"{model}.json"
    npy_path = output_dir / f"{model}.npy"
    image.save(png_path)
    # Raw RGBA array for the runtime node (no image codec needed at runtime).
    np.save(npy_path, np.asarray(image.convert("RGBA"), dtype=np.uint8))
    json_path.write_text(json.dumps(meta, indent=2))
    print(
        f"[{model}] wrote {png_path} ({meta['width']}x{meta['height']}) "
        f"+ {json_path.name} + {npy_path.name}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        nargs="+",
        default=sorted(MODEL_URDF),
        choices=sorted(MODEL_URDF),
        help="Robot models to render (default: all).",
    )
    parser.add_argument(
        "--urdf-dir",
        type=Path,
        default=Path("/ws/src/mock_robot_description/urdf"),
        help="Directory containing the *_mock_robot.urdf.xacro files.",
    )
    parser.add_argument(
        "--description-share",
        type=Path,
        default=Path("/ws/src/mock_robot_description"),
        help="mock_robot_description root used to resolve package:// mesh URIs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/ws/src/dynamic_image_publisher/assets/sprites"),
        help="Where to write <model>.png and <model>.json.",
    )
    parser.add_argument("--tf-prefix", default="robot")
    parser.add_argument("--robot-name", default="mock_robot")
    parser.add_argument(
        "--meters-per-pixel",
        type=float,
        default=0.01,
        help="World metres per output pixel (match the top-down world map).",
    )
    parser.add_argument("--padding-px", type=int, default=4)
    parser.add_argument("--supersample", type=int, default=4)
    parser.add_argument("--ambient", type=float, default=0.35)
    parser.add_argument(
        "--outline-px",
        type=int,
        default=1,
        help="Outline thickness in output pixels (0 disables). Baked into the sprite.",
    )
    parser.add_argument(
        "--outline-color",
        type=int,
        nargs=3,
        metavar=("R", "G", "B"),
        default=[30, 30, 30],
        help="Outline RGB (0..255).",
    )
    parser.add_argument(
        "--no-arrow",
        dest="arrow",
        action="store_false",
        help="Disable the baked-in heading arrow.",
    )
    parser.add_argument(
        "--arrow-scale",
        type=float,
        default=0.42,
        help="Arrow length as a fraction of the smaller sprite dimension.",
    )
    parser.add_argument(
        "--arrow-color",
        type=int,
        nargs=3,
        metavar=("R", "G", "B"),
        default=[255, 40, 40],
        help="Heading-arrow RGB (0..255).",
    )
    args = parser.parse_args()

    for model in args.models:
        try:
            render_model(
                model,
                args.urdf_dir,
                args.description_share,
                args.output_dir,
                args.tf_prefix,
                args.robot_name,
                args.meters_per_pixel,
                args.padding_px,
                args.supersample,
                args.ambient,
                args.outline_px,
                tuple(args.outline_color),
                args.arrow,
                args.arrow_scale,
                tuple(args.arrow_color),
            )
        except (subprocess.CalledProcessError, RuntimeError) as exc:
            print(f"[{model}] FAILED: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
