"""Reopen the saved Blender file and compare the reported cliff with its UE component."""
import bpy
import json
import sys
from pathlib import Path

import numpy as np

root = Path(sys.argv[sys.argv.index("--")+1]).resolve()
diagnosis = json.loads((root.parent/"audit/MassifCliff_06_005_diagnosis.json").read_text())
before = json.loads((root.parent/"audit/MassifCliff_06_005_before.json").read_text())
expected = np.array(diagnosis["new_matrix"])
bpy.context.view_layer.update()
candidates = [o for o in bpy.context.scene.objects if o.type=="MESH" and o.data.get("unrealAssetPath")==before["asset"]
              and np.linalg.norm(np.array(o.matrix_world.translation)-expected[:3,3])<0.01]
assert len(candidates)==1, len(candidates)
obj = candidates[0]
actual = np.array(obj.matrix_world,dtype=float)
vertices = np.empty(len(obj.data.vertices)*3,dtype=np.float32)
obj.data.vertices.foreach_get("co",vertices)
positions = vertices.reshape(-1,3)
error = float(np.max(np.linalg.norm(positions@(actual[:3,:3]-expected[:3,:3]).T+actual[:3,3]-expected[:3,3],axis=1)))
assert error < 0.005, error
obj.name="CHECKED_MassifCliff_06_005"
obj["checked_against_native_ue_component"]=diagnosis["component"]
obj["original_blender_object_name"]=before["name"]
obj["native_world_position_error_m"]=error
obj.select_set(True)
bpy.context.view_layer.objects.active=obj
for material in bpy.data.materials:
    if not material.use_nodes:
        continue
    shader=material.node_tree.nodes.get("Principled BSDF")
    if shader and shader.inputs["Base Color"].links:
        node=shader.inputs["Base Color"].links[0].from_node
        if node.type=="TEX_IMAGE":
            material.node_tree.nodes.active=node
    elif shader:
        # Workbench otherwise displays an arbitrary normal-map image as colour.
        # Give its texture preview the existing constant base colour; the PBR
        # shader and its normal-map connection remain untouched.
        name="Base preview constant "+material.name
        image=bpy.data.images.get(name) or bpy.data.images.new(name,width=1,height=1,alpha=True)
        image.pixels[:]=tuple(shader.inputs["Base Color"].default_value)
        image.pack()
        node=material.node_tree.nodes.get("Base colour preview") or material.node_tree.nodes.new("ShaderNodeTexImage")
        node.name="Base colour preview"
        node.label="Constant base colour; no decoded albedo"
        node.image=image
        material.node_tree.nodes.active=node
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=="VIEW_3D":
            space=area.spaces.active
            space.shading.color_type="TEXTURE"
            space.clip_end=100000
            space.overlay.show_floor=False
            space.overlay.show_axis_x=False
            space.overlay.show_axis_y=False
bpy.ops.file.pack_all()
output=root/"Iceland_fixed.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(output),compress=True)
result={"object":obj.name,"source_component":diagnosis["component"],"maximum_world_vertex_error_m":error,
        "before_maximum_bbox_corner_displacement_m":diagnosis["maximum_bbox_corner_displacement_m"],
        "uv_layers":len(obj.data.uv_layers),"material_slots":len(obj.data.materials),
        "packed_images":sum(i.packed_file is not None for i in bpy.data.images),
        "packed_game_images":sum(i.packed_file is not None and not i.name.startswith("Base preview constant ") for i in bpy.data.images),"file":str(output)}
(root/"diagnostics/reopened_native_check.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
print(json.dumps(result,indent=2),flush=True)
# Re-render the delivered previews with the corrected base-colour selection.
from mathutils import Vector
scene=bpy.context.scene
camera=scene.camera
for name,position,target,scale,resolution in [
    ("Iceland_overview",(5000,-1700,3900),(2016,2100,-70),4800,(1800,1400)),
    ("Iceland_top",(2016,2016,6000),(2016,2016,0),4250,(1800,1800)),
    ("Iceland_detail",(3100,1400,1100),(2110,2200,-30),1650,(1800,1200)),
]:
    camera.location=position
    camera.rotation_euler=(Vector(target)-camera.location).to_track_quat("-Z","Y").to_euler()
    camera.data.ortho_scale=scale
    scene.render.resolution_x,scene.render.resolution_y=resolution
    scene.render.filepath=str(root/(name+".png"))
    bpy.ops.render.render(write_still=True)
