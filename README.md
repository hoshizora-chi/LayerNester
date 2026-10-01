# LayerNester

DISCLAIMER: THIS IS A PROTOTYPE-IN-PRODUCTION MADE BY OPENCODE BIG PICKLE. USE AT YOUR OWN RISK

A Blender 5.2 add-on that takes over the visibility of a nested hierarchy so
that only one branch is shown at a time. See [SPECS.md](SPECS.md).

## Install

The repository root is the add-on package.

* **As an extension**: copy or symlink this directory to
  `~/.config/blender/5.2/extensions/user_default/layernester`, then enable
  *LayerNester* in Preferences → Get Extensions.
* **As a legacy add-on**: copy this directory to
  `~/.config/blender/5.2/scripts/addons/LayerNester`, then enable it in
  Preferences → Add-ons. (Editing → Preferences → Add-ons → Install from Disk
  also works on a zip of this directory.)

Either way the panels show up in:

* Properties → Object → **LayerNester**
* 3D View → Sidebar (<kbd>N</kbd>) → **LayerNester**

## How it works

Tick **Layer Nester** on any object that has children. The add-on then shows
one integer slider per level of nesting, and everything that is not in the
selected branch is hidden in both the viewport and renders.

The slider count is the **deepest nest in the subtree**, not the depth of the
particular branch you happen to be on, so the row of sliders does not change
shape as you move them. For the tree in SPECS.md that is two sliders.

### Reading a slider

The values are consumed in order as a path down the hierarchy:

| Value | Meaning |
| --- | --- |
| `0` | Stop here. Show the object reached and its whole subtree. |
| `n` | Descend into the `n`-th child, and use the next slider. |

If the sliders run out while you are still descending, whatever you landed on
is shown in full. So all zeros means "show everything", which makes `0` a
convenient reset.

With the SPECS.md tree, `Parent` has the children `Child 4`,
`Child Group 1`, `Child Group 2` in outliner order, so:

| Sliders | Visible |
| --- | --- |
| `2, 1` | only `Child 1` |
| `3, 2` | only `Child 3` |
| `1, 0` | only `Child 4` |
| `2, 0` | `Child Group 1` and `Child 1` |
| `3, 0` | `Child Group 2`, `Child 2` and `Child 3` |
| `0, 0` | everything |

Note the numbers are *positions in the outliner*, not positions in the
SPECS.md listing. `Object.children` is the only ordering Blender exposes, and
in 5.x it is sorted, so the first child is the one the outliner lists first.
Each slider is labelled with the child it currently points at, so you never
have to guess.

### Options

| Option | Default | Effect |
| --- | --- | --- |
| **Show Parents** | off | Also keep the group objects on the path to the selected object visible. |
| **Viewport** | on | Manage `hide_viewport` on the children. |
| **Render** | on | Manage `hide_render` on the children. |

The object the nester is switched on is never hidden itself, and switching the
nester off unhides everything underneath it again.

### Operators

All operators act on the enabled nesters among the selected objects, or on
the active object.

| Operator | Purpose |
| --- | --- |
| **Show All** | Set every slider to `0`, showing the whole hierarchy. |
| **Rescan Nest Depth** | Match the slider count to the nesting that is actually there, shrinking as well as growing it. |
| **Select Visible** | Select what the current sliders leave visible. |
| **Apply All** | Re-apply every enabled nester in the file. |

### Keeping the slider count stable

SPECS.md asks for a count that does not move around on its own, so the count
only ever **grows**: when children are added deeper in the tree the add-on
picks up the extra sliders itself, but it never takes any away. **Rescan Nest
Depth** is the explicit way to shrink it back down. Until you rescan, the
panel shows a warning when the hierarchy is deeper than the slider count.

## Animation and drivers

The sliders can be keyframed or driven, and the visibility follows during
playback. Nothing extra is needed: put a keyframe on a slider, or add a driver
to it, and scrub or play.

This works because Blender treats a driven value differently from an edited one.
An `update` callback — which is how an edit made in the panel is noticed — is
never called for a keyframed or driven value, so watching only for edits would
miss animation completely. LayerNester therefore also listens on Blender's two
change handlers, which between them report every case:

| What changed | What reports it |
| --- | --- |
| Edited by hand in the panel or from a script | the property's `update` callback |
| Keyframes, or a driver on the frame number | `frame_change_post` |
| A driver fed from another object's property | `depsgraph_update_post` |
| Children added, removed or re-parented | `depsgraph_update_post` |
| File loaded | `load_post` |

Both handlers also look for a nester that was switched **on** by animation or a
driver, since that never reaches the callback which normally registers it. That
search walks every object in the file, so it is throttled to at most one walk
every half second; in practice a freshly animated toggle picks up within a frame
or two. Switching a nester **off** by animation hands the branch back just as a
hand edit does.

One caveat worth knowing: on a frame where nothing relevant changed, LayerNester
does nothing at all, rather than re-walking the subtree. On a large tree that
is the difference between a free frame and a visible hitch.

## Nested nesters

A nester can be switched on for a child of another nester. The inner one is
applied last and therefore wins for its own subtree, which is what you want
when a rig has a global nester and per-part nesters underneath it.

## Layout

```
__init__.py     bl_info, registration
nester.py       the resolution rule, depth scanning, visibility writes
properties.py   Object.layer_nester and the per level slider storage
handlers.py     the two change handlers, animation and hierarchy edits
operators.py    Show All, Rescan Nest Depth, Select Visible, Apply All
ui.py           the two panels
tests/          headless tests
```

## Tests

```sh
blender -b --factory-startup --python tests/test_layernester.py
blender -b --factory-startup --python tests/test_install.py
```

`test_layernester.py` covers the rule against the SPECS.md examples, deeper
trees, clamping, the slider count, the options, the operators, nested nesters,
keyframes, drivers and the handlers. `test_install.py` installs the add-on the way a user would,
then saves and reloads a file to check the state survives. The tests write
nothing to your Blender configuration and clean up after themselves.
