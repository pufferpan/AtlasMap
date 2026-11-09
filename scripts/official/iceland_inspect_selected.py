import bpy
import json
from pathlib import Path

name = "DeltaForce/Content/Environment/Biome/Nature/Rocks/IceLand/SM_IceLand_Nature_Rock_Huge_MassifCliff_06.SM_IceLand_Nature_Rock_Huge_MassifCliff_06.005"
obj = bpy.data.objects.get(name)
report = {"found": obj is not None}
if obj:
    report.update(name=obj.name, asset=obj.data.get("unrealAssetPath"), level=obj.get("source_level"),
                  matrix=[list(row) for row in obj.matrix_world],
                  local_bounds=[list(v) for v in obj.bound_box])
Path("D:/AtlasMap-tooling/out/Iceland/audit/MassifCliff_06_005_before.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(report)
