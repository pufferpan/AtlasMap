"""Convert a dfmap --split export into one FBX per level, for Unity.

Unity 2018.4 has no built-in glTF support and glTFast needs 2020.3+, so FBX is the route that
works on what is installed. Blender does the conversion; this script only drives it.

Usage:
    blender --python blender_split_to_fbx.py -- <split dir> <out dir> [--limit N]

Notes that matter for the Unity side:
  * Textures are copied next to each FBX (path_mode='COPY'), so Unity's importer can find them.
  * Blender writes FBX in centimetres while dfmap geometry is already in metres, so the export
    turns off unit scaling; if a level arrives 100x off in Unity, set the model's Scale Factor
    to 100 (or 1) - it is a single import setting, not a data problem.
  * Only the geometry and material slots survive a round trip this way. Base colour and normal
    maps are linked by Unity's "Extract Textures" pass; metallic/roughness will need setting by
    hand, because dfmap only recovered 3 of them for this map anyway.
"""
import os
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if len(args) < 2:
    raise SystemExit("usage: blender --python blender_split_to_fbx.py -- <split dir> <out dir> [--limit N]")
split_dir, out_dir = args[0], args[1]
limit = None
if "--limit" in args:
    limit = int(args[args.index("--limit") + 1])

os.makedirs(out_dir, exist_ok=True)
files = sorted(f for f in os.listdir(split_dir) if f.endswith(".glb"))
if limit:
    files = files[:limit]

print(f"converting {len(files)} level(s) -> {out_dir}")
print(f"{'level':<36} {'meshes':>7} {'verts':>12}  fbx")

for f in files:
    glb = os.path.join(split_dir, f)
    stem = os.path.splitext(f)[0]

    # start from an empty file every time, otherwise each level accumulates the previous one
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    verts = sum(len(o.data.vertices) for o in meshes)
    if not meshes:
        print(f"{stem:<36} {'-':>7} {'-':>12}  skipped (no meshes)")
        continue

    fbx = os.path.join(out_dir, stem + ".fbx")
    bpy.ops.export_scene.fbx(
        filepath=fbx,
        use_selection=False,
        apply_unit_scale=False,      # geometry is already in metres
        global_scale=1.0,
        apply_scale_options='FBX_SCALE_NONE',
        path_mode='COPY',            # ship the PNGs alongside
        embed_textures=False,
        mesh_smooth_type='FACE',
        use_mesh_modifiers=False,
        bake_space_transform=False,  # Unity's own axis conversion expects no extra bake
        object_types={'MESH'},
    )
    size = os.path.getsize(fbx) / 1048576.0
    print(f"{stem:<36} {len(meshes):>7} {verts:>12,}  {os.path.basename(fbx)} ({size:.1f} MB)")

print(f"\ndone. Point Unity at {out_dir}: the FBX files are native imports, and the PNGs copied")
print("beside them are picked up by selecting a model and using Extract Textures.")
