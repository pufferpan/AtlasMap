"""Export the accepted Blender scene with explicit geometry/material provenance."""
import bpy
import hashlib
import json
import re
import time
from pathlib import Path
import numpy as np
from mathutils import Matrix

import sys as _sys, os as _os
_sys.path.insert(0,str(Path(__file__).resolve().parent))
from map_geometry import audit_triangles
from map_image_header import image_dimensions
from map_json import write_json
ROOT=Path(_os.environ.get('ATLASMAP_UE_ROOT') or Path('.').resolve())
ROOT.mkdir(parents=True,exist_ok=True)
SHARD_COUNT=max(1,int(_os.environ.get('ATLASMAP_BLENDER_SHARD_COUNT','1')))
SHARD_INDEX=int(_os.environ.get('ATLASMAP_BLENDER_SHARD_INDEX','0'))
RUN_ID=_os.environ.get('ATLASMAP_PARALLEL_RUN_ID','')
MAP_CHUNKS=_os.environ.get('ATLASMAP_MAP_CHUNKS')=='1'
if not 0<=SHARD_INDEX<SHARD_COUNT:raise ValueError('Invalid Blender shard')
chunk_materials=set();chunk_meshes=set()
def owned(asset_id):
    if MAP_CHUNKS:return asset_id in (chunk_materials if asset_id.startswith('M_') else chunk_meshes)
    return int(hashlib.sha256(asset_id.encode()).hexdigest()[:8],16)%SHARD_COUNT==SHARD_INDEX
for part in ['meshes','textures','material_graphs','validation']:(ROOT/part).mkdir(exist_ok=True)
def uid(prefix,value):return prefix+hashlib.sha256(value.encode()).hexdigest()[:20]
def value(v):
    if isinstance(v,(bool,int,float,str)):return v
    try:return list(v)
    except:return str(v)
def write(name,data):write_json(ROOT/name,data)
def status(phase,**details):
    write('blender_export_status.json',dict(phase=phase,time=time.time(),**details));print(phase,details,flush=True)
def task_event(**data):
    if SHARD_COUNT>1:print('@ATLASMAP_TASK '+json.dumps(data,ensure_ascii=False),flush=True)

bpy.context.view_layer.update()
source_scene=bpy.context.scene
objects=list(bpy.context.scene.objects)
from blender_live_preview import LivePreview
LivePreview().add(objects,replace=True,force=True)
source_data={o.data.name:o.data for o in objects if o.type=='MESH'}
materials={m.name:m for d in source_data.values() for m in d.materials if m}
materials.update({s.material.name:s.material for o in objects if o.type=='MESH' for s in o.material_slots if s.material})
material_ids={name:uid('M_',name) for name in materials}
mesh_ids={name:uid('SM_',name) for name in source_data}
chunk=None
if MAP_CHUNKS:
    _sys.path.insert(0,str(Path(__file__).resolve().parent))
    from map_chunks import partition_objects
    rows=[{'id':uid('O_',o.name),'parent':uid('O_',o.parent.name) if o.parent else None,
           'triangles':len(o.data.polygons) if o.type=='MESH' else 1,
           'properties':{'source_level':o.get('source_level')}} for o in objects]
    chunk=partition_objects(rows,SHARD_COUNT)[SHARD_INDEX]
    chunk_object_ids=set(chunk['object_ids'])
    local_objects=[o for o in objects if uid('O_',o.name) in chunk_object_ids]
    chunk_meshes={mesh_ids[o.data.name] for o in local_objects if o.type=='MESH'}
    chunk_materials={material_ids[m.name] for o in local_objects if o.type=='MESH' for m in o.data.materials if m}
    chunk_materials.update(material_ids[s.material.name] for o in local_objects if o.type=='MESH'
                           for s in o.material_slots if s.material)
owned_material_total=sum(owned(mid) for mid in material_ids.values())
task_event(event='assigned',work={'meshes':sum(owned(mid) for mid in mesh_ids.values()),'materials':owned_material_total},
           text=f'分块 {SHARD_INDEX+1}/{SHARD_COUNT}：独立导出本块模型和 {owned_material_total} 个材质')
material_done=0
image_records={};image_keys={};material_records=[]
status('manifest',objects=len(objects),meshes=len(source_data),materials=len(materials))
for material_index,(name,material) in enumerate(sorted(materials.items())):
    if not owned(material_ids[name]):continue
    graph=[];indices={node:i for i,node in enumerate(material.node_tree.nodes)} if material.use_nodes else {}
    for node,index in indices.items():
        inputs=[]
        for socket in node.inputs:
            entry={'name':socket.name,'identifier':socket.identifier,'type':socket.type}
            if hasattr(socket,'default_value'):entry['default']=value(socket.default_value)
            if socket.is_linked:
                link=socket.links[0];entry['link']={'node':indices[link.from_node],'output':list(link.from_node.outputs).index(link.from_socket)}
            inputs.append(entry)
        record={'id':index,'type':node.type,'name':node.name,'inputs':inputs,
                'outputs':[{'name':s.name,'identifier':s.identifier,'type':s.type} for s in node.outputs]}
        for attribute in ['operation','blend_type','data_type','use_clamp','mode','space','uv_map','layer_name','extension','interpolation','from_instancer']:
            if hasattr(node,attribute):record[attribute]=value(getattr(node,attribute))
        if node.type=='TEX_IMAGE':
            if not node.image:raise RuntimeError('Texture node without image: '+name)
            image=node.image
            if image.name not in image_keys:
                if image.packed_file:blob=bytes(image.packed_file.data)
                else:
                    path=Path(bpy.path.abspath(image.filepath))
                    if not path.is_file() or image.is_dirty:raise RuntimeError('Image is not safely serialized: '+image.name)
                    blob=path.read_bytes()
                digest=hashlib.sha256(blob).hexdigest()
                srgb=image.colorspace_settings.name=='sRGB'
                if image.colorspace_settings.name not in ['sRGB','Non-Color']:raise RuntimeError('Unsupported image colour space '+image.colorspace_settings.name)
                key='T_'+digest[:20]+('_C' if srgb else '_D')
                ext=Path(image.filepath).suffix.lower() or '.png'
                relative='textures/'+key+ext
                if key not in image_records:
                    if _os.environ.get('ATLASMAP_IMAGE_CACHE'):
                        _sys.path.insert(0,str(Path(__file__).parent))
                        from map_io import cached_blob
                        cached_blob(_os.environ['ATLASMAP_IMAGE_CACHE'],ROOT/relative,blob,digest)
                    else:(ROOT/relative).write_bytes(blob)
                    # Image.size acquires and retains a decoded Blender buffer.
                    # Thousands of packed PNGs otherwise consume tens of GB just
                    # to build this metadata table. Keep their bytes untouched.
                    image_records[key]={'id':key,'file':relative,'sha256':digest,'srgb':srgb,'size':image_dimensions(blob,image.name),'alpha_mode':image.alpha_mode,'source_name':image.name,'source_path':image.filepath}
                image_keys[image.name]=key
            record['image']=image_keys[image.name]
        graph.append(record)
    item={'id':material_ids[name],'source_name':name,'source_path':material.get('unrealMaterialPath'),
          'use_nodes':material.use_nodes,'diffuse_color':list(material.diffuse_color),'metallic':material.metallic,'roughness':material.roughness,
          'backface_culling':material.use_backface_culling,'surface_render_method':material.surface_render_method,
          'surface':json.loads(material.get('map_surface','{}')),'nodes':graph,'properties':{k:value(v) for k,v in material.items()}}
    material_records.append(item)
    material_done+=1
    if material_done%8==0 or material_done==owned_material_total:
        task_event(event='progress',done=material_done,total=owned_material_total,unit='材质',current=name,
                   text=f'材质 {material_done}/{owned_material_total} · {material_ids[name]} · {name}')
    if material_index%100==0:status('material_manifest',completed=material_index,total=len(materials),unique_images=len(image_records))

mesh_records=[];mesh_lookup={};source_meshes={}
for name,data in sorted(source_data.items()):
    vertices=np.empty(len(data.vertices)*3,np.float32);data.vertices.foreach_get('co',vertices);vertices=vertices.reshape(-1,3)
    indices=np.empty(len(data.loops),np.uint32);data.loops.foreach_get('vertex_index',indices)
    faces=np.empty(len(data.polygons),np.int32);data.polygons.foreach_get('material_index',faces)
    if any(len(p.vertices)!=3 for p in data.polygons):raise RuntimeError('Non-triangle source requires explicit triangulation: '+name)
    record={'id':mesh_ids[name],'source_name':name,'source_asset':data.get('unrealAssetPath'),
            'vertices':len(data.vertices),'triangles':len(data.polygons),
            'uv_layers':[l.name for l in data.uv_layers],
            'active_render_uv':next((i for i,l in enumerate(data.uv_layers) if l.active_render),0),
            'color_layer':data.color_attributes.active_color.name if data.color_attributes.active_color else None,
            'materials':[material_ids[m.name] if m else None for m in data.materials],
            'local_min_blender':vertices.min(0).tolist(),'local_max_blender':vertices.max(0).tolist(),
            'position_sha256':hashlib.sha256(vertices.astype('<f4').tobytes()).hexdigest(),
            'index_sha256':hashlib.sha256(indices.astype('<u4').tobytes()).hexdigest(),
            'face_slot_counts':{str(i):int(np.count_nonzero(faces==i)) for i in sorted(set(faces))},
            'fbx':'meshes/'+mesh_ids[name]+'.fbx'}
    record.update(audit_triangles(vertices,indices,faces))
    triangle_indices=indices.reshape(-1,3)
    repeated=(triangle_indices[:,0]==triangle_indices[:,1])|(triangle_indices[:,0]==triangle_indices[:,2])|(triangle_indices[:,1]==triangle_indices[:,2])
    record['repeated_index_triangles']=int(np.count_nonzero(repeated))
    record['renderable_face_slot_counts']={str(i):int(np.count_nonzero((faces==i)&~repeated)) for i in sorted(set(faces))}
    write('validation/'+mesh_ids[name]+'.json',{'source_positions_sample':vertices[:16].tolist(),'source_loop_uv_samples':[[list(item.uv) for item in layer.data[:12]] for layer in data.uv_layers]})
    mesh_records.append(record);mesh_lookup[name]=record;source_meshes[record['id']]=(data,None)

C=Matrix.Diagonal((1,-1,1,1))
object_records=[]
for obj in sorted(objects,key=lambda o:o.name):
    matrix=obj.matrix_world.copy();location,rotation,scale=matrix.decompose();trs=Matrix.LocRotScale(location,rotation,scale)
    residual=max(abs(matrix[r][c]-trs[r][c]) for r in range(3) for c in range(3))
    mesh_id=mesh_ids[obj.data.name] if obj.type=='MESH' else None
    if obj.type=='MESH' and residual>1e-5:
        native=mesh_lookup[obj.data.name]
        variant=dict(native);variant['id']=uid('SM_',obj.data.name+'__affine__'+obj.name);variant['source_mesh']=native['id']
        residual_matrix=trs.inverted()@matrix
        variant['residual_matrix']=[list(row) for row in residual_matrix]
        data=obj.data.copy();data.transform(residual_matrix)
        vertices=np.empty(len(data.vertices)*3,np.float32);data.vertices.foreach_get('co',vertices);vertices=vertices.reshape(-1,3)
        indices=np.empty(len(data.loops),np.uint32);data.loops.foreach_get('vertex_index',indices)
        faces=np.empty(len(data.polygons),np.int32);data.polygons.foreach_get('material_index',faces)
        variant.update(audit_triangles(vertices,indices,faces))
        variant.update(local_min_blender=vertices.min(0).tolist(),local_max_blender=vertices.max(0).tolist())
        bpy.data.meshes.remove(data)
        variant['fbx']='meshes/'+variant['id']+'.fbx'
        mesh_records.append(variant);source_meshes[variant['id']]=(obj.data,trs.inverted()@matrix);mesh_id=variant['id']
        if MAP_CHUNKS and uid('O_',obj.name) in chunk_object_ids:chunk_meshes.add(variant['id'])
    ue=C@trs@C
    ue.translation*=100
    if obj.type=='CAMERA':
        camera_basis=Matrix(((0,1,0),(0,0,1),(-1,0,0)))
        camera_rotation=C.to_3x3()@rotation.to_matrix()@camera_basis
        ue=Matrix.LocRotScale(C.to_3x3()@location*100,camera_rotation.to_quaternion(),scale)
    ue_location,ue_rotation,ue_scale=ue.decompose()
    entry={'id':uid('O_',obj.name),'name':obj.name,'type':obj.type,'mesh':mesh_id,
           'location_cm':list(ue_location),'rotation_xyzw':[ue_rotation.x,ue_rotation.y,ue_rotation.z,ue_rotation.w],'scale':list(ue_scale),
           'blender_matrix':[list(row) for row in matrix],
           'ue_matrix':[list(row) for row in ue],
           'hidden_render':obj.hide_render,'hidden_editor':obj.hide_get() or obj.hide_viewport,
           'collections':[c.name for c in obj.users_collection],'parent':uid('O_',obj.parent.name) if obj.parent else None,
           'properties':{k:value(v) for k,v in obj.items()}}
    if obj.type=='MESH':entry['materials']=[material_ids[s.material.name] if s.material else None for s in obj.material_slots]
    if obj.type=='CAMERA':entry['camera']={'projection':obj.data.type,'horizontal_fov_degrees':obj.data.angle_x*180/np.pi,'ortho_width_cm':obj.data.ortho_scale*100,'clip_start_cm':obj.data.clip_start*100,'clip_end_cm':obj.data.clip_end*100}
    object_records.append(entry)
manifest={'source_blend':bpy.data.filepath,'source_blender_version':bpy.app.version_string,
          'ue_root':'/Game/Imported/Iceland_Blender_20261031','level':'/Game/Maps/Iceland_Blender_20261031',
          'objects':object_records,'meshes':mesh_records,'materials':material_records,'images':list(image_records.values()),
          'coordinate_mapping':'UE centimetres = 100 * (Blender X, -Blender Y, Blender Z); FBX calibrated separately',
          'render_aspect':bpy.context.scene.render.resolution_x/bpy.context.scene.render.resolution_y,
          'color_management':{'view_transform':bpy.context.scene.view_settings.view_transform,'look':bpy.context.scene.view_settings.look},
          'counts':{'objects':len(object_records),'mesh_objects':sum(o['type']=='MESH' for o in object_records),
                    'mesh_assets':len(mesh_records),'materials':len(material_records),'images':len(image_records),
                    'hidden_render_meshes':sum(o['type']=='MESH' and o['hidden_render'] for o in object_records)}}
if MAP_CHUNKS:
    manifest['catalog']={'objects':object_records,'meshes':mesh_records,
                         'material_ids':[material_ids[name] for name in sorted(materials)]}
    manifest['objects']=[o for o in object_records if o['id'] in chunk_object_ids]
    manifest['meshes']=[m for m in mesh_records if owned(m['id'])]
    manifest['chunk']=dict(chunk,run_id=RUN_ID,count=SHARD_COUNT)
    manifest['counts'].update(objects=len(manifest['objects']),mesh_assets=len(manifest['meshes']),
        mesh_objects=sum(o['type']=='MESH' for o in manifest['objects']),
        hidden_render_meshes=sum(o['type']=='MESH' and o['hidden_render'] for o in manifest['objects']))
    task_event(event='assigned',work={'levels':len(chunk['source_levels']),'objects':len(local_objects),
               'meshes':len(manifest['meshes']),'materials':len(material_records)},
               text=f"地图分块 {SHARD_INDEX+1}：{len(chunk['source_levels'])} 源地图块 / {len(local_objects)} 对象")
elif SHARD_COUNT>1:
    manifest['parallel']={'run_id':RUN_ID,'index':SHARD_INDEX,'count':SHARD_COUNT,
                          'all_material_ids':[material_ids[name] for name in sorted(materials)]}
write('manifest.json',manifest)
owned_meshes=[record for record in mesh_records if owned(record['id'])]
task_event(event='assigned',work={'meshes':len(owned_meshes),'materials':len(material_records),'textures':len(image_records)},
           text=f'本块资源：{len(owned_meshes)} 模型 / {len(material_records)} 材质 / {len(image_records)} 贴图')

for item in bpy.context.selected_objects:item.select_set(False)
export_scene=bpy.data.scenes.new('UE_transfer_export_only')
export_scene.unit_settings.scale_length=1
bpy.context.window.scene=export_scene
temporary=bpy.data.objects.new('UE_Export_Temporary',next(iter(source_data.values()),None));export_scene.collection.objects.link(temporary)
placeholders=[]
for index in range(max((len(r['materials']) for r in mesh_records),default=0)):
    name=f'DF_SLOT_{index:04d}';placeholders.append(bpy.data.materials.get(name) or bpy.data.materials.new(name))
for index,record in enumerate(owned_meshes):
    target=ROOT/record['fbx']
    revision=target.with_suffix('.revision')
    if target.is_file() and (len(record['materials'])<=1 or (revision.is_file() and revision.read_text()=='preserve_face_slots_v2')):
        with target.open('rb') as handle:
            if target.stat().st_size>160:
                handle.seek(-16,2)
                if handle.read()==bytes.fromhex('f85a8c6adef5d97eece90ce3758f290b'):continue
    original,residual=source_meshes[record['id']]
    data=original.copy()
    if residual is not None:data.transform(residual)
    face_indices=np.empty(len(data.polygons),np.int32);data.polygons.foreach_get('material_index',face_indices)
    data.materials.clear()
    for slot in range(len(record['materials'])):data.materials.append(placeholders[slot])
    data.polygons.foreach_set('material_index',face_indices)
    temporary.data=data;temporary.name=record['id'];temporary.hide_render=False;temporary.hide_set(False)
    temporary.select_set(True);bpy.context.view_layer.objects.active=temporary
    partial=target.with_name(target.stem+'.partial.fbx')
    bpy.ops.export_scene.fbx(filepath=str(partial),use_selection=True,object_types={'MESH'},
        global_scale=1,apply_unit_scale=False,apply_scale_options='FBX_SCALE_NONE',
        use_space_transform=False,bake_space_transform=False,axis_forward='-Y',axis_up='Z',
        use_mesh_modifiers=False,use_tspace=bool(data.uv_layers),colors_type='LINEAR',
        mesh_smooth_type='FACE',add_leaf_bones=False,bake_anim=False,path_mode='STRIP')
    partial.replace(target)
    revision.write_text('preserve_face_slots_v2')
    temporary.select_set(False);temporary.data=original;bpy.data.meshes.remove(data)
    if index%8==0 or index+1==len(owned_meshes):
        status('fbx',completed=index+1,total=len(owned_meshes))
        task_event(event='progress',done=index+1,total=len(owned_meshes),unit='模型',current=record['source_name'],
                   text=f"模型 {index+1}/{len(owned_meshes)} · {record['id']} · {record['source_name']}")
if MAP_CHUNKS:
    # Use the same native save path as the source importer. Library-writing a
    # live Scene crashes Blender 5.2; save a copy after removing outside objects.
    local_images={node.image for name,mat in materials.items() if material_ids[name] in chunk_materials and mat.use_nodes
                  for node in mat.node_tree.nodes if node.type=='TEX_IMAGE' and node.image}
    for image in local_images:
        if not image.packed_file:image.pack()
    bpy.context.window.scene=source_scene
    bpy.data.objects.remove(temporary,do_unlink=True)
    bpy.data.scenes.remove(export_scene)
    outside=[obj for obj in list(source_scene.objects) if uid('O_',obj.name) not in chunk_object_ids]
    if outside:bpy.data.batch_remove(ids=outside)
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'chunk.blend'),copy=True,compress=True)
status('complete',counts=manifest['counts'])
write('parallel_result.json',{'complete':True,'run_id':RUN_ID,
      'meshes':[m['id'] for m in mesh_records if owned(m['id'])],
      'materials':[m['id'] for m in material_records]})
