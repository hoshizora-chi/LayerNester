# SPDX-License-Identifier: GPL-2.0-or-later
"""Application handlers for LayerNester.

The only thing that needs watching is the hierarchy: when children are added
under a nester the slider count has to grow, otherwise the deeper objects
could never be reached.  Shrinking is left to the rescan operator because
SPECS.md asks for a slider count that does not move around on its own.
"""

from __future__ import annotations

import bpy

from . import nester


# Set once the tracked set has been swept, see _on_depsgraph_update.
_swept = False


def _on_depsgraph_update(_scene, _depsgraph=None):
    global _swept
    if not _swept:
        # Picks up nesters that were already enabled before the add-on was
        # registered. This cannot run from register(), where bpy.data is not
        # readable yet, so it waits for the first depsgraph update instead.
        _swept = True
        nester.rebuild_roots()

    if nester.is_busy():
        return
    for root in nester.nester_roots():
        if nester.scan_depth(root, grow_only=True):
            # New levels appeared, set_depth already synced them.
            nester.apply(root)
            continue
        # Keeps the slider labels and the hide flags in step with edits such as
        # deleting or renaming a child.
        nester.sync_limits(root)
        nester.apply(root)


def _on_load(*_args):
    global _swept
    _swept = True
    nester.rebuild_roots()
    nester.apply_all()


def register():
    global _swept
    _swept = False
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)
    bpy.app.handlers.load_post.append(_on_load)


def unregister():
    for handlers in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.load_post):
        while _on_depsgraph_update in handlers:
            handlers.remove(_on_depsgraph_update)
        while _on_load in handlers:
            handlers.remove(_on_load)
