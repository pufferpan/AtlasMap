"""Apply verified render sections and missing common layers to the active scene.

Run inside the connected Blender instance; preserve the current scene and edits.
"""
import bpy
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from mathutils import Matrix, Vector

root=Path("D:/AtlasMap-tooling/out/Iceland/revised")
folder=root/"common_static_repair"
bundle=json.loads((folder/"repair_bundle.json").read_text(encoding="utf-8-sig"))
backup=root/("Iceland_before_common_repair_"+str(int(time.time()))+".blend")
bpy.ops.wm.save_as_mainfile(filepath=str(backup),copy=True,compress=True)
image_cache={}
material_cache={}


def image(relative,non_color=False):
    if not relative:return None
    path=(folder/relative).resolve()
    if not path.exists():return None
    key=str(path),non_color
    if key not in image_cache:
        item=bpy.data.images.load(str(path),check_existing=False)
        item.colorspace_settings.name="Non-Color" if non_color else "sRGB"
        image_cache[key]=item
    return image_cache[key]


def material(path):
    if path in material_cache:return material_cache[path]
    definition=bundle["materials"].get(path,{})
    name=path.rsplit(".",1)[-1].rsplit("/",1)[-1]
    item=bpy.data.materials.new("CHECKED_"+name)
    item["unrealMaterialPath"]=path
    item["render_section_repair"]=True
    item.use_nodes=True
    nodes,links=item.node_tree.nodes,item.node_tree.links
    shader=next(n for n in nodes if n.type=="BSDF_PRINCIPLED")
    tint=list(definition.get("tint") or [1,1,1,1])
    tint[3]=max(0,min(1,tint[3])) if tint[3]>0 else 1
    item.diffuse_color=tint
    shader.inputs["Base Color"].default_value=tint
    shader.inputs["Metallic"].default_value=0
    shader.inputs["Roughness"].default_value=.65
    base=image(definition.get("base_color"))
    active=None
    if base:
        node=nodes.new("ShaderNodeTexImage")
        node.image=base
        node.location=(-650,200)
        active=node
        if any(abs(v-1)>1e-6 for v in tint[:3]):
            multiply=nodes.new("ShaderNodeMixRGB")
            multiply.blend_type="MULTIPLY"
            multiply.inputs[0].default_value=1
            multiply.inputs[2].default_value=tint
            links.new(node.outputs["Color"],multiply.inputs[1])
            links.new(multiply.outputs[0],shader.inputs["Base Color"])
        else:links.new(node.outputs["Color"],shader.inputs["Base Color"])
    else:
        item["unresolved_base_color"]=definition.get("original_base_color") or "no decoded base-colour binding"
    normal_image=image(definition.get("normal"),True)
    if normal_image:
        node=nodes.new("ShaderNodeTexImage")
        node.image=normal_image
        node.location=(-650,-100)
        normal=nodes.new("ShaderNodeNormalMap")
        normal.location=(-300,-100)
        links.new(node.outputs["Color"],normal.inputs["Color"])
        links.new(normal.outputs["Normal"],shader.inputs["Normal"])
    packed=image(definition.get("mra"),True)
    packed_name=str(definition.get("original_mra") or "").lower()
    if packed and any(t in packed_name for t in ("mra","orm","rma")):
        node=nodes.new("ShaderNodeTexImage")
        node.image=packed
        separate=nodes.new("ShaderNodeSeparateColor")
        links.new(node.outputs["Color"],separate.inputs["Color"])
        metal,rough=("Blue","Green") if "orm" in packed_name else (("Green","Red") if "rma" in packed_name else ("Red","Green"))
        links.new(separate.outputs[metal],shader.inputs["Metallic"])
        links.new(separate.outputs[rough],shader.inputs["Roughness"])
    if active is None:
        # Workbench must not display an active normal/mask image as albedo.
        constant=bpy.data.images.new("Missing albedo preview "+name,width=1,height=1,alpha=True)
        constant.pixels[:]=tint
        constant.pack()
        active=nodes.new("ShaderNodeTexImage")
        active.image=constant
        active.label="Constant preview; original albedo not decoded"
    nodes.active=active
    material_cache[path]=item
    return item


checked=[]
skipped=[]
source_data={}
for entry in bundle["meshes"]:
    data=bpy.data.meshes.get(entry["data_name"])
    if data is None or data.get("unrealAssetPath")!=entry["asset"]:
        skipped.append({"asset":entry["asset"],"reason":"live mesh was renamed or replaced"})
        continue
    indices=np.empty(len(data.loops),dtype=np.uint32)
    data.loops.foreach_get("vertex_index",indices)
    digest=hashlib.sha256(indices.astype("<u4").tobytes()).hexdigest()
    if digest!=entry["index_sha256"] or len(data.polygons)!=entry["triangle_count"]:
        skipped.append({"asset":entry["asset"],"reason":"live mesh topology changed since snapshot"})
        continue
    faces=np.fromfile(folder/entry["face_material_file"],dtype="<u2")
    assert len(faces)==len(data.polygons)
    used=entry["used_source_slots"]
    remap=np.full(max(used)+1,-1,dtype=np.int32)
    for slot,index in enumerate(used):remap[index]=slot
    assert np.all(remap[faces]>=0)
    prepared=[material(entry["materials"][index]) for index in used]
    data.materials.clear()
    for assigned in prepared:data.materials.append(assigned)
    data.polygons.foreach_set("material_index",remap[faces])
    data["unreal_material_source_slots"]=used
    data["verified_section_materials"]=True
    source_data[entry["asset"]]=data
    checked.append({"asset":entry["asset"],"slots":len(used),"triangles":len(faces)})

before=set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=str(folder/"common_additions.glb"),import_pack_images=True)
imported=[o for o in bpy.data.objects if o not in before]
by_name={o.name:o for o in imported}
collection=bpy.data.collections.new("Checked common additions - Iceland Tower TowerB")
bpy.context.scene.collection.children.link(collection)
for obj in imported:
    for old in list(obj.users_collection):old.objects.unlink(obj)
    collection.objects.link(obj)
addition_checks=[]
spires=[]
basis=Matrix.Diagonal((1,-1,1,1))
for entry in bundle["additions"]:
    obj=by_name.get(entry["node_name"])
    if obj is None:raise RuntimeError("Missing imported node "+entry["node_name"])
    asset=entry["asset"]
    original=obj.data
    if asset in source_data:
        obj.data=source_data[asset]
        if original.users==0:bpy.data.meshes.remove(original)
    else:
        obj.data["unrealAssetPath"]=asset
        for i,old in enumerate(list(obj.data.materials)):
            path=old.get("unrealMaterialPath") if old else None
            if path in bundle["materials"]:obj.data.materials[i]=material(path)
    obj["source_level"]=entry["source_level"]
    obj["common_repair_node"]=entry["node_name"]
    obj.name=asset.rsplit(".",1)[-1]+" [checked addition]"
    native=np.array(entry["MatrixUE"]).reshape(4,4).T
    native[:3,3]/=100
    expected=basis@Matrix(native.tolist())@basis
    if "Industrial_Tower_02a." in asset:
        obj.name="CHECKED_Industrial_Spire_02a"
        spires.append(obj)
    addition_checks.append((obj,expected,asset,entry["source_level"]))
bpy.context.view_layer.update()
report=[]
affine_bakes=0
for obj,expected,asset,level in addition_checks:
    actual=obj.matrix_world.copy()
    discrepancy=max(abs(actual[r][c]-expected[r][c]) for r in range(4) for c in range(4))
    if discrepancy>0.0001:
        residual=actual.inverted()@expected
        data=obj.data.copy()
        obj.data=data
        data.transform(residual)
        obj["native_affine_residual_baked"]=True
        affine_bakes+=1
    position_error=(obj.matrix_world.translation-expected.translation).length
    assert position_error<0.003,(obj.name,position_error)
    report.append({"name":obj.name,"asset":asset,"source_level":level,"origin_error_m":position_error})
for obj in bpy.context.selected_objects:obj.select_set(False)
for obj in spires:obj.select_set(True)
if spires:
    bpy.context.view_layer.objects.active=spires[0]
    target=Vector((2334,2420,90))
    for area in bpy.context.screen.areas:
        if area.type=="VIEW_3D":
            space=area.spaces.active
            space.clip_end=100000
            space.region_3d.view_location=target
            space.region_3d.view_rotation=(target-Vector((2480,2200,170))).to_track_quat("-Z","Y")
            space.region_3d.view_distance=220
            space.region_3d.view_perspective="ORTHO"
            space.shading.type="SOLID"
            space.shading.color_type="TEXTURE"
            area.tag_redraw()
bpy.ops.file.pack_all()
output=root/"Iceland_common_static_fixed.blend"
if output.exists():output=root/("Iceland_common_static_fixed_"+str(int(time.time()))+".blend")
bpy.ops.wm.save_as_mainfile(filepath=str(output),compress=True)
spire_report=[]
for obj in spires:
    bounds=[obj.matrix_world@Vector(v) for v in obj.bound_box]
    spire_report.append({"name":obj.name,"source_level":obj["source_level"],"position":list(obj.matrix_world.translation),
                         "minimum_z_m":min(v.z for v in bounds),"maximum_z_m":max(v.z for v in bounds)})
summary={"saved_as":str(output),"backup":str(backup),"mesh_tables_applied":len(checked),
         "multimaterial_meshes_applied":sum(x["slots"]>1 for x in checked),"material_definitions":len(material_cache),
         "decoded_images_loaded":len(image_cache),"new_objects":len(report),"affine_residuals_baked":affine_bakes,
         "maximum_new_origin_error_m":max(x["origin_error_m"] for x in report),"spires":spire_report,"skipped":skipped}
(folder/"live_application_check.json").write_text(json.dumps({"summary":summary,"mesh_checks":checked,"addition_checks":report},indent=2),encoding="utf-8")
result=summary
