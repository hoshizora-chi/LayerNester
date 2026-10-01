# SPDX-License-Identifier: GPL-2.0-or-later
"""Headless tests for LayerNester.

Run with::

    blender -b --factory-startup --python tests/test_layernester.py
"""

from __future__ import annotations

import os
import sys
import traceback

import bpy

# The add-on package is the repository root itself, so it is imported by its
# directory name from one level above.
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_REPO_DIR))

import LayerNester  # noqa: E402
from LayerNester import handlers, nester  # noqa: E402


# ----------------------------------------------------------------------------
# Tiny test harness

TESTS = []
FAILURES = []


def test(fn):
    TESTS.append(fn)
    return fn


class Failure(AssertionError):
    pass


def check(condition, message):
    if not condition:
        raise Failure(message)


def check_equal(got, want, message):
    if got != want:
        raise Failure(f"{message}: got {got!r}, want {want!r}")


# ----------------------------------------------------------------------------
# Helpers


def new_object(name, parent=None):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def spec_hierarchy():
    """The exact tree from SPECS.md."""
    parent = new_object("Parent")
    group1 = new_object("Child Group 1", parent)
    child1 = new_object("Child 1", group1)
    group2 = new_object("Child Group 2", parent)
    child2 = new_object("Child 2", group2)
    child3 = new_object("Child 3", group2)
    child4 = new_object("Child 4", parent)
    return parent, group1, child1, group2, child2, child3, child4


def parent_of(root, name):
    """The child of ``root`` that contains ``name``, by name."""
    for child in root.children:
        if name in {obj.name for obj in nester.iter_subtree(child)}:
            return child
    raise KeyError(name)


def levels_for(root, name):
    """Level values that make ``name`` the only visible object.

    Used instead of hard coded numbers, so the tests keep working whatever
    order Blender lists children in, and whatever depth the tree has.
    """
    node = bpy.data.objects[name]
    chain = []
    while node is not root and node.parent is not None:
        chain.append(node)
        node = node.parent
    if node is not root:
        raise KeyError(f"{name} is not under {root.name}")

    chain.reverse()  # from the direct child of root down to name
    values = []
    for child in chain:
        values.append(index_of(root, child.name, above=tuple(values)))
    while len(values) < root.layer_nester.depth:
        values.append(0)  # stop descending here
    return tuple(values)


def set_levels(parent, *values):
    """Set the nester sliders, growing the storage as needed."""
    settings = parent.layer_nester
    for _ in range(len(values) - len(settings.path)):
        settings.path.add()
    for level, value in zip(settings.path, values):
        level.value = value


def viewport_visible(obj):
    return not obj.hide_viewport


def visible_names(parent):
    """Names of the visible descendants of ``parent``, the root excluded."""
    return [obj.name for obj in nester.iter_subtree(parent)
            if obj is not parent and viewport_visible(obj)]


def index_of(parent, name, above=()):
    """Level value that picks the child called ``name``.

    Level values index into ``Object.children``, which is the order the
    outliner shows, so the tests ask for the value by name rather than
    hard coding numbers that depend on how Blender orders children.
    """
    node = parent
    for value in above:
        node = node.children[value - 1]
    return [child.name for child in node.children].index(name) + 1


def render_visible(obj):
    return not obj.hide_render


def refresh():
    """Force a depsgraph update so the add-on's handler gets a chance to run."""
    bpy.context.view_layer.update()
    bpy.context.evaluated_depsgraph_get().update()


def wipe():
    # Animation and drivers have to go with the objects, and the frame has to
    # go back to the start, or a leftover curve would drive the next test.
    if bpy.data.actions:
        for action in list(bpy.data.actions):
            bpy.data.actions.remove(action)
    bpy.context.scene.frame_set(1)
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    nester.rebuild_roots()


# ----------------------------------------------------------------------------
# SPECS.md


@test
def test_level_one_updates_on_every_single_change():
    """Each step of a drag must take effect, not only the last one."""
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True

    check_equal([obj.name for obj in parent.children],
                ["Child 4", "Child Group 1", "Child Group 2"],
                "level values index the outliner order")

    # Asserted inside the loop on purpose: a check that only looked at the
    # final value would pass even if the intermediate steps never applied.
    for value, expected in ((1, ["Child 4"]),
                            (2, ["Child Group 1", "Child 1"]),
                            (3, ["Child Group 2", "Child 2", "Child 3"])):
        parent.layer_nester.path[0].value = value
        check_equal(visible_names(parent), expected,
                    f"level 1 at {value} applied immediately")

    parent.layer_nester.path[0].value = 0
    check_equal(len(visible_names(parent)), 6, "and zero still shows everything")


@test
def test_level_two_updates_on_every_single_change():
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    group2_value = index_of(parent, "Child Group 2")
    parent.layer_nester.path[0].value = group2_value

    # show_parents is off, so the group itself stays hidden while descending.
    for value, expected in ((1, ["Child 2"]),
                            (2, ["Child 3"]),
                            (3, ["Child 3"])):  # clamps, Child Group 2 has 2 children
        parent.layer_nester.path[1].value = value
        check_equal(visible_names(parent), expected,
                    f"level 2 at {value} applied immediately")

    parent.layer_nester.path[1].value = 0
    check_equal(visible_names(parent),
                ["Child Group 2", "Child 2", "Child 3"],
                "zero on level 2 shows the whole group again")


@test
def test_slider_count_matches_deepest_nest():
    """The amount of sliders is the highest nest in the group."""
    wipe()
    parent, *_ = spec_hierarchy()
    check_equal(nester.subtree_depth(parent), 2, "subtree depth of the spec tree")
    check_equal(len(list(nester.iter_subtree(parent))), 7,
                "objects in the spec tree, the root included")

    parent.layer_nester.enabled = True
    check_equal(parent.layer_nester.depth, 2, "stored slider count")
    check_equal(len(parent.layer_nester.path), 2, "slider storage size")


@test
def test_spec_example_1_child_1_visible():
    """Level 1 picks Child Group 1, level 2 picks Child 1 -> only Child 1 shows."""
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, index_of(parent, "Child Group 1"), 1)

    check_equal(visible_names(parent), ["Child 1"],
                "only Child 1 should show")


@test
def test_spec_example_2_child_3_visible():
    """Level 1 picks Child Group 2, level 2 picks Child 3 -> only Child 3 shows."""
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, *levels_for(parent, "Child 3"))

    check_equal(visible_names(parent), ["Child 3"],
                "only Child 3 should show")


@test
def test_spec_example_3_child_4_visible():
    """Level 1 picks Child 4, level 2 stays 0 -> only Child 4 shows."""
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, index_of(parent, "Child 4"), 0)

    check_equal(visible_names(parent), ["Child 4"], "only Child 4 should show")


@test
def test_spec_examples_are_reachable_in_every_order():
    """The three examples of SPECS.md, whatever order Blender lists children in."""
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    check_equal(len(parent.layer_nester.path), 2, "two sliders")

    for name in ("Child 1", "Child 2", "Child 3", "Child 4"):
        values = levels_for(parent, name)
        set_levels(parent, *values)
        check_equal(visible_names(parent), [name],
                    f"{name} alone should show at levels {values}")


@test
def test_level_indices_follow_the_outliner():
    """Level values index ``Object.children``, i.e. the order the outliner shows."""
    wipe()
    parent = new_object("Parent")
    new_object("Zeta", parent)
    new_object("Alpha", parent)
    new_object("Mu", parent)

    order = [child.name for child in parent.children]
    parent.layer_nester.enabled = True
    for value, name in enumerate(order, start=1):
        set_levels(parent, value)
        check_equal(visible_names(parent), [name], f"value {value} selects {name}")


@test
def test_zero_shows_the_whole_branch():
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True

    everything = [
        obj.name for obj in nester.iter_subtree(parent)
        if obj is not parent
    ]
    check_equal(len(everything), 6, "the spec tree has six descendants")

    set_levels(parent, 0, 0)
    check_equal(sorted(visible_names(parent)), sorted(everything),
                "all zeros show everything")

    group1_value = index_of(parent, "Child Group 1")
    set_levels(parent, group1_value, 0)
    check_equal(sorted(visible_names(parent)), ["Child 1", "Child Group 1"],
                "a zero on the second level shows that whole group")

    group2_value = index_of(parent, "Child Group 2")
    set_levels(parent, group2_value, 0)
    check_equal(sorted(visible_names(parent)),
                ["Child 2", "Child 3", "Child Group 2"],
                "level 1 on a two child group shows the whole group")


@test
def test_render_follows_viewport():
    wipe()
    parent, group1, child1, group2, child2, child3, child4 = spec_hierarchy()
    parent.layer_nester.enabled = True
    group2_value = index_of(parent, "Child Group 2")
    set_levels(parent, group2_value, index_of(parent, "Child 3", above=(group2_value,)))

    check(not viewport_visible(child1), "the test needs Child 1 to be hidden")
    for obj in (group1, child1, group2, child2, child3, child4):
        check_equal(render_visible(obj), viewport_visible(obj),
                    f"{obj.name} render vs viewport")


@test
def test_render_can_be_left_alone():
    wipe()
    parent, group1, child1, group2, child2, child3, child4 = spec_hierarchy()
    parent.layer_nester.enabled = True
    parent.layer_nester.use_render = False
    group1_value = index_of(parent, "Child Group 1")
    set_levels(parent, group1_value, 1)

    check(not child2.hide_render, "use_render off leaves the flag alone")
    check(not child3.hide_render, "use_render off leaves the flag alone")
    check(not child4.hide_render, "use_render off leaves the flag alone")
    check(not child1.hide_viewport, "viewport is still managed")
    check(not viewport_visible(child2), "viewport is still managed")


@test
def test_turning_off_a_channel_hands_the_flags_back():
    wipe()
    parent, group1, child1, group2, child2, child3, child4 = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, index_of(parent, "Child Group 1"), 1)
    check(not viewport_visible(child4), "the test needs something hidden")

    parent.layer_nester.use_viewport = False
    check_equal(sorted(obj.name for obj in parent.children_recursive
                       if not obj.hide_viewport),
                sorted(["Child 4", "Child Group 1", "Child Group 2", "Child 1",
                        "Child 2", "Child 3"]),
                "switching Viewport off reveals what it had hidden")

    parent.layer_nester.use_render = False
    for obj in parent.children_recursive:
        check(not obj.hide_render, f"{obj.name} render flag was handed back")
        check(not obj.hide_viewport, f"{obj.name} viewport flag is untouched too")


@test
def test_a_released_channel_leaves_manual_hides_alone():
    """Releasing a channel once must not keep overriding the user."""
    wipe()
    parent, group1, child1, group2, child2, child3, child4 = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, index_of(parent, "Child Group 1"), 1)
    parent.layer_nester.use_viewport = False

    child4.hide_viewport = True
    for _ in range(3):
        refresh()
    check(child4.hide_viewport, "a hide made after the release survives")

    # The render channel is still ours, so it keeps tracking the sliders.
    parent.layer_nester.path[1].value = 1
    check(child3.hide_render, "render still follows the sliders")
    check(child4.hide_viewport, "viewport is still left to the user")


@test
def test_switching_a_channel_back_on_takes_over_again():
    wipe()
    parent, group1, child1, group2, child2, child3, child4 = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, index_of(parent, "Child Group 1"), 1)
    parent.layer_nester.use_viewport = False
    check(viewport_visible(child4), "released")

    parent.layer_nester.use_viewport = True
    check(not viewport_visible(child4), "hiding resumes")
    group2_value = index_of(parent, "Child Group 2")
    set_levels(parent, group2_value,
               index_of(parent, "Child 3", above=(group2_value,)))
    check(viewport_visible(child3), "and follows the new selection")
    check(not viewport_visible(child1), "for every branch")
    check(not viewport_visible(child2), "including the other sibling")


@test
def test_registry_does_not_grow_over_repeated_edits():
    """Deleted roots must actually leave the registry.

    A removed bpy object hashes to 0, so holding the objects in a plain set
    would make the entry unreachable and grow the registry forever.
    """
    wipe()
    for cycle in range(4):
        for index in range(6):
            obj = new_object(f"Cycle{cycle}_{index}")
            obj.layer_nester.enabled = True
        check_equal(len(nester.nester_roots()), 6, f"cycle {cycle} sees its roots")

        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        check_equal(nester.nester_roots(), [], f"cycle {cycle} is empty again")
        check_equal(len(nester._roots), 0, f"cycle {cycle} left no registry entry")
        check_equal(len(nester._managed), 0, f"cycle {cycle} left no channel entry")


@test
def test_channel_state_is_matched_to_the_object_not_only_the_pointer():
    """Blender hands pointers out again, so an old entry must not be adopted."""
    wipe()
    first, second = new_object("First"), new_object("Second")
    try:
        nester._managed[first.as_pointer()] = (
            second, {"use_viewport": True, "use_render": True})
        check(nester._previous_channels(first) is None,
              "an entry belonging to another object is ignored")

        nester._managed[first.as_pointer()] = (
            first, {"use_viewport": True, "use_render": True})
        check_equal(nester._previous_channels(first),
                    {"use_viewport": True, "use_render": True},
                    "the object's own entry is used")
    finally:
        nester._managed.clear()


@test
def test_channel_state_is_dropped_when_a_root_is_deleted():
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    key = parent.as_pointer()
    check(key in nester._managed, "the root recorded its channels")

    bpy.data.objects.remove(parent, do_unlink=True)
    nester.nester_roots()
    check(key not in nester._managed, "and the entry went with it")
    check(not nester._roots, "the root itself was forgotten")


# ----------------------------------------------------------------------------
# Enable and disable

@test
def test_disabled_by_default():
    wipe()
    parent, *_ = spec_hierarchy()
    check(not parent.layer_nester.enabled, "layer nester is off by default")
    check_equal(parent.layer_nester.depth, 0, "no sliders by default")
    check_equal(len(visible_names(parent)), 6, "nothing is hidden while disabled")


@test
def test_disabling_restores_visibility():
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    group2_value = index_of(parent, "Child Group 2")
    set_levels(parent, group2_value, index_of(parent, "Child 3", above=(group2_value,)))
    check_equal(len(visible_names(parent)), 1, "only the chosen leaf shows")

    parent.layer_nester.enabled = False
    check_equal(len(visible_names(parent)), 6, "disabling brings everything back")


@test
def test_nester_root_is_never_hidden():
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, index_of(parent, "Child 4"), 0)
    check(viewport_visible(parent), "the nester root stays visible")
    check(render_visible(parent), "the nester root stays renderable")


@test
def test_leaf_object_has_no_sliders():
    wipe()
    parent, group1, child1, *_ = spec_hierarchy()
    group1.layer_nester.enabled = True
    check_equal(group1.layer_nester.depth, 1, "a group with one child needs one slider")
    set_levels(group1, 1)
    check_equal(visible_names(group1), ["Child 1"], "the single child shows")


# ----------------------------------------------------------------------------
# Slider range and labels


@test
def test_slider_labels_follow_the_level_above():
    wipe()
    parent, group1, child1, group2, child2, child3, child4 = spec_hierarchy()
    parent.layer_nester.enabled = True

    check_equal(parent.layer_nester.path[0].child_count, 3,
                "level 1 counts the three children of Parent")
    check_equal(parent.layer_nester.path[0].child_name, "",
                "level 1 has no child name at 0")
    check_equal(parent.layer_nester.path[1].child_count, 0,
                "level 2 is unreachable while level 1 is 0")

    group2_value = index_of(parent, "Child Group 2")
    set_levels(parent, group2_value, 0)
    check_equal(parent.layer_nester.path[0].child_name, "Child Group 2",
                "level 1 names the child it points at")
    check_equal(parent.layer_nester.path[1].child_count, 2,
                "level 2 counts Child 2 and Child 3")

    group1_value = index_of(parent, "Child Group 1")
    set_levels(parent, group1_value, 0)
    check_equal(parent.layer_nester.path[1].child_count, 1,
                "level 2 follows back to the group with one child")


@test
def test_out_of_range_value_is_clamped():
    wipe()
    parent, group1, child1, group2, child2, child3, child4 = spec_hierarchy()
    parent.layer_nester.enabled = True

    parent.layer_nester.path[0].value = 99
    check_equal(parent.layer_nester.path[0].value, 3, "clamped to the child count")
    last = parent.children[-1]
    check_equal(parent.layer_nester.path[0].child_name, last.name,
                "the slider points at the last child")
    want = [obj.name for obj in nester.iter_subtree(last)]
    check_equal(visible_names(parent), want,
                "the last child and its whole subtree show after clamping")

    group1_value = index_of(parent, "Child Group 1")
    set_levels(parent, group1_value, 99)
    check_equal(parent.layer_nester.path[1].value, 1,
                "clamped to the child count one level down")


@test
def test_deleting_a_child_reclamps():
    wipe()
    parent, group1, child1, group2, child2, child3, child4 = spec_hierarchy()
    parent.layer_nester.enabled = True
    group2_value = index_of(parent, "Child Group 2")
    child2_value = index_of(parent, "Child 2", above=(group2_value,))
    set_levels(parent, group2_value, child2_value)
    check_equal(visible_names(parent), ["Child 2"], "Child 2 shows")
    check(not viewport_visible(child3), "Child 3 is hidden first")

    bpy.data.objects.remove(child2, do_unlink=True)
    refresh()
    check_equal(parent.layer_nester.path[1].child_name, "Child 3",
                "the level slid onto the child that is left")
    check(viewport_visible(child3), "Child 3 takes the place of Child 2")


# ----------------------------------------------------------------------------
# Slider count stability


@test
def test_slider_count_grows_but_never_shrinks():
    wipe()
    parent, group1, child1, group2, child2, child3, child4 = spec_hierarchy()
    parent.layer_nester.enabled = True
    check_equal(parent.layer_nester.depth, 2, "two sliders for the spec tree")

    nester.scan_depth(parent, grow_only=True)
    check_equal(parent.layer_nester.depth, 2, "no change while the tree is the same")

    bpy.data.objects.remove(child4, do_unlink=True)
    check(not nester.scan_depth(parent, grow_only=True),
          "a shallower tree does not trigger a rescan")
    check_equal(parent.layer_nester.depth, 2, "the count stays put")

    nester.scan_depth(parent, grow_only=False)
    check_equal(parent.layer_nester.depth, 2, "still deep enough after the removal")


@test
def test_deeper_nesting_grows_the_count():
    wipe()
    parent, group1, child1, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    check_equal(parent.layer_nester.depth, 2, "two sliders to start with")

    # Hang a new group two levels below Child Group 1.
    deep = new_object("Deep", child1)
    new_object("Deeper", deep)
    check(nester.scan_depth(parent, grow_only=True), "deeper nesting is detected")
    check_equal(parent.layer_nester.depth, 4, "the count grew")
    check_equal(len(parent.layer_nester.path), 4, "storage grew with it")

    set_levels(parent, index_of(parent, "Child Group 1"), 1, 1, 1)
    check_equal(visible_names(parent), ["Deeper"],
                "the deepest object is reachable")
    parent.layer_nester.show_parents = True
    check_equal(sorted(visible_names(parent)),
                ["Child 1", "Child Group 1", "Deep", "Deeper"],
                "the path leading to it is kept when asked for")


@test
def test_rescan_operator_shrinks_to_fit():
    wipe()
    parent, group1, child1, group2, child2, child3, child4 = spec_hierarchy()
    deep = new_object("Deep", child1)
    new_object("Deeper", deep)
    parent.layer_nester.enabled = True
    check_equal(parent.layer_nester.depth, 4, "four sliders")

    bpy.data.objects.remove(child1, do_unlink=True)
    bpy.data.objects.remove(deep, do_unlink=True)
    check_equal(parent.layer_nester.depth, 4, "still four before the rescan")

    parent.select_set(True)
    bpy.context.view_layer.objects.active = parent
    check_equal(bpy.ops.layernester.rescan(), {"FINISHED"}, "rescan runs")
    check_equal(parent.layer_nester.depth, 2, "rescan shrank the count to fit")
    check_equal(len(parent.layer_nester.path), 2, "storage shrank too")


# ----------------------------------------------------------------------------
# Deeper trees


@test
def test_three_level_tree():
    wipe()
    parent = new_object("Parent")
    c1 = new_object("C1", parent)
    g1 = new_object("G1", c1)
    l1 = new_object("L1", g1)
    g2 = new_object("G2", c1)
    l2 = new_object("L2", g2)
    c2 = new_object("C2", parent)

    parent.layer_nester.enabled = True
    check_equal(parent.layer_nester.depth, 3, "three levels deep")

    for values, want in (
        ((1, 1, 1), ["L1"]),
        ((1, 1, 0), ["G1", "L1"]),
        ((1, 2, 1), ["L2"]),
        ((1, 2, 0), ["G2", "L2"]),
        ((1, 0, 0), ["C1", "G1", "L1", "G2", "L2"]),
        ((2, 0, 0), ["C2"]),
        ((0, 0, 0), ["C1", "C2", "G1", "G2", "L1", "L2"]),
    ):
        set_levels(parent, *values)
        check_equal(sorted(visible_names(parent)), sorted(want), f"levels {values}")


@test
def test_deep_tree_chain():
    wipe()
    root = new_object("Root")
    node = root
    for index in range(6):
        node = new_object(f"N{index}", node)

    root.layer_nester.enabled = True
    check_equal(root.layer_nester.depth, 6, "six levels")
    whole_chain = ["N0", "N1", "N2", "N3", "N4", "N5"]

    set_levels(root, 1, 1, 1, 1, 1, 1)
    check_equal(visible_names(root), ["N5"],
                "descending every level lands on the deepest leaf")

    set_levels(root, 1, 1, 1, 1, 0, 0)
    check_equal(visible_names(root), ["N3", "N4", "N5"],
                "a zero part way down shows the rest of the chain")

    set_levels(root, 1, 0, 0, 0, 0, 0)
    check_equal(visible_names(root), whole_chain,
                "a zero on the first level shows everything")

    set_levels(root, 0, 0, 0, 0, 0, 0)
    check_equal(visible_names(root), whole_chain, "all zeros show everything")

    root.layer_nester.show_parents = True
    set_levels(root, 1, 1, 1, 1, 1, 1)
    check_equal(visible_names(root), whole_chain,
                "show parents keeps the path to the leaf")


# ----------------------------------------------------------------------------
# Options


@test
def test_show_parents_keeps_the_path_visible():
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    parent.layer_nester.show_parents = True

    group2_value = index_of(parent, "Child Group 2")
    set_levels(parent, group2_value, index_of(parent, "Child 3", above=(group2_value,)))
    check_equal(sorted(visible_names(parent)), ["Child 3", "Child Group 2"],
                "the group on the path stays visible")

    group1_value = index_of(parent, "Child Group 1")
    set_levels(parent, group1_value, 1)
    check_equal(sorted(visible_names(parent)), ["Child 1", "Child Group 1"],
                "the other group is hidden")


@test
def test_viewport_only():
    wipe()
    parent, group1, child1, group2, child2, child3, child4 = spec_hierarchy()
    parent.layer_nester.enabled = True
    parent.layer_nester.use_viewport = False
    group1_value = index_of(parent, "Child Group 1")
    set_levels(parent, group1_value, 1)

    for obj in (group1, child1, group2, child2, child3, child4):
        check(viewport_visible(obj), f"{obj.name} is left alone in the viewport")
    check(not render_visible(group2), "render is still managed")
    check(not render_visible(child2), "render is still managed")
    check(render_visible(child1), "the shown branch still renders")


# ----------------------------------------------------------------------------
# Operators


@test
def test_show_all_operator():
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, index_of(parent, "Child Group 2"), 1)
    parent.select_set(True)
    bpy.context.view_layer.objects.active = parent

    check_equal(bpy.ops.layernester.release(), {"FINISHED"}, "release runs")
    check_equal([level.value for level in parent.layer_nester.path], [0, 0],
                "every slider is back at 0")
    check_equal(len(visible_names(parent)), 6, "everything shows again")


@test
def test_operators_need_an_enabled_nester():
    wipe()
    parent, *_ = spec_hierarchy()
    parent.select_set(True)
    bpy.context.view_layer.objects.active = parent

    check_equal(bpy.ops.layernester.rescan(), {"CANCELLED"},
                "rescan refuses without an enabled nester")
    check_equal(bpy.ops.layernester.release(), {"CANCELLED"},
                "release refuses without an enabled nester")
    check_equal(bpy.ops.layernester.select_visible(), {"CANCELLED"},
                "select visible refuses without an enabled nester")


@test
def test_select_visible_operator():
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    group2_value = index_of(parent, "Child Group 2")
    set_levels(parent, group2_value, index_of(parent, "Child 3", above=(group2_value,)))
    parent.select_set(True)
    bpy.context.view_layer.objects.active = parent

    check_equal(bpy.ops.layernester.select_visible(), {"FINISHED"}, "runs")
    selected = sorted(obj.name for obj in bpy.context.selected_objects)
    check_equal(selected, ["Child 3"], "the visible leaf is selected")


@test
def test_select_visible_skips_objects_the_view_layer_cannot_select():
    """A child can live in a collection this view layer does not show."""
    wipe()
    parent, group1, child1, *_ = spec_hierarchy()
    other_scene = bpy.data.scenes.new("Other Scene")
    try:
        # Parent it into a sibling scene, so it is a real child of the nester
        # root but not a member of the active view layer.
        stray = bpy.data.objects.new("Stray", None)
        other_scene.collection.objects.link(stray)
        stray.parent = parent
        bpy.context.view_layer.update()
        check(stray.name not in bpy.context.view_layer.objects,
              "the test needs an object outside the view layer")

        parent.layer_nester.enabled = True
        parent.layer_nester.path[0].value = index_of(parent, "Stray")
        parent.select_set(True)
        bpy.context.view_layer.objects.active = parent

        check_equal(bpy.ops.layernester.select_visible(), {"FINISHED"},
                    "the operator still finishes")
        check_equal(list(bpy.context.selected_objects), [],
                    "Stray is the only thing left visible and it cannot be "
                    "selected, so nothing is")
    finally:
        bpy.data.scenes.remove(other_scene)


@test
def test_apply_all_operator():
    wipe()
    parent, group1, child1, group2, child2, child3, child4 = spec_hierarchy()
    parent.layer_nester.enabled = True
    group2_value = index_of(parent, "Child Group 2")
    set_levels(parent, group2_value, index_of(parent, "Child 3", above=(group2_value,)))
    check(viewport_visible(child3), "Child 3 shows to begin with")

    # Something else hid the chosen branch, apply_all must fix it.
    child3.hide_viewport = True
    child3.hide_render = True
    bpy.ops.layernester.apply_all()
    check(viewport_visible(child3), "apply_all restored Child 3")
    check(render_visible(child3), "apply_all restored Child 3 for render")


@test
def test_apply_all_operator_forces_the_write_by_itself():
    """An explicit "Apply All" must not depend on a callback having run first.

    Without the handlers the depsgraph path cannot quietly repair the flags, so
    this fails if the operator lets the signature gate skip the write.
    """
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, *levels_for(parent, "Child 2"))
    child2 = bpy.data.objects["Child 2"]

    handlers.unregister()
    try:
        child2.hide_viewport = True
        child2.hide_render = True
        bpy.ops.layernester.apply_all()
        check(viewport_visible(child2), "the operator restored the viewport flag")
        check(render_visible(child2), "and the render flag")
    finally:
        handlers.register()


# ----------------------------------------------------------------------------
# Nested nesters


@test
def test_inner_nester_wins():
    wipe()
    root = new_object("Root")
    group_a = new_object("A", root)
    a1 = new_object("A1", group_a)
    a2 = new_object("A2", group_a)
    b = new_object("B", root)

    root.layer_nester.enabled = True
    set_levels(root, 1)  # show the A branch

    group_a.layer_nester.enabled = True
    set_levels(group_a, 1)  # inside A, only A1

    check(viewport_visible(a1), "the inner nester wins for A1")
    check(not viewport_visible(a2), "the inner nester hides A2")
    check(not viewport_visible(b), "the outer nester still hides B")

    set_levels(group_a, 2)
    check(not viewport_visible(a1), "the inner nester hides A1")
    check(viewport_visible(a2), "the inner nester shows A2")

    group_a.layer_nester.enabled = False
    check(viewport_visible(a1), "switching the inner one off hands A1 back")
    check(viewport_visible(a2), "switching the inner one off hands A2 back")
    check(not viewport_visible(b), "the outer nester is unaffected")


# ----------------------------------------------------------------------------
# Handlers
# ----------------------------------------------------------------------------


@test
def test_handler_grows_the_sliders_when_nesting_deepens():
    wipe()
    parent, group1, child1, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    check_equal(parent.layer_nester.depth, 2, "two sliders to start with")

    # A group two levels down appears without the add-on being told.
    group = new_object("Group", child1)
    new_object("Deep", group)
    new_object("Deeper", group)
    refresh()

    check_equal(parent.layer_nester.depth, 4, "the handler grew the slider count")
    check_equal(parent.layer_nester.computed_depth, 4, "and recorded the new depth")
    check_equal(len(parent.layer_nester.path), 4, "storage grew with it")

    set_levels(parent, *levels_for(parent, "Deeper"))
    check_equal(visible_names(parent), ["Deeper"], "the new depth is reachable")


@test
def test_handler_does_not_shrink_the_sliders():
    wipe()
    parent, group1, child1, group2, child2, child3, child4 = spec_hierarchy()
    parent.layer_nester.enabled = True

    # Deleting siblings renumbers the level values, since they index into the
    # children, so the levels are picked again after the edit.
    bpy.data.objects.remove(child4, do_unlink=True)
    bpy.data.objects.remove(child3, do_unlink=True)
    bpy.data.objects.remove(child2, do_unlink=True)
    refresh()

    check_equal(parent.layer_nester.depth, 2, "the count stays put")
    check_equal(parent.layer_nester.computed_depth, 2, "the detected depth dropped")

    set_levels(parent, *levels_for(parent, "Child 1"))
    check_equal(visible_names(parent), ["Child 1"], "and the nester still works")


@test
def test_handler_ignores_disabled_nesters():
    wipe()
    parent, group1, child1, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, *levels_for(parent, "Child 1"))
    parent.layer_nester.enabled = False

    group = new_object("Group", child1)
    new_object("Deep", group)
    refresh()

    check_equal(parent.layer_nester.depth, 2, "a disabled nester is not watched")
    check_equal(len(visible_names(parent)), 8, "the two new objects and nothing hidden")


@test
def test_registry_forgets_deleted_and_disabled_objects():
    wipe()
    parent, group1, child1, *_ = spec_hierarchy()
    child1.layer_nester.enabled = True
    parent.layer_nester.enabled = True
    check_equal(len(nester.nester_roots()), 2, "both are tracked")

    child1.layer_nester.enabled = False
    check_equal([obj.name for obj in nester.nester_roots()], ["Parent"],
                "switching one off drops it")

    parent.layer_nester.enabled = False
    check_equal(nester.nester_roots(), [], "nothing left is tracked")

    # A deleted object must not leave a dead reference behind.
    parent.layer_nester.enabled = True
    bpy.data.objects.remove(parent, do_unlink=True)
    check_equal(nester.nester_roots(), [], "a deleted root is forgotten")

    wipe()
    check_equal(nester.nester_roots(), [], "wiping the file clears the registry")


@test
def test_rebuild_roots_finds_saved_nesters():
    wipe()
    parent, group1, child1, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    nester.unregister_root(parent)
    check_equal(nester.nester_roots(), [], "no longer tracked")

    nester.rebuild_roots()
    check_equal([obj.name for obj in nester.nester_roots()], ["Parent"],
                "rebuild finds it again, as a file load would")


# ----------------------------------------------------------------------------
# Animation and drivers
#
# None of these can be reached by setting a property from Python, because that
# runs the update callback and the whole point is that Blender does not run it
# for an animated or driven value. So each one drives the real handler.


def keyframe_level(parent, index, frame, value):
    """Keyframe one level slider, as the animation editor would."""
    level = parent.layer_nester.path[index]
    level.value = value
    level.keyframe_insert("value", frame=frame)


def drive_level(parent, index, expression):
    """Put a driver on one level slider."""
    fcurve = parent.driver_add(f"layer_nester.path[{index}].value")
    fcurve.driver.expression = expression
    return fcurve


def drive_level_from(parent, index, source, prop):
    """Drive one level slider from a custom property on another object."""
    fcurve = parent.driver_add(f"layer_nester.path[{index}].value")
    driver = fcurve.driver
    var = driver.variables.new()
    var.name = "src"
    var.type = "SINGLE_PROP"
    var.targets[0].id = source
    var.targets[0].data_path = f'["{prop}"]'
    driver.expression = "src"
    return fcurve


@test
def test_animated_level_drives_the_visibility():
    """A keyframed slider has to move the visibility, not just its own value."""
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    keyframe_level(parent, 0, 1, index_of(parent, "Child 4"))
    keyframe_level(parent, 0, 2, index_of(parent, "Child Group 1"))

    bpy.context.scene.frame_set(1)
    check_equal(visible_names(parent), ["Child 4"], "frame 1 shows the first branch")

    bpy.context.scene.frame_set(2)
    check_equal(visible_names(parent), ["Child Group 1", "Child 1"],
                "frame 2 shows the second branch")


@test
def test_animated_second_level_drives_the_visibility():
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    group2 = index_of(parent, "Child Group 2")
    parent.layer_nester.path[0].value = group2
    keyframe_level(parent, 1, 1, index_of(parent, "Child 2", above=(group2,)))
    keyframe_level(parent, 1, 2, index_of(parent, "Child 3", above=(group2,)))

    bpy.context.scene.frame_set(1)
    check_equal(visible_names(parent), ["Child 2"], "frame 1 picks the first leaf")

    bpy.context.scene.frame_set(2)
    check_equal(visible_names(parent), ["Child 3"], "frame 2 picks the second leaf")


@test
def test_animated_level_drives_the_render_flags():
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    keyframe_level(parent, 0, 1, index_of(parent, "Child 4"))
    keyframe_level(parent, 0, 2, index_of(parent, "Child Group 1"))

    bpy.context.scene.frame_set(1)
    shown = [obj.name for obj in nester.iter_subtree(parent)
             if obj is not parent and render_visible(obj)]
    check_equal(shown, ["Child 4"], "the render flags follow too")

    bpy.context.scene.frame_set(2)
    shown = [obj.name for obj in nester.iter_subtree(parent)
             if obj is not parent and render_visible(obj)]
    check_equal(shown, ["Child Group 1", "Child 1"], "on the next frame as well")


@test
def test_time_driven_driver_drives_the_visibility():
    """A driver on the frame number only ever posts frame_change_post."""
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    drive_level(parent, 0, "frame % 4")

    bpy.context.scene.frame_set(1)
    check_equal(visible_names(parent), ["Child 4"], "frame 1 gives level value 1")

    bpy.context.scene.frame_set(2)
    check_equal(visible_names(parent), ["Child Group 1", "Child 1"],
                "frame 2 gives level value 2")

    bpy.context.scene.frame_set(5)
    check_equal(visible_names(parent), ["Child 4"], "and it wraps round")


@test
def test_dependency_driven_driver_drives_the_visibility():
    """A driver fed by another object only ever posts depsgraph_update_post."""
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    source = new_object("Driver Source")
    source["level"] = index_of(parent, "Child 4")
    drive_level_from(parent, 0, source, "level")
    refresh()
    check_equal(visible_names(parent), ["Child 4"], "the driver's first value applied")

    source["level"] = index_of(parent, "Child Group 1")
    source.update_tag()
    refresh()
    check_equal(visible_names(parent), ["Child Group 1", "Child 1"],
                "and it follows when the source changes")


@test
def test_driven_disable_hands_the_branch_back():
    """Switching off without the update callback must still un-hide.

    Only a driver can reach this state. Authoring a keyframe means setting the
    value, and that runs the callback, so a keyframed nester has already been
    released by the time playback switches it off.
    """
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, *levels_for(parent, "Child 1"))
    check_equal(visible_names(parent), ["Child 1"], "hidden while it is on")

    parent.driver_add("layer_nester.enabled").driver.expression = "frame < 2"

    bpy.context.scene.frame_set(2)
    check_equal(parent.layer_nester.enabled, False, "the driver switched it off")
    check_equal(len(visible_names(parent)), 6, "and every descendant is handed back")

    bpy.context.scene.frame_set(1)
    check_equal(parent.layer_nester.enabled, True, "switched on again")
    check_equal(visible_names(parent), ["Child 1"], "and the levels apply once more")


@test
def test_a_nester_switched_on_only_by_animation_is_found():
    """A keyframed toggle never runs the update callback that registers it."""
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    parent.keyframe_insert(data_path="layer_nester.enabled", frame=10)
    parent.layer_nester.enabled = False
    parent.keyframe_insert(data_path="layer_nester.enabled", frame=1)
    nester.unregister_root(parent)

    check_equal(nester.nester_roots(), [], "nothing is tracked to begin with")
    set_levels(parent, *levels_for(parent, "Child 1"))

    bpy.context.scene.frame_set(10)
    check_equal(parent.layer_nester.enabled, True, "the keyframe switched it on")
    check_equal(len(nester.nester_roots()), 1, "and the sweep found it")
    check_equal(visible_names(parent), ["Child 1"], "so the levels take effect")


@test
def test_scan_enabled_is_throttled():
    """The discovery sweep walks every object, so it must not run per frame."""
    wipe()
    parent, *_ = spec_hierarchy()
    nester.rebuild_roots()  # resets the throttle

    check_equal(nester.scan_enabled(now=1000.0), False, "nothing enabled yet")

    parent.layer_nester.enabled = True
    nester.unregister_root(parent)
    check_equal(nester.scan_enabled(now=1001.0), True, "it finds the nester")
    check_equal(nester.scan_enabled(now=1001.1), False, "not again straight away")

    nester.unregister_root(parent)
    check_equal(nester.scan_enabled(now=1002.0), True,
                "but again once the interval has passed")


@test
def test_unchanged_settings_skip_the_write():
    """The per frame path pays for a walk only when the settings moved."""
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, *levels_for(parent, "Child 1"))

    out_of_step = bpy.data.objects["Child Group 2"]
    out_of_step.hide_viewport = False

    nester.apply_all()
    check_equal(out_of_step.hide_viewport, False,
                "an unforced apply leaves unchanged settings alone")

    nester.apply_all(force=True)
    check_equal(out_of_step.hide_viewport, True, "a forced apply puts them back")


@test
def test_signature_notices_a_changed_child_count():
    """A new child moves no level value, so the counts are what reveal it."""
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, *levels_for(parent, "Child 2"))
    check_equal(visible_names(parent), ["Child 2"], "applied")

    new_object("Child 5", parent_of(parent, "Child Group 2"))
    nester.sync_limits(parent)
    check_equal(parent.layer_nester.path[1].child_count, 3,
                "one more child under the branch level 1 points at")
    check_equal(parent.layer_nester.level_values(), [3, 1], "and no level value moved")

    nester.apply_all()
    check("Child 5" not in visible_names(parent),
          "the new child is hidden even though no level value moved")


@test
def test_both_handlers_are_registered_once_and_fully_removed():
    """Both are needed: keyframes post one, drivers the other."""
    pairs = ((bpy.app.handlers.depsgraph_update_post, handlers._on_depsgraph_update),
             (bpy.app.handlers.frame_change_post, handlers._on_frame_change),
             (bpy.app.handlers.load_post, handlers._on_load))

    def count(handler_list, fn):
        return sum(1 for handler in handler_list if handler == fn)

    for handler_list, fn in pairs:
        check_equal(count(handler_list, fn), 1, f"{fn.__name__} registered once")

    handlers.unregister()
    try:
        for handler_list, fn in pairs:
            check_equal(count(handler_list, fn), 0, f"{fn.__name__} fully removed")
    finally:
        handlers.register()


# ----------------------------------------------------------------------------
# is_visible and UI wiring


@test
def test_is_visible_matches_the_written_flags():
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True

    for values in ((0, 0), (1, 0), (1, 1), (2, 1), (2, 2), (3, 0)):
        set_levels(parent, *values)
        for obj in nester.iter_subtree(parent):
            if obj is parent:
                continue
            check_equal(nester.is_visible(parent, obj), viewport_visible(obj),
                        f"is_visible for {obj.name} at levels {values}")


@test
def test_is_visible_ignores_objects_outside_the_tree():
    wipe()
    parent, *_ = spec_hierarchy()
    stranger = new_object("Stranger")
    parent.layer_nester.enabled = True
    set_levels(parent, index_of(parent, "Child 4"), 0)

    check(nester.is_visible(parent, stranger), "an unrelated object is not managed")
    check(viewport_visible(stranger), "and is left alone")


@test
def test_ui_rna_paths_resolve():
    """The panel draws ``layer_nester.path[i].value``, so that path must resolve."""
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, 1, 1)

    for index, value in ((0, 1), (1, 1)):
        path = f"layer_nester.path[{index}].value"
        found = parent.path_resolve(path)
        check_equal(found, value, f"path_resolve({path!r})")

    # The other properties the panel draws have to resolve as well.
    for name in ("enabled", "depth", "computed_depth", "show_parents",
                 "use_viewport", "use_render"):
        parent.path_resolve(f"layer_nester.{name}")

    # And the per level fields the panel labels come from.
    for index in range(2):
        for name in ("value", "child_name", "child_count"):
            parent.path_resolve(f"layer_nester.path[{index}].{name}")


@test
def test_panels_and_operators_registered():
    for name in ("LAYERNESTER_PT_object", "LAYERNESTER_PT_view3d"):
        check(hasattr(bpy.types, name), f"{name} is registered")
    for name in ("rescan", "release", "apply_all", "select_visible"):
        check(hasattr(bpy.ops.layernester, name), f"layernester.{name} is registered")


@test
def test_icons_used_by_the_panels_exist():
    """A misspelt icon draws nothing, so check them against the real enum."""
    import re

    valid = {item.identifier for item in
             bpy.types.UILayout.bl_rna.functions["label"]
             .parameters["icon"].enum_items}
    check(len(valid) > 100, "the icon enum was readable")

    with open(os.path.join(os.path.dirname(__file__), "..", "ui.py"),
              encoding="utf-8") as handle:
        source = handle.read()
    used = set(re.findall(r"icon=['\"]([A-Z0-9_]+)['\"]", source))
    check(used, "the panels use icons")
    for icon in sorted(used):
        check(icon in valid, f"icon {icon!r} does not exist in Blender")


@test
def test_operators_the_panels_draw_exist():
    """Every operator id the panels draw has to resolve."""
    import re

    with open(os.path.join(os.path.dirname(__file__), "..", "ui.py"),
              encoding="utf-8") as handle:
        source = handle.read()

    for bl_idname in set(re.findall(r'operator\(["\']([\w.]+)["\']', source)):
        module, _, name = bl_idname.partition(".")
        ops = getattr(bpy.ops, module)
        check(hasattr(ops, name), f"{bl_idname} is registered")


# ----------------------------------------------------------------------------
# Panel drawing
# ----------------------------------------------------------------------------


class FakeLayout:
    """Stands in for UILayout so the panel code can run without a display.

    It checks the things a real UILayout would reject: unknown properties,
    misspelt keyword arguments and unknown icons.
    """

    _VALID_ICONS = {item.identifier for item in
                    bpy.types.UILayout.bl_rna.functions["label"]
                    .parameters["icon"].enum_items}

    def __init__(self, calls=None):
        self.calls = [] if calls is None else calls
        self.alert = False
        self.scale_y = 1.0
        self.use_property_split = False
        self.use_property_decorate = False

    @classmethod
    def _kwargs(cls, function, skip):
        return {p.identifier for p in
                bpy.types.UILayout.bl_rna.functions[function].parameters
                if p.identifier not in skip}

    def _record(self, name, rna_name=None, **kwargs):
        """Validate against the real RNA signature, then keep the call."""
        valid = self._kwargs(rna_name or name, {"self"})
        for key in kwargs:
            check(key in valid, f"{name}() got an unknown keyword {key!r}")
        icon = kwargs.get("icon")
        if icon is not None:
            check(icon in self._VALID_ICONS, f"{name}() got unknown icon {icon!r}")
        self.calls.append((name, kwargs))
    def row(self, **_kwargs):
        return self

    def column(self, **_kwargs):
        return self

    def box(self):
        return self

    def separator(self, **kwargs):
        self._record("separator", **kwargs)

    def label(self, **kwargs):
        self._record("label", **kwargs)

    def prop(self, data, property, **kwargs):  # noqa: A002
        self._record("prop", **kwargs)
        check(hasattr(data, property),
              f"prop({type(data).__name__}, {property!r}) does not exist")
        self.calls[-1][1]["data"] = data
        self.calls[-1][1]["property"] = property

    def operator(self, idname, **kwargs):  # noqa: A002
        self._record("operator", "operator", **kwargs)
        module, _, name = idname.partition(".")
        check(hasattr(getattr(bpy.ops, module), name),
              f"operator({idname!r}) is not registered")
        self.calls[-1][1]["idname"] = idname


class FakePanel:
    """Just enough of a Panel for its draw() to run without a real one."""

    layout = None


def draw_panel(panel_cls):
    panel = FakePanel()
    panel.layout = FakeLayout()
    panel_cls.draw(panel, bpy.context)
    return panel.layout.calls


def props_drawn(calls):
    return [kwargs for name, kwargs in calls if name == "prop"]


def operators_drawn(calls):
    return [kwargs for name, kwargs in calls if name == "operator"]


@test
def test_object_panel_draws_when_disabled():
    wipe()
    parent, *_ = spec_hierarchy()
    bpy.context.view_layer.objects.active = parent

    calls = draw_panel(bpy.types.LAYERNESTER_PT_object)
    check_equal(len(props_drawn(calls)), 1, "only the enable toggle is drawn")
    check_equal(props_drawn(calls)[0]["data"].enabled, False, "and it is off")
    texts = [kwargs.get("text", "") for name, kwargs in calls if name == "label"]
    check(any("not managed" in text for text in texts),
          "and it says visibility is left alone")


@test
def test_object_panel_draws_the_sliders():
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, *levels_for(parent, "Child 1"))
    bpy.context.view_layer.objects.active = parent

    calls = draw_panel(bpy.types.LAYERNESTER_PT_object)
    values = [kwargs for kwargs in props_drawn(calls)
              if kwargs.get("property") == "value"]
    check_equal(len(values), parent.layer_nester.depth, "one slider per level")
    check_equal(values[0]["data"], parent.layer_nester.path[0], "level 1 is the first")
    check_equal(values[1]["data"], parent.layer_nester.path[1], "level 2 is the second")
    check_equal(values[0]["text"], "1. Child Group 1", "level 1 is labelled by name")
    check_equal(values[1]["text"], "2. Child 1", "level 2 is labelled by name")

    drawn = {kwargs["property"] for kwargs in props_drawn(calls)}
    for name in ("enabled", "show_parents", "use_viewport", "use_render"):
        check(name in drawn, f"{name} is drawn")

    ids = {kwargs["idname"] for kwargs in operators_drawn(calls)}
    check_equal(ids, {"layernester.release", "layernester.rescan"},
                "Show All and Rescan are offered")


@test
def test_panel_labels_a_zero_level_as_the_whole_branch():
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, *levels_for(parent, "Child Group 1")[:1], 0)
    bpy.context.view_layer.objects.active = parent

    calls = draw_panel(bpy.types.LAYERNESTER_PT_object)
    texts = [kwargs["text"] for kwargs in props_drawn(calls)
             if kwargs.get("property") == "value"]
    check_equal(texts, ["1. Child Group 1", "2. all 1"],
                "a level at zero says how many it covers")


@test
def test_panel_warns_when_the_sliders_do_not_fit():
    wipe()
    parent, group1, child1, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    parent.layer_nester.computed_depth = 5  # pretend the handler has not caught up
    bpy.context.view_layer.objects.active = parent

    calls = draw_panel(bpy.types.LAYERNESTER_PT_object)
    warnings = [kwargs for name, kwargs in calls
                if name == "label" and kwargs.get("alert", False) is not None
                and "deep" in kwargs.get("text", "")]
    check(warnings, "the mismatch is called out")
    check("5 deep" in warnings[0]["text"], "with the detected depth")
    check("2 sliders" in warnings[0]["text"], "and the slider count")


@test
def test_view3d_panel_draws():
    wipe()
    parent, *_ = spec_hierarchy()
    parent.layer_nester.enabled = True
    set_levels(parent, *levels_for(parent, "Child 1"))
    bpy.context.view_layer.objects.active = parent

    calls = draw_panel(bpy.types.LAYERNESTER_PT_view3d)
    ids = {kwargs["idname"] for kwargs in operators_drawn(calls)}
    check({"layernester.select_visible", "layernester.apply_all"} <= ids,
          "the sidebar offers Select Visible and Apply All")

    values = [kwargs for kwargs in props_drawn(calls)
              if kwargs.get("property") == "value"]
    check_equal(len(values), 2, "the sidebar draws the sliders too")


@test
def test_panels_handle_a_childless_object():
    wipe()
    lonely = new_object("Lonely")
    lonely.layer_nester.enabled = True
    bpy.context.view_layer.objects.active = lonely

    for panel in (bpy.types.LAYERNESTER_PT_object, bpy.types.LAYERNESTER_PT_view3d):
        calls = draw_panel(panel)
        texts = [kwargs.get("text", "") for name, kwargs in calls if name == "label"]
        check(any("no children" in text for text in texts),
              f"{panel.bl_idname} says there is nothing to nest")


@test
def test_panels_handle_a_nester_with_no_levels_yet():
    wipe()
    parent = new_object("Parent")
    new_object("Child", parent)
    bpy.context.view_layer.objects.active = parent

    # Enabled by hand so the enable callback does not size the sliders.
    parent.layer_nester.enabled = True
    parent.layer_nester.depth = 0
    for _ in range(len(parent.layer_nester.path)):
        parent.layer_nester.path.remove(0)
    check_equal(parent.layer_nester.depth, 0, "no levels stored")

    for panel in (bpy.types.LAYERNESTER_PT_object, bpy.types.LAYERNESTER_PT_view3d):
        calls = draw_panel(panel)
        texts = [kwargs.get("text", "") for name, kwargs in calls if name == "label"]
        check(any("No levels yet" in text for text in texts),
              f"{panel.bl_idname} offers a rescan instead of empty sliders")


# ----------------------------------------------------------------------------
# Run


def run():
    LayerNester.register()
    try:
        for fn in TESTS:
            wipe()
            try:
                fn()
            except Exception:
                FAILURES.append((fn.__name__, traceback.format_exc()))
                print(f"FAIL  {fn.__name__}")
            else:
                print(f"ok    {fn.__name__}")
    finally:
        wipe()
        LayerNester.unregister()

    print("")
    if FAILURES:
        for name, tb in FAILURES:
            print(f"=== {name} ===")
            print(tb)
        print(f"{len(FAILURES)} of {len(TESTS)} tests failed")
    else:
        print(f"all {len(TESTS)} tests passed")


if __name__ == "__main__":
    run()
    sys.exit(1 if FAILURES else 0)
