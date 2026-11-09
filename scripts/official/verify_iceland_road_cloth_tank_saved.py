"""Check source attributes, shader inputs and unchanged geometry in the saved scene."""
import bpy
import hashlib
import json
from pathlib import Path
import numpy as np

root=Path('D:/AtlasMap-tooling/out/Iceland')
folder=root/'revised/material_refresh'
application=json.loads((folder/'road_cloth_tank_application.json').read_text())
definitions=json.loads((folder/'material_refresh.json').read_text())['materials']
attributes=json.loads((root/'audit/material_attributes/attributes.json').read_text())
by_asset={}
for obj in bpy.context.scene.objects:
    if obj.type=='MESH':by_asset.setdefault(obj.data.get('unrealAssetPath'),{})[obj.data.name]=obj.data
failures=[];uv_count=color_count=0
for entry in attributes:
    for data in by_asset.get(entry['asset'],{}).values():
        indices=np.empty(len(data.loops),np.uint32);data.loops.foreach_get('vertex_index',indices)
        if hashlib.sha256(indices.astype('<u4').tobytes()).hexdigest()!=entry['index_sha256']:
            failures.append({'asset':entry['asset'],'reason':'native indices differ'});continue
        for channel,file in enumerate(entry['uv_files']):
            source=np.fromfile(root/'audit/material_attributes'/file,'<f4').reshape(-1,2).copy();source[:,1]=1-source[:,1]
            name='UVMap' if channel==0 else f'UV{channel}'
            actual=np.empty(len(data.loops)*2,np.float32);data.uv_layers[name].data.foreach_get('uv',actual)
            if not np.array_equal(actual.reshape(-1,2),source[indices]):failures.append({'asset':entry['asset'],'reason':'UV differs','channel':channel})
            else:uv_count+=1
        expected=np.fromfile(root/'audit/material_attributes'/entry['color_file'],'u1').reshape(-1,4).astype(np.float32)/255 if entry['color_file'] else np.ones((len(data.vertices),4),np.float32)
        actual=np.empty(len(data.loops)*4,np.float32);data.color_attributes['UEVertexColor'].data.foreach_get('color',actual)
        if not np.array_equal(actual.reshape(-1,4),expected[indices]):failures.append({'asset':entry['asset'],'reason':'vertex colours differ'})
        else:color_count+=1
materials=[]
checked_rvt_images=set()
for entry in application['materials']:
    candidates=[m for m in bpy.data.materials if m.users and m.get('unrealMaterialPath')==entry['path'] and m.get('road_cloth_tank_revision')]
    if len(candidates)!=1:failures.append({'material':entry['path'],'reason':'replacement missing or duplicated'});continue
    material=candidates[0];nodes=material.node_tree.nodes
    shader=next(n for n in nodes if n.type=='BSDF_PRINCIPLED')
    if entry['category']=='road':
        if not material.get('source_rvt_albedo') or not material.get('road_vertex_mask_restored') or not shader.inputs['Alpha'].is_linked:
            failures.append({'material':entry['path'],'reason':'road RVT/vertex opacity incomplete'})
        sample=shader.inputs['Base Color'].links[0].from_node
        if sample.type!='TEX_IMAGE' or not sample.image or not sample.image.packed_file or 'rvt_layer0_mip1' not in sample.image.name:
            failures.append({'material':entry['path'],'reason':'wrong RVT colour layer'})
        elif sample.image.name not in checked_rvt_images:
            checked_rvt_images.add(sample.image.name)
            if list(sample.image.size)!=application['rvt_projection']['resolution']:
                failures.append({'material':entry['path'],'reason':'RVT resolution differs'})
            expected_hash=hashlib.sha256(Path(application['rvt_projection']['colour_file']).read_bytes()).digest()
            if hashlib.sha256(sample.image.packed_file.data).digest()!=expected_hash:
                failures.append({'material':entry['path'],'reason':'packed RVT differs from source PNG'})
    if entry['category']=='tank':
        mask=next(n for n in nodes if n.type=='TEX_IMAGE' and n.image and ('_A_HD' in n.image.name or '_Mask_HD' in n.image.name))
        uv=mask.inputs['Vector'].links[0].from_node
        if uv.type!='UVMAP' or uv.uv_map!='UV1':failures.append({'material':entry['path'],'reason':'tank mask UV differs'})
        if not material.get('material_response_from_both_layers'):failures.append({'material':entry['path'],'reason':'tank response still single-layer'})
    if entry['category']=='cloth' and definitions[entry['path']]['SwitchParameters'].get('UseDetailNormal'):
        if not material.get('cloth_detail_normal_restored'):failures.append({'material':entry['path'],'reason':'fabric detail normal absent'})
    materials.append(entry)

def geometry_snapshot():
    bpy.context.view_layer.update()
    objects={o.name:{'data':o.data.name if o.type=='MESH' else None,'matrix':np.asarray(o.matrix_world,dtype=np.float32).tobytes().hex()} for o in bpy.context.scene.objects}
    meshes={}
    for obj in bpy.context.scene.objects:
        if obj.type!='MESH' or obj.data.name in meshes:continue
        data=obj.data;positions=np.empty(len(data.vertices)*3,np.float32);data.vertices.foreach_get('co',positions)
        indices=np.empty(len(data.loops),np.uint32);data.loops.foreach_get('vertex_index',indices)
        faces=np.empty(len(data.polygons),np.int32);data.polygons.foreach_get('material_index',faces)
        meshes[data.name]={'positions':hashlib.sha256(positions.tobytes()).hexdigest(),'indices':hashlib.sha256(indices.tobytes()).hexdigest(),'face_slots':hashlib.sha256(faces.tobytes()).hexdigest()}
    return objects,meshes

file=bpy.data.filepath
current_objects,current_meshes=geometry_snapshot()
backup=max((root/'revised').glob('Iceland_before_road_cloth_tank_repair_*.blend'),key=lambda p:p.stat().st_mtime)
bpy.ops.wm.open_mainfile(filepath=str(backup))
before_objects,before_meshes=geometry_snapshot()
if before_objects!=current_objects:failures.append({'reason':'object transforms or mesh bindings changed from backup'})
if before_meshes!=current_meshes:failures.append({'reason':'vertex positions, topology or face-material assignments changed from backup'})
report={'file':file,'backup':str(backup),'exact_native_uv_channels':uv_count,'exact_vertex_colour_meshes':color_count,
        'materials_checked':len(materials),'scene_objects_compared':len(current_objects),'unique_mesh_geometries_compared':len(current_meshes),
        'geometry_unchanged':before_objects==current_objects and before_meshes==current_meshes,'failures':failures}
(folder/'road_cloth_tank_saved_validation.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2),flush=True)
assert not failures
result=report
