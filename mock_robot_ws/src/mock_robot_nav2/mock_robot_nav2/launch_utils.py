"""Launch helpers for mock_robot_nav2.

The Nav2 / SLAM / AMCL param files are single templates that carry ``${frame_id}``
(and, for Nav2, ``${footprint}`` and ``${motion_model}``; for AMCL,
``${amcl_motion_model}``) tokens. ``render_params`` substitutes those tokens and
writes a concrete params file to the system temp dir, mirroring the temp-file
pattern ``mock_robot.launch.py`` already uses for its controller frame overrides.
Topics are left as bare relative strings and resolve under the pushed namespace,
so they are never tokenized.
"""

import os
import string
import tempfile


# Costmap footprints derived from mock_robot_description URDF link geometry
# (half-extents in metres). See mock_robot_nav2.md §10 decision 4.
FOOTPRINTS = {
    "a300": "[ [0.43, 0.34], [0.43, -0.34], [-0.43, -0.34], [-0.43, 0.34] ]",
    "j100": "[ [0.21, 0.21], [0.21, -0.21], [-0.21, -0.21], [-0.21, 0.21] ]",
    "r100": "[ [0.48, 0.40], [0.48, -0.40], [-0.48, -0.40], [-0.48, 0.40] ]",
}


def _as_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def motion_model_for(use_mecanum):
    """MPPI controller motion model: 'Omni' for mecanum, else 'DiffDrive'."""
    return "Omni" if _as_bool(use_mecanum) else "DiffDrive"


def amcl_motion_model_for(use_mecanum):
    """AMCL motion model plugin: omni for mecanum, else differential."""
    return (
        "nav2_amcl::OmniMotionModel"
        if _as_bool(use_mecanum)
        else "nav2_amcl::DifferentialMotionModel"
    )


def footprint_for(robot_model):
    """Return the costmap footprint string for a mock robot model."""
    try:
        return FOOTPRINTS[robot_model.strip().lower()]
    except KeyError:
        valid = ", ".join(sorted(FOOTPRINTS))
        raise RuntimeError(
            f"Unknown robot_model '{robot_model}'. Valid choices are: {valid}."
        )


def render_params(template_path, substitutions, name_hint=None):
    """Substitute ``${...}`` tokens in a param template and write a concrete file.

    ``substitutions`` may contain more keys than the template uses; only tokens
    present in the template are replaced. A missing/misspelled token in the
    template raises ``KeyError`` (catching typos early). Returns the path to the
    rendered file in the system temp dir.
    """
    with open(template_path, "r", encoding="utf-8") as handle:
        template = string.Template(handle.read())
    rendered = template.substitute(**substitutions)

    prefix = name_hint or substitutions.get("frame_id", "mock")
    basename = os.path.basename(template_path).replace(".template", "")
    output_path = os.path.join(tempfile.gettempdir(), f"{prefix}_{basename}")
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    return output_path
