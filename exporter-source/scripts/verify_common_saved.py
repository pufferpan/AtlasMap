"""Check the saved scene against native component matrices and render sections."""
import bpy
import hashlib
import json
import struct
from pathlib import Path

import numpy as np

root=Path("D:/AtlasMap-tooling/out/Iceland/revised/common_static_repair")
bundle=json.loads((root/"repair_bundle.json").read_text(encoding="utf-8-sig"))
visibility=json.loads((root.parent.parent/"audit/visibility/visibility_audit.json").read_text(encoding="utf-8-sig"))
excluded={r["asset"] for r in visibility if not r["renderable"]}
raw=(root/"common_additions.glb").read_bytes()
length=struct.unpack_from("<I",raw,12)[0]
document=json.loads(raw[20:20+length])
binary=raw[28+length:]
source_positions={}
for mesh in document["meshes"]:
    index=mesh["primitives"][0]["attributes"]["POSITION"]
    accessor=document["accessors"][index]
    view=document["bufferViews"][accessor["bufferView"]]
    coords=np.frombuffer(binary,"<f4",accessor["count"]*3,view.get("byteOffset",0)+accessor.get("byteOffset",0)).reshape(-1,3)
    coords=coords[:,[0,2,1]].copy()
    coords[:,1]*=-1
    source_positions[mesh["name"]]=coords
bpy.context.view_layer.update()
failures=[]
material_checks=0
for entry in bundle["meshes"]:
    data=bpy.data.meshes.get(entry["data_name"])
    if data is None:
        failures.append({"asset":entry["asset"],"reason":"saved mesh missing"})
        continue
    indices=np.empty(len(data.loops),dtype=np.uint32)
    data.loops.foreach_get("vertex_index",indices)
    if hashlib.sha256(indices.astype("<u4").tobytes()).hexdigest()!=entry["index_sha256"]:
        failures.append({"asset":entry["asset"],"reason":"topology differs"})
        continue
    actual=np.empty(len(data.polygons),dtype=np.int32)
    data.polygons.foreach_get("material_index",actual)
    used=np.array(entry["used_source_slots"])
    expected=np.fromfile(root/entry["face_material_file"],"<u2")
    if np.any(actual>=len(used)) or not np.array_equal(used[actual],expected):
        failures.append({"asset":entry["asset"],"reason":"saved face-material assignments differ"})
        continue
    material_checks+=1
by_node={o.get("common_repair_node"):o for o in bpy.context.scene.objects if o.get("common_repair_node")}
placement_checks=[]
mirror=np.diag([1,-1,1,1])
for entry in bundle["additions"]:
    obj=by_node.get(entry["node_name"])
    if obj is None:
        failures.append({"node":entry["node_name"],"reason":"addition missing"})
        continue
    native=np.array(entry["MatrixUE"])
    native=native.reshape(4,4).T
    native[:3,3]/=100
    expected=mirror@native@mirror
    source=source_positions[entry["asset"]]
    expected_world=source@expected[:3,:3].T+expected[:3,3]
    vertices=np.empty(len(obj.data.vertices)*3,dtype=np.float32)
    obj.data.vertices.foreach_get("co",vertices)
    actual=np.array(obj.matrix_world)
    world=vertices.reshape(-1,3)@actual[:3,:3].T+actual[:3,3]
    error=float(max(np.max(np.abs(world.min(0)-expected_world.min(0))),np.max(np.abs(world.max(0)-expected_world.max(0)))))
    tolerance=max(.005,float(np.max(np.abs(expected_world)))*2e-7)
    if error>tolerance:failures.append({"node":entry["node_name"],"asset":entry["asset"],"reason":"native world bounds differ","error_m":error,"tolerance_m":tolerance})
    if entry["asset"] in excluded and not obj.hide_render:
        failures.append({"node":entry["node_name"],"reason":"non-renderable helper visible in render"})
    placement_checks.append({"node":entry["node_name"],"asset":entry["asset"],"world_bounds_error_m":error,"tolerance_m":tolerance,"hidden_render":obj.hide_render})
report={"file":bpy.data.filepath,"saved_material_tables_checked":material_checks,"saved_additions_checked":len(placement_checks),
        "visible_additions":sum(not x["hidden_render"] for x in placement_checks),"failures":failures,
        "maximum_native_bounds_error_m":max(x["world_bounds_error_m"] for x in placement_checks),"placements":placement_checks}
(root/"saved_scene_validation.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps({k:v for k,v in report.items() if k!="placements"},indent=2),flush=True)
assert not failures
