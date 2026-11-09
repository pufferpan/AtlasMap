"""Import a dfmap glTF export into Blender and set the scene up for it.

Usage (Blender 4.x):
    blender --python blender_import_dfmap.py -- "G:/AAAAAmanp研究/out/AZ-5/scene.glb"

Or from Blender's Scripting workspace: edit GLB_PATH below and press Run Script.

What it does beyond File > Import:
  * sets the scene unit system to metric / metres and a sane clip range (the maps are
    hundreds of metres across, so the default 100 m clip end hides them)
  * reports what actually landed in the scene so an incomplete export is obvious
    (dfmap cannot decode every mesh - see the tool README section 6.1)
  * leaves everything selected on a single collection named after the map
"""
import os
import sys

import bpy

# In GUI mode nothing a --python script prints reaches a console, so every run also appends its
# report to <glb folder>/blender_import.log. That is what makes a GUI import verifiable.
_LOG = []
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender_import.log")


def say(line=""):
    print(line)
    _LOG.append(str(line))

DEFAULT = "G:/AAAAAmanp研究/out/AZ-5/scene.glb"
GLB_PATH = DEFAULT
if "--" in sys.argv:
    rest = sys.argv[sys.argv.index("--") + 1:]
    if rest:
        GLB_PATH = rest[0]
elif len(bpy.data.filepath) == 0 and os.path.exists(DEFAULT):
    GLB_PATH = DEFAULT

if not os.path.exists(GLB_PATH):
    raise SystemExit(f"GLB not found: {GLB_PATH}")

map_name = os.path.splitext(os.path.basename(os.path.dirname(GLB_PATH)))[0] or "dfmap"

before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=GLB_PATH)
imported = [o for o in bpy.data.objects if o not in before]

meshes = [o for o in imported if o.type == "MESH"]
verts = sum(len(o.data.vertices) for o in meshes)
for o in meshes:
    o.data.calc_loop_triangles()
tris = sum(len(o.data.loop_triangles) for o in meshes)

say("=" * 70)
say(f"dfmap import: {GLB_PATH}")
say(f"  objects      : {len(imported)}  ({len(meshes)} meshes)")
say(f"  vertices     : {verts:,}")
say(f"  triangles    : {tris:,}")

if meshes:
    xs, ys, zs = [], [], []
    for o in meshes:
        for v in o.data.vertices:
            w = o.matrix_world @ v.co
            xs.append(w.x); ys.append(w.y); zs.append(w.z)
    say(f"  bounds (m)   : X {min(xs):.1f}..{max(xs):.1f}  "
          f"Y {min(ys):.1f}..{max(ys):.1f}  Z {min(zs):.1f}..{max(zs):.1f}")
    say(f"  scene size   : {max(xs)-min(xs):.0f} x {max(ys)-min(ys):.0f} x {max(zs)-min(zs):.0f} m")
    centre = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
    radius = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) / 2
    # report texture wiring, so a grey model is obviously a texture problem and not a lighting one
    textured = sum(1 for o in meshes
                   if o.data.materials and any(
                       m and m.use_nodes and any(
                           n.type == "TEX_IMAGE" and n.image for n in m.node_tree.nodes)
                       for m in o.data.materials))
    images = len([i for i in bpy.data.images if i.source == "FILE" and i.filepath])
    say(f"  meshes with an image texture: {textured}/{len(meshes)}   images loaded: {images}")
    # Blender leaves file images unloaded until something reads their pixels, so has_data is
    # False right after import even when everything resolved. Force a read, then report the
    # ones that genuinely are not there.
    missing = []
    for img in bpy.data.images:
        if img.source != "FILE" or not img.filepath:
            continue
        path = bpy.path.abspath(img.filepath)
        if not os.path.exists(path):
            missing.append(path)
            continue
        try:
            _ = img.pixels[0]
        except Exception:
            missing.append(path)
    if missing:
        say(f"  !! {len(missing)} image(s) could not be read - is textures/ next to the .glb?")
        for m in missing[:5]:
            say(f"     {m}")
    else:
        say(f"  all {images} referenced images resolved and loaded")
else:
    centre, radius = (0.0, 0.0, 0.0), 100.0

# units / clipping: these maps are big, the defaults hide them
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1.0
# Viewport cosmetics only make sense with a GUI: touching screen areas in --background mode
# crashes Blender natively (no windows exist), so this whole block is skipped there.
if not bpy.app.background:
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type != "VIEW_3D":
                    continue
                try:
                    space.clip_end = 100000.0
                    space.clip_start = 0.05
                    # Solid + Texture shows the albedo with no lighting set up at all, which is
                    # the fastest way to tell a missing mesh from a dark one. The maps sit far
                    # from the origin (the SafeHouse hub is ~200 m below it), so point at them.
                    space.shading.type = "SOLID"
                    space.shading.color_type = "TEXTURE"
                    space.shading.show_backface_culling = False
                    rv = space.region_3d
                    if rv is not None:
                        rv.view_location = centre
                        rv.view_distance = radius * 2.2
                        rv.view_rotation = (0.7071, 0.3536, 0.3536, 0.6124)   # down from front-right
                        rv.update()
                except Exception as exc:                   # cosmetics must never break the import
                    say(f"  (viewport setup skipped: {exc})")

coll = bpy.data.collections.new(map_name)
scene.collection.children.link(coll)
for o in imported:
    for c in list(o.users_collection):
        c.objects.unlink(o)
    coll.objects.link(o)

say(f"  collection   : {map_name}")
say(f"  view framed on: {tuple(round(c, 1) for c in centre)}  (radius {radius:.0f} m)")
say("=" * 70)
say("Viewport is in Solid+Texture mode. Press Z > Rendered to see the exported lights,")
say("but note most of them are 10 m ranges, so the hub interior is where they show up.")
say("If very few meshes appear, the export was geometry-incomplete "
    "(meshes whose LOD lives in .ubulk could not be decoded).")

if LOG_PATH:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"\n===== {__import__('datetime').datetime.now():%Y-%m-%d %H:%M:%S} "
                     f"blender {bpy.app.version_string} "
                     f"{'background' if bpy.app.background else 'gui'} =====\n")
            fh.write("\n".join(_LOG) + "\n")
    except Exception as exc:
        say(f"could not write {LOG_PATH}: {exc}")
