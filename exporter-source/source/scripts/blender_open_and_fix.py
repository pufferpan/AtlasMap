"""Open a dfmap export in Blender and immediately repair the view.

One Blender session, two steps, in this order:
  1. blender_import_split.py  - import the per-level files, each into its own collection, and
                                move every object's origin onto its own geometry
  2. blender_fix_view.py      - set the viewport and camera clip range for a scene measured in
                                kilometres, and re-frame on what actually loaded

The clip step has to run after the import: Blender's 3D viewport defaults to a 1000 m clip end,
and AZ-5 spans 65 km, so without it the scene looks like most of it never arrived.

Blender can take --python more than once, but the import script claims everything after "--" as
its own arguments, so the two are chained here instead.

Usage:
    blender --python blender_open_and_fix.py -- <split dir>
"""
import os
import runpy
import sys

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
split_dir = args[0] if args else r"G:/AAAAAmanp研究/out/AZ-5_full/preview"
here = os.path.dirname(os.path.abspath(__file__))

if not os.path.isdir(split_dir):
    raise SystemExit(f"split dir not found: {split_dir}")

print("=" * 78)
print(f"step 1/2  importing {split_dir}")
print("=" * 78)
sys.argv = [os.path.join(here, "blender_import_split.py"), "--", split_dir]
runpy.run_path(os.path.join(here, "blender_import_split.py"), run_name="__main__")

print()
print("=" * 78)
print("step 2/2  repairing the view (clip range, framing, camera)")
print("=" * 78)
sys.argv = [os.path.join(here, "blender_fix_view.py")]
runpy.run_path(os.path.join(here, "blender_fix_view.py"), run_name="__main__")

print()
print("Done. Every level is its own collection under 'split'; toggle them in the Outliner.")
