"""Export asymmetric source geometry to calibrate UE FBX axes/units/UVs."""
import bpy
import json
from pathlib import Path

root=Path('D:/AtlasMap-tooling/out/Iceland/ue_transfer/20261031')
root.mkdir(parents=True,exist_ok=True)
source=bpy.data.meshes['DFM_e9e72804dcac9974917c']
data=source.copy()
data.materials.clear()
for index in range(len(source.materials)):
    material=bpy.data.materials.get(f'DF_SLOT_{index:04d}') or bpy.data.materials.new(f'DF_SLOT_{index:04d}')
    data.materials.append(material)
obj=bpy.data.objects.new('SM_Probe_Road01',data)
bpy.context.scene.collection.objects.link(obj)
for item in bpy.context.selected_objects:item.select_set(False)
obj.select_set(True);bpy.context.view_layer.objects.active=obj
filename=root/'SM_Probe_Road01.fbx'
bpy.ops.export_scene.fbx(filepath=str(filename),use_selection=True,object_types={'MESH'},
    global_scale=1,apply_unit_scale=False,apply_scale_options='FBX_SCALE_NONE',
    use_space_transform=False,bake_space_transform=False,axis_forward='-Y',axis_up='Z',
    use_mesh_modifiers=False,use_tspace=bool(data.uv_layers),colors_type='LINEAR',
    mesh_smooth_type='FACE',add_leaf_bones=False,bake_anim=False,path_mode='STRIP')
points=[[v.co.x*100,-v.co.y*100,v.co.z*100] for v in source.vertices]
report={'vertices':len(source.vertices),'triangles':len(source.polygons),'slots':len(source.materials),
        'expected_ue_min':list(map(min,zip(*points))),'expected_ue_max':list(map(max,zip(*points))),
        'first_positions':points[:8],'first_uvs':[[float(x) for x in item.uv] for item in source.uv_layers[0].data[:8]],
        'file':str(filename),'source_blend':bpy.data.filepath}
(root/'fbx_probe_expected.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2),flush=True)
