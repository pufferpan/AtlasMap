"""Import every dfmap export into one Blender session, each in its own collection.

Usage:
    blender --python blender_import_all.py -- <folder> [<folder> ...]

Each folder must contain a scene.glb. Collections are named after the folder, so the Outliner
can isolate one map at a time. The viewport is framed on whichever map has the most geometry.

A map folder often sits a long way from the world origin (Forrest_Tutorial is ~6 km out), so
framing the union of all of them would zoom out to nothing useful; that is why the framing
target is chosen rather than computed over everything.
"""
import os
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not args:
    root = r"G:/AAAAAmanp研究/out"
    args = [os.path.join(root, d) for d in os.listdir(root)
            if os.path.exists(os.path.join(root, d, "scene.glb"))]

LOG = []
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender_import_all.log")


def say(line=""):
    print(line)
    LOG.append(str(line))


scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0

if not bpy.app.background:
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    try:
                        space.clip_end = 1000000.0
                        space.clip_start = 0.05
                        space.shading.type = "SOLID"
                        space.shading.color_type = "TEXTURE"
                        space.shading.show_backface_culling = False
                    except Exception as exc:
                        say(f"  (viewport setup skipped: {exc})")

summaries = []
for folder in args:
    glb = os.path.join(folder, "scene.glb")
    if not os.path.exists(glb):
        say(f"skip (no scene.glb): {folder}")
        continue
    name = os.path.basename(os.path.normpath(folder))

    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb)
    imported = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in imported if o.type == "MESH"]

    verts = tris = 0
    lo = [1e30] * 3
    hi = [-1e30] * 3
    for o in meshes:
        me = o.data
        verts += len(me.vertices)
        me.calc_loop_triangles()
        tris += len(me.loop_triangles)
        for v in me.vertices:
            w = o.matrix_world @ v.co
            for k in range(3):
                lo[k] = min(lo[k], w[k])
                hi[k] = max(hi[k], w[k])

    coll = bpy.data.collections.new(name)
    scene.collection.children.link(coll)
    for o in imported:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)

    textured = sum(1 for o in meshes
                   if o.data.materials and any(
                       m and m.use_nodes and any(n.type == "TEX_IMAGE" and n.image
                                                 for n in m.node_tree.nodes)
                       for m in o.data.materials))
    centre = [(lo[k] + hi[k]) / 2 for k in range(3)]
    radius = max(hi[k] - lo[k] for k in range(3)) / 2 if meshes else 100.0
    summaries.append({"name": name, "objects": len(imported), "meshes": len(meshes),
                      "verts": verts, "tris": tris, "textured": textured,
                      "centre": centre, "radius": radius, "coll": coll})

say("=" * 74)
say(f"dfmap: imported {len(summaries)} maps")
say(f'{"map":<20} {"objects":>8} {"meshes":>8} {"verts":>12} {"tris":>12} {"textured":>10}   centre (m)')
for s in summaries:
    c = ",".join(f"{v:.0f}" for v in s["centre"])
    say(f'{s["name"]:<20} {s["objects"]:>8} {s["meshes"]:>8} {s["verts"]:>12,} '
        f'{s["tris"]:>12,} {s["textured"]:>10}   ({c})')

images = [i for i in bpy.data.images if i.source == "FILE" and i.filepath]
missing = []
for img in images:
    try:
        _ = img.pixels[0]
    except Exception:
        missing.append(bpy.path.abspath(img.filepath))
say(f"images referenced: {len(images)}   unreadable: {len(missing)}")
for m in missing[:5]:
    say(f"   !! {m}")

# frame the biggest map; the others are one Outliner click away
if summaries and not bpy.app.background:
    target = max(summaries, key=lambda s: s["verts"])
    say(f'framed on: {target["name"]}')
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type != "VIEW_3D":
                    continue
                rv = space.region_3d
                if rv is not None:
                    rv.view_location = target["centre"]
                    rv.view_distance = max(target["radius"] * 2.2, 5.0)
                    rv.view_rotation = (0.7071, 0.3536, 0.3536, 0.6124)
                    rv.update()
say("=" * 74)
say("Each map is its own collection - use the Outliner to isolate one.")

try:
    with open(LOG_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(LOG) + "\n")
except Exception as exc:
    print(f"could not write {LOG_PATH}: {exc}")
