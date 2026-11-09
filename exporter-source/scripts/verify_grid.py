"""Independently verify the dfmap block-tiling formula against a `dfmap scan` inventory.

Formula under test (decoded from 207 observed LevelBounds cells):

    世界子格边长 CELL = 12600 uu (126 m)
    子格中心 = ((i + 0.5) * CELL, (j + 0.5) * CELL)        # UE cm, Y negative
    名字     {类别}_x{X}_y{Y}_{Z}
        i = 2*X + (1 if Z >= 2 else 0)
        j = -( 2*Y + 1 + (1 if Z % 2 else 0) )

This script re-derives the observed cell index from LevelBounds and compares.
Exit code 0 only when every grid-named level with bounds matches.
"""
import json
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CELL = 12600.0
GRID = re.compile(
    r"^(?:Gameplay|Interactor|Loot|QA|DynamicMesh)_x(\d+)_y(\d+)_(\d+)(?:_HD)?$", re.I)

src = sys.argv[1] if len(sys.argv) > 1 else r"G:\AAAAAmanp研究\_tool\out_az5_scan.json"
rows = json.load(open(src, encoding="utf-8"))
print(f"inventory: {src}")
print(f"{len(rows)} level records\n")


def cell_of(center):
    return round(center[0] / CELL - 0.5), round(center[1] / CELL - 0.5)


match = mismatch = skipped = 0
bad = []
for r in rows:
    name = r["Level"].rsplit("/", 1)[-1].removesuffix(".umap")
    m = GRID.match(name)
    center = r.get("BoundsCenter")
    if not (m and center):
        skipped += 1
        continue
    x, y, z = (int(m.group(i)) for i in (1, 2, 3))
    predicted = (2 * x + (1 if z >= 2 else 0),
                 -(2 * y + 1 + (1 if z % 2 else 0)))
    observed = cell_of(center)
    if predicted == observed:
        match += 1
    else:
        mismatch += 1
        bad.append((name, predicted, observed, center))

print(f"grid-named levels with LevelBounds : {match + mismatch}")
print(f"  formula MATCH                    : {match}")
print(f"  MISMATCH                         : {mismatch}")
print(f"(levels without a grid name or without LevelBounds: {skipped})")

for name, p, o, c in bad[:20]:
    print(f"  MISMATCH {name}: predicted {p} observed {o} center {c}")

# show the mapping table for the record
seen = {}
for r in rows:
    name = r["Level"].rsplit("/", 1)[-1].removesuffix(".umap")
    m = GRID.match(name)
    if not (m and r.get("BoundsCenter")):
        continue
    key = (int(m.group(1)), int(m.group(2)))
    seen.setdefault(key, set()).add(cell_of(r["BoundsCenter"]))
print("\nname(X,Y) -> observed world cells:")
for k in sorted(seen)[:16]:
    print(f"  ({k[0]:>2},{k[1]:>2}) -> {sorted(seen[k])}")

print("\nVERDICT: " + ("FORMULA CONFIRMED" if mismatch == 0 else f"{mismatch} MISMATCHES"))
sys.exit(0 if mismatch == 0 else 1)
