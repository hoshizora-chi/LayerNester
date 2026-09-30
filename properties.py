# SPDX-License-Identifier: GPL-2.0-or-later
"""Properties for LayerNester."""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

from . import nester

# Level values are clamped into range by sync_limits anyway; this is only a
# sanity net against values that arrive from a script or an old file.
MAX_LEVEL_VALUE = 1 << 20


def _update_level(self, context):
    nester.sync_limits(self.id_data)
    nester.apply(self.id_data)


def _update_enabled(self, context):
    root = self.id_data
    if self.enabled:
        nester.register_root(root)
        nester.set_depth(root, nester.subtree_depth(root))
        nester.sync_limits(root)
        nester.apply(root)
    else:
        nester.unregister_root(root)
        nester.release(root)


def _update_depth(self, context):
    root = self.id_data
    nester.sync_limits(root)
    nester.apply(root)


def _update_visibility_option(self, context):
    root = self.id_data
    if not self.enabled:
        nester.release(root)
    nester.apply(root)


class LAYERNESTER_PG_Level(PropertyGroup):
    """One nest level, i.e. one integer slider."""

    value: IntProperty(
        name="Value",
        description="0 shows the whole branch, 1 and up pick a child to descend into",
        default=0,
        min=0,
        max=MAX_LEVEL_VALUE,
        soft_min=0,
        soft_max=8,
        update=_update_level,
    )
    child_name: StringProperty(
        name="Child",
        description="Name of the child this level points at, for display only",
        default="",
    )
    child_count: IntProperty(
        name="Child Count",
        description="Number of children selectable at this level, for display only",
        default=0,
        min=0,
    )


class LAYERNESTER_PG_Root(PropertyGroup):
    """Per object nester settings, stored on ``Object.layer_nester``."""

    enabled: BoolProperty(
        name="Layer Nester",
        description="Take over the visibility of this object's children so that "
                    "only one branch is shown at a time",
        default=False,
        update=_update_enabled,
    )
    depth: IntProperty(
        name="Nest Depth",
        description="Number of level sliders. Taken from the deepest nest in the "
                    "subtree and kept stable, it only grows when deeper nesting appears",
        default=0,
        min=0,
        soft_max=8,
        update=_update_depth,
    )
    computed_depth: IntProperty(
        name="Detected Depth",
        description="Nest depth found in the hierarchy by the last scan",
        default=0,
        min=0,
    )
    show_parents: BoolProperty(
        name="Show Parents",
        description="Keep the group objects leading to the shown branch visible",
        default=False,
        update=_update_visibility_option,
    )
    use_viewport: BoolProperty(
        name="Viewport",
        description="Manage the hide in viewport flag of the children",
        default=True,
        update=_update_visibility_option,
    )
    use_render: BoolProperty(
        name="Render",
        description="Manage the hide in render flag of the children",
        default=True,
        update=_update_visibility_option,
    )
    path: CollectionProperty(type=LAYERNESTER_PG_Level)

    def level_values(self) -> list[int]:
        """The slider values, in order."""
        return [level.value for level in self.path]


CLASSES = (
    LAYERNESTER_PG_Level,
    LAYERNESTER_PG_Root,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.layer_nester = PointerProperty(type=LAYERNESTER_PG_Root)


def unregister():
    del bpy.types.Object.layer_nester
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
