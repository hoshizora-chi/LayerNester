# SPDX-License-Identifier: GPL-2.0-or-later
"""Application handlers for LayerNester.

Two things have to be watched, and Blender reports them through two different
handlers, so both are hooked:

``frame_change_post``
    Posted once per animation frame, which is the only place keyframes and
    time-driven drivers show up.  Blender never runs a property's ``update``
    callback for an animated value, and ``depsgraph_update_post`` is not posted
    for an animation frame change at all, so without this an animated slider
    would move while the visibility stayed where it was.

``depsgraph_update_post``
    Posted when something in the scene changes that a driver can depend on, and
    when the hierarchy itself changes.  A driver fed from another object's
    property fires only this one.

Both are needed, and both call ``nester.scan_enabled`` so that a nester switched
on by animation or a driver is picked up whichever way it gets changed.  With
the ``update`` callbacks in properties.py, which cover a plain edit from the UI
or a script, that is every way a level value can move.
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

    # A root switched on by animation or a driver was never registered by the
    # update callback. The throttle means this is at most one walk of the file
    # every nester.scan_enabled.max_interval seconds, not one per update.
    nester.scan_enabled()

    for root in nester.nester_roots():
        if nester.scan_depth(root, grow_only=True):
            # New levels appeared, set_depth already synced them.
            nester.apply(root, force=True)
            continue
        # Keeps the slider labels and the hide flags in step with edits such as
        # deleting or renaming a child. Forced because a re-parent can move an
        # object between branches without changing any level value.
        nester.sync_limits(root)
        nester.apply(root, force=True)


def _on_frame_change(_scene, _depsgraph=None):
    """Push animated and driven level values onto the visibility flags.

    ``apply_all`` is unforced, so a frame where the settings still match what is
    already on screen costs one comparison per nester instead of a walk of its
    subtree.
    """
    nester.scan_enabled()
    nester.apply_all()


def _on_load(*_args):
    global _swept
    _swept = True
    nester.rebuild_roots()
    nester.apply_all(force=True)


def register():
    global _swept
    _swept = False
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)
    bpy.app.handlers.frame_change_post.append(_on_frame_change)
    bpy.app.handlers.load_post.append(_on_load)


def unregister():
    for handler in (bpy.app.handlers.depsgraph_update_post,
                    bpy.app.handlers.frame_change_post,
                    bpy.app.handlers.load_post):
        for ours in (_on_depsgraph_update, _on_frame_change, _on_load):
            while ours in handler:
                handler.remove(ours)
