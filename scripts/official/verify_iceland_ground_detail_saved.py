"""Check saved ground detail, native helper visibility and unchanged geometry."""
import bpy
import hashlib
import json
from pathlib import Path
import numpy as np

root=Path('D:/AtlasMap-tooling/out/Iceland')
report_file=root/'revised/material_refresh/ground_detail_saved_validation.json'
application=json.loads((root/'revised/material_refresh/ground_detail_application.json').read_text())
helpers=json.loads((root/'revised/material_refresh/helper_visibility_application.json').read_text())
before=json.loads((root/'audit/ground_detail_geometry_before.json').read_text())
failures=[];hidden_present=0;removed_before=[]
for entry in helpers['hidden']:
    obj=bpy.data.objects.get(entry['name'])
    if obj is None:
        if entry['name'] not in before['objects']:removed_before.append(entry['name'])
        else:failures.append({'object':entry['name'],'reason':'helper disappeared during material pass'})
        continue
    if not obj.hide_render or not obj.hide_get():failures.append({'object':obj.name,'reason':'native-hidden helper visible'})
    else:hidden_present+=1
visible_testmap=[o.name for o in bpy.context.scene.objects if o.type=='MESH' and '/TestMap/' in o.data.get('unrealAssetPath','') and not o.hide_get() and not o.hide_render]
if visible_testmap:failures.append({'reason':'TestMap helpers still visible','objects':visible_testmap})
wall=bpy.data.objects.get(application['wall_object'])
if wall is None or wall.material_slots[0].link!='OBJECT' or wall.material_slots[0].material.get('unrealMaterialPath')!=application['wall_material_override']:
    failures.append({'reason':'visible wall material override differs'})
terrain=bpy.data.objects.get(application['terrain']);material=terrain.active_material
nodes=material.node_tree.nodes
colour_nodes=[n for n in nodes if n.type=='TEX_IMAGE' and n.label.startswith('Source colour detail layer ')]
normal_nodes=[n for n in nodes if n.type=='TEX_IMAGE' and n.label.startswith('Source normal XY layer ')]
if len(colour_nodes)!=10 or len(normal_nodes)!=10:failures.append({'reason':'not all source detail layers connected'})
for node in colour_nodes+normal_nodes:
    if list(node.image.size)!=[2048,2048] or node.image.colorspace_settings.name!='Non-Color' or not node.image.packed_file:
        failures.append({'image':node.image.name,'reason':'detail image resolution, colour space or packing differs'})
shader=next(n for n in nodes if n.type=='BSDF_PRINCIPLED')
if not shader.inputs['Normal'].is_linked or not shader.inputs['Base Color'].is_linked:failures.append({'reason':'ground colour or normal missing'})
normal_map=next(n for n in nodes if n.type=='NORMAL_MAP')
if normal_map.uv_map!='GroundWorldUV':failures.append({'reason':'detail normal UV basis absent'})
for path in application['road_materials']:
    if not any(m.users and m.get('unrealMaterialPath')==path and m.get('road_near_detail_restored') for m in bpy.data.materials):
        failures.append({'material':path,'reason':'road detail revision missing'})
source=(root.parent.parent/'scripts/verify_iceland_road_cloth_tank_saved.py').read_text()
start=source.index('def geometry_snapshot():');end=source.index('\nfile=bpy.data.filepath',start)
exec(source[start:end])
objects,meshes=geometry_snapshot()
if objects!=before['objects']:failures.append({'reason':'object matrices or mesh bindings changed during detail pass'})
if meshes!=before['meshes']:failures.append({'reason':'vertex positions, topology or face slots changed during detail pass'})
report={'file':bpy.data.filepath,'source_hidden_helpers_present':hidden_present,'removed_before_material_pass':removed_before,
        'visible_testmap_objects':visible_testmap,'source_colour_layers':len(colour_nodes),'source_normal_layers':len(normal_nodes),
        'road_materials_checked':len(application['road_materials']),'objects_compared':len(objects),'unique_meshes_compared':len(meshes),
        'geometry_unchanged':objects==before['objects'] and meshes==before['meshes'],'failures':failures}
report_file.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2),flush=True)
assert not failures
result=report
