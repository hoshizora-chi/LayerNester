# SPDX-License-Identifier: GPL-2.0-or-later
"""Operators for LayerNester."""

from __future__ import annotations

import bpy
from bpy.types import Operator

from . import nester


def _roots(context):
    """Enabled nester roots among the selected objects, or just the active one."""
    roots = [obj for obj in context.selected_objects if obj.layer_nester.enabled]
    if not roots and context.object and context.object.layer_nester.enabled:
        roots = [context.object]
    return roots


class LAYERNESTER_OT_rescan(Operator):
    """Match the slider count to the nesting actually present"""

    bl_idname = "layernester.rescan"
    bl_label = "Rescan Nest Depth"
    bl_description = ("Set the number of sliders to the deepest nest in the hierarchy, "
                      "shrinking it as well as growing it")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        roots = _roots(context)
        if not roots:
            self.report({"WARNING"}, "No enabled layer nester selected")
            return {"CANCELLED"}

        for root in roots:
            nester.scan_depth(root, grow_only=False)
        nester.apply_all()

        if len(roots) == 1:
            self.report({"INFO"},
                        f"Nest depth is {roots[0].layer_nester.depth}")
        else:
            self.report({"INFO"}, f"Rescanned {len(roots)} nesters")
        return {"FINISHED"}


class LAYERNESTER_OT_release(Operator):
    """Zero every slider, showing the whole hierarchy again"""

    bl_idname = "layernester.release"
    bl_label = "Show All"
    bl_description = "Set every slider to 0 so the whole hierarchy is visible again"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        roots = _roots(context)
        if not roots:
            self.report({"WARNING"}, "No enabled layer nester selected")
            return {"CANCELLED"}

        for root in roots:
            for level in root.layer_nester.path:
                level.value = 0
        nester.apply_all()
        return {"FINISHED"}


class LAYERNESTER_OT_apply_all(Operator):
    """Re-apply every enabled layer nester in the file"""

    bl_idname = "layernester.apply_all"
    bl_label = "Apply All"
    bl_description = "Re-apply the visibility of every enabled layer nester in the file"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        nester.apply_all()
        return {"FINISHED"}


class LAYERNESTER_OT_select_visible(Operator):
    """Select the objects the current sliders leave visible"""

    bl_idname = "layernester.select_visible"
    bl_label = "Select Visible"
    bl_description = "Select the descendants the current sliders leave visible"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        roots = _roots(context)
        if not roots:
            self.report({"WARNING"}, "No enabled layer nester selected")
            return {"CANCELLED"}

        view_layer = context.view_layer
        for obj in view_layer.objects:
            obj.select_set(False)

        # A descendant can live in a collection that this view layer does not
        # show, for instance a sibling scene, and select_set rejects those.
        selectable = {obj.as_pointer() for obj in view_layer.objects}
        count = 0
        skipped = 0
        for root in roots:
            for obj in nester.resolve(
                    root, root.layer_nester.level_values(), root.layer_nester.show_parents):
                if obj.as_pointer() not in selectable:
                    skipped += 1
                    continue
                obj.select_set(True)
                count += 1

        if skipped:
            self.report({"INFO"}, f"Selected {count} objects, "
                                  f"{skipped} are in collections this view "
                                  f"layer does not show")
        else:
            self.report({"INFO"}, f"Selected {count} objects")
        return {"FINISHED"}


CLASSES = (
    LAYERNESTER_OT_rescan,
    LAYERNESTER_OT_release,
    LAYERNESTER_OT_apply_all,
    LAYERNESTER_OT_select_visible,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
