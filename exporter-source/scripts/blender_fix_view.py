"""Repair a dfmap import in an open Blender session: bring back "disappeared" geometry.

Run this from Blender's Scripting tab (or `blender --python blender_fix_view.py`) while the
imported scene is open. It changes nothing about the data - it fixes the three view-side reasons
dfmap geometry looks like it vanished:

1. CLIPPING. Blender's 3D viewport defaults to clip_start 0.1 / clip_end 1000 metres. AZ-5 spans
   65,440 x 65,600 m, so with default values everything past the first kilometre is simply not
   drawn - which reads as "some objects and the ground disappeared". The same value exists per
   viewport and per workspace, and a newly opened viewport goes back to the default, which is why
   it can look fine one minute and empty the next.

2. FRAMING. After a world-space bake the object origins sit at (0,0,0) while the geometry can be
   kilometres away, so Orbit/Frame Selected does nothing useful. This sets the view to the real
   bounds of what is visible.

3. RENDER CLIP. The camera's own clip_end is separate from the viewport's and defaults to 1000 m
   too, so a render comes out empty even when the viewport looks right.

umodel_tools sidesteps 2 by placing each instance as its own object with a real matrix_world
(see map_importer.py: new_obj.matrix_world = parent_mtx @ trs.matrix_4x4) instead of baking world
coordinates into the mesh. That is the structural fix; this script is the quick one.
"""
import sys

import bpy

CLIP_START = 0.05
CLIP_END = 10_000_000.0        # 10,000 km - larger than any dfmap scene, still finite

# In GUI mode nothing a --python script prints reaches a console, so every run also appends its
# report to a log next to this file. That is what makes the repair verifiable.
_LOG = []


def say(line=""):
    print(line)
    _LOG.append(str(line))


def visible_bounds():
    lo = [1e30] * 3
    hi = [-1e30] * 3
    found = False
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH' or not obj.visible_get():
            continue
        mw = obj.matrix_world
        for v in obj.data.vertices:
            w = mw @ v.co
            for k in range(3):
                if w[k] < lo[k]:
                    lo[k] = w[k]
                if w[k] > hi[k]:
                    hi[k] = w[k]
            found = True
    return (lo, hi) if found else (None, None)


def main():
    scene = bpy.context.scene
    touched = 0

    # 1 + 2: every viewport, in every workspace, not just the one that happens to be open
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for space in area.spaces:
                if space.type != 'VIEW_3D':
                    continue
                space.clip_start = CLIP_START
                space.clip_end = CLIP_END
                if hasattr(space, 'shading'):
                    space.shading.show_backface_culling = False
                touched += 1

                rv = space.region_3d
                if rv is None:
                    continue
                lo, hi = visible_bounds()
                if lo is None:
                    continue
                rv.view_location = [(lo[k] + hi[k]) / 2 for k in range(3)]
                span = max(hi[k] - lo[k] for k in range(3))
                rv.view_distance = max(span * 1.4, 10.0)
                rv.update()

    # 3: the camera clip, used by renders and by "Camera Persp" view
    for cam in [o for o in scene.objects if o.type == 'CAMERA']:
        cam.data.clip_start = CLIP_START
        cam.data.clip_end = CLIP_END

    lo, hi = visible_bounds()
    say(f'viewports updated : {touched}')
    say(f'clip              : {CLIP_START} .. {CLIP_END:,.0f} m')
    if lo is not None:
        say(f'visible bounds (m): X {lo[0]:.1f}..{hi[0]:.1f}  Y {lo[1]:.1f}..{hi[1]:.1f}  '
            f'Z {lo[2]:.1f}..{hi[2]:.1f}')
        say(f'visible size  (m) : {hi[0]-lo[0]:.0f} x {hi[1]-lo[1]:.0f} x {hi[2]-lo[2]:.0f}')
        if max(hi[k] - lo[k] for k in range(3)) > 2000:
            say('This spans kilometres, so the default 1000 m clip end was hiding almost all of')
            say('it. Press Home (or Numpad .) in the viewport to re-frame on everything.')
        else:
            say('This fits inside a kilometre, so clipping was not what was hiding it.')
    else:
        say('no visible mesh objects found - check the Outliner collection toggles')

    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'blender_fix_view.log')
    try:
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(_LOG) + '\n')
    except Exception as exc:
        print(f'could not write {path}: {exc}')
    return _LOG


main()
