# SPDX-License-Identifier: GPL-2.0-or-later
"""Install path checks for LayerNester.

Installs the add-on the way a user would, through ``addon_utils`` and
``bl_info``, then saves and reloads a file to prove the state survives.

Run with::

    blender -b --factory-startup --python tests/test_install.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback

import bpy
import addon_utils

ADDON_NAME = "LayerNester"
ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FAILURES = []


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def check_equal(got, want, message):
    if got != want:
        raise AssertionError(f"{message}: got {got!r}, want {want!r}")


def check_bl_info(info):
    for key in ("name", "author", "version", "blender", "location",
                "description", "category"):
        check(key in info, f"bl_info is missing {key!r}")
    check_equal(tuple(info["version"]), (1, 0, 0), "bl_info version")
    check(info["blender"] <= bpy.app.version,
          f"bl_info claims it needs Blender {info['blender']}, running {bpy.app.version}")


def install():
    """Copy the add-on into a scripts/addons directory Blender scans."""
    targets = [os.path.join(bpy.utils.user_resource("SCRIPTS"), "addons")]
    targets.extend(os.path.join(path, "addons") for path in addon_utils.paths())

    installed = []
    for directory in targets:
        target = os.path.join(directory, ADDON_NAME)
        try:
            # Always refresh, so a run that died before cleaning up cannot
            # leave stale code behind.
            shutil.rmtree(target, ignore_errors=True)
            os.makedirs(target)
            for name in os.listdir(ADDON_DIR):
                source = os.path.join(ADDON_DIR, name)
                if os.path.isfile(source) and name.endswith((".py", ".toml")):
                    shutil.copy2(source, target)
            installed.append(target)
        except OSError as ex:
            print(f"skipping {directory}: {ex}")

    check(installed, f"could not install into any of {targets}")
    addon_utils.modules_refresh()
    return installed


def uninstall(installed):
    for target in installed:
        shutil.rmtree(target, ignore_errors=True)
    addon_utils.modules_refresh()


def test_bl_info_is_valid():
    modules = {module.__name__: module for module in addon_utils.modules()}
    check(ADDON_NAME in modules, f"the add-on was found, got {sorted(modules)[:5]}...")
    check_bl_info(dict(addon_utils.module_bl_info(modules[ADDON_NAME])))


def test_addon_enables_and_disables():
    default_set = addon_utils.check(ADDON_NAME)
    check_equal(default_set[1], False, "the add-on starts disabled")

    # Not persistent, so running the tests does not touch the user preferences.
    addon_utils.enable(ADDON_NAME, default_set=default_set, persistent=False)
    check(addon_utils.check(ADDON_NAME)[1], "the add-on is enabled")
    check(hasattr(bpy.types.Object, "layer_nester"),
          "the object property exists while enabled")
    check(hasattr(bpy.types, "LAYERNESTER_PT_object"), "the panel is registered")

    addon_utils.disable(ADDON_NAME, default_set=addon_utils.check(ADDON_NAME))
    check(not hasattr(bpy.types.Object, "layer_nester"),
          "the object property is gone while disabled")

    # Registering twice in a row must not leave a stale handler behind.
    before = len(bpy.app.handlers.depsgraph_update_post)
    addon_utils.enable(ADDON_NAME, default_set=addon_utils.check(ADDON_NAME))
    check_equal(len(bpy.app.handlers.depsgraph_update_post), before + 1,
                "one handler was added")
    addon_utils.disable(ADDON_NAME, default_set=addon_utils.check(ADDON_NAME))
    check_equal(len(bpy.app.handlers.depsgraph_update_post), before,
                "and removed again")


def test_enabling_addon_adopts_existing_nesters():
    """Enabling the add-on on a file that already uses it must keep working."""
    addon_utils.enable(ADDON_NAME, default_set=addon_utils.check(ADDON_NAME))
    try:
        parent = bpy.data.objects.new("Parent", None)
        bpy.context.scene.collection.objects.link(parent)
        group = bpy.data.objects.new("Group", None)
        bpy.context.scene.collection.objects.link(group)
        group.parent = parent
        leaf = bpy.data.objects.new("Leaf", None)
        bpy.context.scene.collection.objects.link(leaf)
        leaf.parent = group
        other = bpy.data.objects.new("Other", None)
        bpy.context.scene.collection.objects.link(other)
        other.parent = parent

        from LayerNester import nester
        parent.layer_nester.enabled = True
        parent.layer_nester.path[0].value = [
            child.name for child in parent.children].index("Group") + 1
        parent.layer_nester.path[1].value = 1
        check(other.hide_viewport, "the other child is hidden")

        # Drop the add-on and put it back, the way a preferences toggle does.
        addon_utils.disable(ADDON_NAME, default_set=addon_utils.check(ADDON_NAME))
        addon_utils.enable(ADDON_NAME, default_set=addon_utils.check(ADDON_NAME))

        check_equal(parent.layer_nester.depth, 2, "the slider count is still there")
        check_equal([level.value for level in parent.layer_nester.path], [1, 1],
                    "the slider values survived the toggle")

        # The handler sweeps the file on its first update after registering.
        bpy.context.view_layer.update()
        bpy.context.evaluated_depsgraph_get().update()
        check_equal([obj.name for obj in nester.nester_roots()], ["Parent"],
                    "the existing nester was adopted")
        check(other.hide_viewport, "and still hides the other child")
    finally:
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)


def test_survives_a_save_and_load():
    addon_utils.enable(ADDON_NAME, default_set=addon_utils.check(ADDON_NAME))

    def build():
        parent = bpy.data.objects.new("Parent", None)
        bpy.context.scene.collection.objects.link(parent)
        group = bpy.data.objects.new("Group", None)
        bpy.context.scene.collection.objects.link(group)
        group.parent = parent
        leaf = bpy.data.objects.new("Leaf", None)
        bpy.context.scene.collection.objects.link(leaf)
        leaf.parent = group
        other = bpy.data.objects.new("Other", None)
        bpy.context.scene.collection.objects.link(other)
        other.parent = parent
        return parent, leaf, other

    parent, leaf, other = build()
    parent.layer_nester.enabled = True
    group_value = [child.name for child in parent.children].index("Group") + 1
    parent.layer_nester.path[0].value = group_value
    parent.layer_nester.path[1].value = 1
    check(leaf.hide_viewport is False, "the chosen leaf shows")
    check(other.hide_viewport is True, "the other child is hidden")

    handle, path = tempfile.mkstemp(suffix=".blend")
    os.close(handle)
    try:
        bpy.ops.wm.save_as_mainfile(filepath=path)

        # Wipe the scene, then reload it, the add-on handlers must pick the
        # nester back up from the saved file.
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.ops.wm.open_mainfile(filepath=path)
    finally:
        os.unlink(path)

    parent = bpy.data.objects["Parent"]
    leaf = bpy.data.objects["Leaf"]
    other = bpy.data.objects["Other"]
    check(parent.layer_nester.enabled, "the nester is still enabled")
    check_equal(parent.layer_nester.depth, 2, "the slider count survived")
    check_equal([level.value for level in parent.layer_nester.path], [group_value, 1],
                "the slider values survived")
    check(leaf.hide_viewport is False, "the chosen leaf still shows")
    check(other.hide_viewport is True, "the other child is still hidden")

    addon_utils.disable(ADDON_NAME, default_set=addon_utils.check(ADDON_NAME))


def test_manifest_is_present_and_plausible():
    path = os.path.join(ADDON_DIR, "blender_manifest.toml")
    check(os.path.isfile(path), "blender_manifest.toml exists")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    for key in ('schema_version = "1.0.0"', 'id = "layernester"',
                'type = "add-on"', "version = ", "blender_version_min = ",
                "license = ", "tagline = ", "maintainer = "):
        check(key in text, f"the manifest is missing {key}")


def run():
    installed = install()
    try:
        for fn in (test_bl_info_is_valid,
                   test_addon_enables_and_disables,
                   test_enabling_addon_adopts_existing_nesters,
                   test_survives_a_save_and_load,
                   test_manifest_is_present_and_plausible):
            try:
                fn()
            except Exception:
                FAILURES.append((fn.__name__, traceback.format_exc()))
                print(f"FAIL  {fn.__name__}")
            else:
                print(f"ok    {fn.__name__}")
    finally:
        uninstall(installed)

    print("")
    if FAILURES:
        for name, tb in FAILURES:
            print(f"=== {name} ===")
            print(tb)
        print(f"{len(FAILURES)} checks failed")
    else:
        print("install checks passed")


if __name__ == "__main__":
    run()
    sys.exit(1 if FAILURES else 0)
