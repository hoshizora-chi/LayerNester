# SPDX-License-Identifier: GPL-2.0-or-later
"""LayerNester, visibility control for nested Blender objects.

See SPECS.md and README.md.
"""

from __future__ import annotations

bl_info = {
    "name": "LayerNester",
    "author": "LayerNester contributors",
    "version": (1, 0, 0),
    "blender": (5, 2, 0),
    "location": "Properties > Object > LayerNester, 3D View > Sidebar > LayerNester",
    "description": "Manage the visibility of nested objects with one slider per level of nesting",
    "category": "Object",
}

if "bpy" in locals():
    # Support Blender's add-on reload during development.
    import importlib

    from . import handlers, nester, operators, properties, ui
    for module in (nester, properties, operators, ui, handlers):
        importlib.reload(module)

import bpy

from . import handlers, operators, properties, ui

_MODULES = (properties, operators, ui, handlers)


def register():
    for module in _MODULES:
        module.register()


def unregister():
    for module in reversed(_MODULES):
        module.unregister()


if __name__ == "__main__":
    register()
