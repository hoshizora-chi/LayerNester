# SPDX-License-Identifier: GPL-2.0-or-later
"""Core resolution logic for LayerNester.

The rule
--------
A nester root owns one integer level value per level of nesting, from the
first level down to the deepest level found in its subtree.  The values are
consumed in order as a path through the hierarchy:

* ``0``  -> stop descending, show the object reached and its whole subtree.
* ``n``  -> descend into the ``n``-th child and use the next level.
* If the levels run out while still descending, the object reached is shown
  together with its whole subtree.

``n`` indexes into ``Object.children``, which is the order the outliner lists
the children in, so level 1 is always the first child shown there.

So with::

    Parent
        Child Group 1
            Child 1
        Child Group 2
            Child 2
            Child 3
        Child 4

picking ``Child Group 1`` then ``Child 1`` shows only ``Child 1``, picking
``Child Group 2`` then ``Child 3`` shows only ``Child 3``, and picking
``Child 4`` with the second level at ``0`` shows only ``Child 4``.  That is
the behaviour SPECS.md asks for, and only one child is visible at a time.
"""

from __future__ import annotations

import time

import bpy

# Safety net for pathologically deep hierarchies, so a generated parent chain
# can never spin forever.
_MAX_WALK = 4096

# Guard against re-entrancy: writing hide flags updates the depsgraph, which
# calls back into the handler that writes hide flags.
_busy = False

# Objects that were switched on at some point, so the depsgraph handler does
# not have to touch every object in the file. Keyed by object pointer rather
# than held in a set: once an object is deleted its Python wrapper hashes to 0,
# which would make a set entry unreachable and leak forever.
_roots: dict[int, object] = {}

# Which hide channels each root currently owns, plus the settings that produced
# them. Keyed by object pointer and paired with the object itself, because
# Blender recycles pointers and a fresh object must not inherit a deleted one's
# state. This is runtime state rather than file data, and it exists so that
# switching a channel off hands the flags back exactly once instead of on every
# depsgraph update, which would otherwise fight the user over manual hides, and
# so that a repeat apply with unchanged settings can be skipped.
_managed: dict[int, tuple[object, dict[str, bool], tuple]] = {}

# Wall clock of the last sweep for enabled nesters, see scan_enabled.
_last_scan = 0.0

_CHANNELS = ("use_viewport", "use_render")


def _is_alive(obj) -> bool:
    """False once the object has been removed from the file."""
    try:
        obj.layer_nester.enabled
    except (ReferenceError, AttributeError):
        return False
    return True


class _Busy:
    """Context manager marking LayerNester as writing visibility flags."""

    def __enter__(self):
        global _busy
        self._outermost = not _busy
        _busy = True
        return self

    def __exit__(self, *exc):
        global _busy
        if self._outermost:
            _busy = False
        return False


def is_busy() -> bool:
    """True while visibility flags are being written."""
    return _busy


# ----------------------------------------------------------------------------
# Hierarchy walking


def iter_subtree(root):
    """Yield ``root`` then every descendant, parents before children.

    Siblings keep their ``Object.children`` order, which is the order the
    nester levels index into.
    """
    stack = [root]
    while stack:
        obj = stack.pop()
        yield obj
        children = obj.children
        if children:
            stack.extend(reversed(children))


def subtree_depth(root):
    """Number of nester levels needed to address the deepest object.

    Returns ``0`` when ``root`` has no children, ``1`` when its children are
    leaves, and so on.
    """
    depth = 0
    stack = [(root, 0)]
    while stack:
        obj, level = stack.pop()
        if level > depth:
            depth = level
            if depth >= _MAX_WALK:
                break
        children = obj.children
        if children:
            stack.extend((child, level + 1) for child in reversed(children))
    return depth


def child_count_at(root, values):
    """Number of children selectable at ``root`` after following ``values``.

    ``values`` are the level values of the levels *above* the one being
    measured.  Used to size and label that level's slider.
    """
    node = root
    for value in values:
        if value <= 0:
            return 0
        children = node.children
        if not children:
            return 0
        node = children[min(value, len(children)) - 1]
    return len(node.children)


def level_child_name(root, values, level):
    """Name of the child the given level points at, or ``None``."""
    node = root
    for value in values[:level]:
        if value <= 0:
            return None
        children = node.children
        if not children:
            return None
        node = children[min(value, len(children)) - 1]
    children = node.children
    if not children:
        return None
    value = values[level] if level < len(values) else 0
    if value <= 0 or value > len(children):
        return None
    return children[value - 1].name


def ancestors_to(obj, stop):
    """Chain from ``obj`` up to and including ``stop``."""
    chain = []
    current = obj
    while current is not None:
        chain.append(current)
        if current is stop:
            break
        current = current.parent
    return chain


def hierarchy_level(obj):
    """Number of parents above ``obj``, used to order nested nesters."""
    count = 0
    current = obj.parent
    while current is not None and count < _MAX_WALK:
        count += 1
        current = current.parent
    return count


# ----------------------------------------------------------------------------
# Resolution


def resolve(root, values, show_parents=False):
    """Objects that must stay visible for the given level ``values``.

    ``values`` may be shorter than the stored depth; the missing levels count
    as ``0``.
    """
    if not values:
        return list(iter_subtree(root))

    node = root
    for value in values:
        if value <= 0:
            break
        children = node.children
        if not children:
            break
        node = children[min(value, len(children)) - 1]

    visible = list(iter_subtree(node))
    if show_parents and node is not root:
        visible.extend(ancestors_to(node.parent, root))
    return visible


def is_visible(root, obj):
    """True when ``obj`` stays visible for ``root``'s current level values.

    Objects outside the subtree are not managed, so they count as visible.
    """
    if obj is root or obj not in root.children_recursive:
        return True
    settings = root.layer_nester
    visible = {o.as_pointer() for o in resolve(
        root, settings.level_values(), settings.show_parents)}
    return obj.as_pointer() in visible


# ----------------------------------------------------------------------------
# Level storage


_syncing = False


def set_depth(root, depth):
    """Resize the level storage to exactly ``depth`` sliders."""
    settings = root.layer_nester
    while len(settings.path) < depth:
        settings.path.add()
    while len(settings.path) > depth:
        settings.path.remove(len(settings.path) - 1)
    if settings.depth != depth:
        settings.depth = depth
    if settings.computed_depth != depth:
        settings.computed_depth = depth
    sync_limits(root)


def sync_limits(root):
    """Match every slider to the level value above it.

    Level *i* indexes into the children of whatever levels ``0..i-1`` point
    at, so the counts and names follow the sliders above them.  Values outside
    the range are clamped, which is what keeps a slider honest after children
    are deleted or renamed.
    """
    global _syncing
    if _syncing:
        return

    settings = root.layer_nester
    with _Busy():
        _syncing = True
        try:
            values = settings.level_values()
            for index, level in enumerate(settings.path):
                count = child_count_at(root, values[:index])
                if count != level.child_count:
                    level.child_count = count
                if count == 0:
                    # Not reachable, the level above already shows a whole
                    # branch. Leave the value alone.
                    if level.child_name:
                        level.child_name = ""
                    continue
                value = min(max(level.value, 0), count)
                if value != level.value:
                    # Triggers the level update callback, which returns early
                    # because we are inside _Busy().
                    level.value = value
                values[index] = value
                name = level_child_name(root, values, index) or ""
                if name != level.child_name:
                    level.child_name = name
        finally:
            _syncing = False


def scan_depth(root, grow_only=True):
    """Refresh the stored depth from the hierarchy.

    By default the slider count only grows, per SPECS.md the count must stay
    stable.  ``grow_only=False`` shrinks it back to what the hierarchy needs,
    which is what the rescan operator uses.
    """
    settings = root.layer_nester
    depth = subtree_depth(root)
    if settings.computed_depth != depth:
        settings.computed_depth = depth

    if grow_only:
        if depth <= settings.depth:
            return False
    elif depth == settings.depth:
        return False

    set_depth(root, depth)
    return True


# ----------------------------------------------------------------------------
# Visibility


def _channels(root):
    """The hide channels this root is set up to manage."""
    settings = root.layer_nester
    return {name: bool(getattr(settings, name)) for name in _CHANNELS}


def _signature(root):
    """Everything a write depends on, as a comparable value.

    The hide flags are a pure function of the level values, the parent option
    and the channels, but the child counts matter too: a child added at a level
    that is already there leaves every level value untouched while still needing
    the new object hidden.  ``sync_limits`` maintains those counts, so comparing
    them is how a repeat apply notices the subtree changed without walking it.
    """
    settings = root.layer_nester
    return (
        tuple(level.value for level in settings.path),
        tuple(level.child_count for level in settings.path),
        settings.depth,
        settings.computed_depth,
        settings.show_parents,
        tuple(_channels(root)[name] for name in _CHANNELS),
    )


def _last_signature(root):
    """The signature behind the flags currently on screen, or ``None``."""
    entry = _managed.get(root.as_pointer())
    if entry is None or entry[0] is not root:
        return None
    return entry[2]


def _previous_channels(root):
    """The channels this root owned on its last write, or ``None``."""
    entry = _managed.get(root.as_pointer())
    if entry is None or entry[0] is not root:
        return None
    return entry[1]


def _write_channel(root, visible, channel):
    """Write one hide channel across every descendant of ``root``.

    ``visible`` holds the pointers that must stay visible, or ``None`` to only
    un-hide, which is how the flags of a channel that was switched off are
    handed back to the user.
    """
    viewport = channel == "use_viewport"
    for obj in iter_subtree(root):
        if obj is root:
            continue
        hidden = visible is not None and obj.as_pointer() not in visible
        if viewport:
            if obj.hide_viewport != hidden:
                obj.hide_viewport = hidden
        elif obj.hide_render != hidden:
            obj.hide_render = hidden


def _write(root):
    """Push ``root``'s level values onto the hide flags of every descendant.

    Both channels are handled in one pass over the subtree. This runs on every
    value change, so while dragging a slider it runs once per step and a second
    walk is not free.
    """
    settings = root.layer_nester
    previous = _previous_channels(root)
    channels = _channels(root)
    signature = _signature(root)
    visible = None
    released = set()
    for channel, on in channels.items():
        if on:
            if visible is None:
                visible = {obj.as_pointer() for obj in resolve(
                    root, settings.level_values(), settings.show_parents)}
        elif previous is not None and previous.get(channel):
            # Switched off since the last write, so release it once. Doing this
            # on every apply instead would undo the user's own hides.
            released.add(channel)

    if visible is not None or released:
        free_viewport = "use_viewport" in released
        free_render = "use_render" in released
        for obj in iter_subtree(root):
            if obj is root:
                continue
            hidden = visible is not None and obj.as_pointer() not in visible
            if channels["use_viewport"] or free_viewport:
                wanted = False if free_viewport else hidden
                if obj.hide_viewport != wanted:
                    obj.hide_viewport = wanted
            if channels["use_render"] or free_render:
                wanted = False if free_render else hidden
                if obj.hide_render != wanted:
                    obj.hide_render = wanted

    _managed[root.as_pointer()] = (root, channels, signature)


def _apply_locked(root, force=False):
    """Gate the write on the signature. The caller must already hold the busy flag."""
    signature = _signature(root)
    if not force and _last_signature(root) == signature:
        return
    _write(root)


def apply(root, force=False):
    """Push ``root``'s level values onto its descendants' visibility flags.

    ``force`` writes even when nothing that matters has changed.  The caller
    that reacts to hierarchy edits wants that, because an edit can move an
    object between branches without altering any level value.  The caller that
    runs on every animation frame does not: a frame where the settings happen to
    match the ones already on screen is the common case, and skipping it keeps
    a playing animation from walking the subtree for nothing.
    """
    if _busy or not root.layer_nester.enabled:
        return
    with _Busy():
        _apply_locked(root, force=force)


def release(root):
    """Un-hide every descendant, used when a nester is switched off."""
    previous = _previous_channels(root) or {}
    _managed.pop(root.as_pointer(), None)
    # Release a channel if we own it now, or owned it until this moment.
    owned = {channel for channel, on in _channels(root).items() if on}
    owned |= {channel for channel, on in previous.items() if on}
    with _Busy():
        for channel in owned:
            _write_channel(root, None, channel)


def nester_roots():
    """Every enabled nester, outermost first.

    Outermost first means a nested nester writes its flags last and therefore
    wins over the nester above it, which is what a user expects when nesters
    are nested.

    Only objects that were switched on at some point are looked at, so this
    stays cheap enough to call on every frame.
    """
    roots = []
    for key, obj in list(_roots.items()):
        if not _is_alive(obj):
            _roots.pop(key, None)
            _managed.pop(key, None)
        elif obj.layer_nester.enabled:
            roots.append(obj)
        elif key in _managed:
            # Tracked but now switched off. Switch it off by hand and the update
            # callback has already released it; switch it off through animation
            # or a driver and that callback never runs, so release it here or
            # the hides would be left in place. Staying tracked means switching
            # it back on needs no new sweep.
            release(obj)

    roots.sort(key=hierarchy_level)
    return roots


def scan_enabled(max_interval=0.5, now=None):
    """Register nesters that were switched on without the update callback.

    Animation and drivers change property values without ever running an
    ``update`` callback, so an object whose ``enabled`` flag is animated is
    never registered by that path and the frame handler would never look at it.
    This walks every object in the file, which is too much to do on every
    depsgraph update, so it is throttled to one walk per ``max_interval``
    seconds. Returns True when it registered something.
    """
    global _last_scan
    if now is None:
        now = time.monotonic()
    if now - _last_scan < max_interval:
        return False
    _last_scan = now

    fresh = []
    for obj in bpy.data.objects:
        try:
            if not obj.layer_nester.enabled:
                continue
        except (ReferenceError, AttributeError):
            continue
        key = obj.as_pointer()
        if _roots.get(key) is not obj:
            _roots[key] = obj
            fresh.append(obj)

    if fresh:
        with _Busy():
            for obj in fresh:
                # An object enabled by animation has no sliders yet, so give it
                # the same set an interactive enable would have given it.
                set_depth(obj, subtree_depth(obj))
                sync_limits(obj)
    return bool(fresh)


def register_root(obj):
    """Start tracking ``obj`` as a possible nester root."""
    _roots[obj.as_pointer()] = obj


def unregister_root(obj):
    """Stop tracking ``obj``."""
    _roots.pop(obj.as_pointer(), None)


def rebuild_roots():
    """Rebuild the tracked set from scratch, used after loading a file."""
    global _last_scan
    _last_scan = 0.0
    _roots.clear()
    _managed.clear()
    for obj in bpy.data.objects:
        try:
            if obj.layer_nester.enabled:
                _roots[obj.as_pointer()] = obj
        except (ReferenceError, AttributeError):
            continue


def apply_all(force=False):
    """Re-apply every enabled nester in the file.

    Called on every animation frame, so it skips roots whose settings have not
    moved since the last write.
    """
    if _busy:
        return
    with _Busy():
        for root in nester_roots():
            _apply_locked(root, force=force)
