# SPDX-License-Identifier: GPL-2.0-or-later
"""User interface for LayerNester."""

from __future__ import annotations

import bpy
from bpy.types import Panel

from . import nester

CATEGORY = "LayerNester"


def _draw_header(layout, obj):
    """The enable toggle, plus a warning when the sliders no longer fit."""
    settings = obj.layer_nester
    layout.prop(settings, "enabled", icon='NODETREE')

    if not settings.enabled:
        return

    if settings.computed_depth != settings.depth:
        row = layout.row()
        row.alert = True
        row.label(text=f"Hierarchy is {settings.computed_depth} deep, "
                       f"only {settings.depth} sliders shown",
                   icon='ERROR')


def _draw_body(layout, obj):
    settings = obj.layer_nester

    if not obj.children:
        layout.label(text="This object has no children", icon='INFO')
        return

    if settings.depth == 0:
        layout.label(text="No levels yet, rescan to pick them up", icon='INFO')
        layout.operator("layernester.rescan", icon='FILE_REFRESH')
        return

    levels = layout.column(align=True)
    for index, level in enumerate(settings.path):
        if level.child_name:
            text = f"{index + 1}. {level.child_name}"
        elif level.child_count:
            text = f"{index + 1}. all {level.child_count}"
        else:
            text = f"{index + 1}."
        levels.prop(level, "value", text=text)

    # resolve always returns at least the object it landed on.
    visible = nester.resolve(obj, settings.level_values(), settings.show_parents)
    summary = layout.box()
    summary.scale_y = 0.8
    summary.label(text=f"Showing {visible[0].name}", icon='HIDE_OFF')
    if len(visible) > 1:
        summary.label(text=f"and {len(visible) - 1} more")

    options = layout.column(align=True)
    options.prop(settings, "show_parents")
    row = options.row(align=True)
    row.prop(settings, "use_viewport")
    row.prop(settings, "use_render")

    row = layout.row(align=True)
    row.operator("layernester.release", text="Show All")
    row.operator("layernester.rescan", text="Rescan")


class LAYERNESTER_PT_object(Panel):
    bl_label = "Layer Nester"
    bl_idname = "LAYERNESTER_PT_object"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_category = CATEGORY

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def draw(self, context):
        layout = self.layout
        obj = context.object

        _draw_header(layout, obj)
        if not obj.layer_nester.enabled:
            layout.label(text="Visibility of the children is not managed here")
            return

        _draw_body(layout, obj)


class LAYERNESTER_PT_view3d(Panel):
    bl_label = "Layer Nester"
    bl_idname = "LAYERNESTER_PT_view3d"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def draw(self, context):
        layout = self.layout
        obj = context.object

        row = layout.row()
        row.label(text=obj.name, icon='OBJECT_DATA')
        row.prop(obj.layer_nester, "enabled", text="")

        if not obj.layer_nester.enabled:
            layout.label(text="Visibility is not managed here", icon='INFO')
            return

        if obj.layer_nester.computed_depth != obj.layer_nester.depth:
            row = layout.row()
            row.alert = True
            row.label(text=f"{obj.layer_nester.computed_depth} deep, "
                           f"{obj.layer_nester.depth} sliders",
                      icon='ERROR')

        _draw_body(layout, obj)

        layout.separator()
        layout.operator("layernester.select_visible", icon='RESTRICT_SELECT_OFF')
        layout.operator("layernester.apply_all", icon='FILE_REFRESH')


CLASSES = (
    LAYERNESTER_PT_object,
    LAYERNESTER_PT_view3d,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
