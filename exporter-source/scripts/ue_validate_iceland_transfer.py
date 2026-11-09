"""Read-back validation of complete scene identity, transforms, slots and assets."""
import json
import math
import re
import time
import traceback
from pathlib import Path
import unreal
import ue_iceland_bridge as bridge

ROOT=bridge.ROOT
_handle=None
_busy=False
state={}
rows=[]
_verified_masters=set()
_instance_rows={r['id']:r for r in bridge.INSTANCE_PLAN['instances']}
_master_rows={r['id']:r for r in bridge.INSTANCE_PLAN['parents']}

def error(kind,identifier,reason,**details):state['errors'].append(dict(kind=kind,id=identifier,reason=reason,**details))
def persist():
    state['updated']=time.time();(ROOT/'ue_validation_status.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    if state.get('complete'):(ROOT/f"ue_validation_{state['phase']}.json").write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
def texture(row):
    obj=bridge.asset('Textures',row['id'])
    dims=[obj.blueprint_get_size_x(),obj.blueprint_get_size_y()]
    if dims!=row['size']:error('texture',row['id'],'size differs',actual=dims,expected=row['size'])
    if bool(obj.get_editor_property('srgb'))!=row['srgb']:error('texture',row['id'],'sRGB differs')
    if obj.get_editor_property('compression_no_alpha'):error('texture',row['id'],'alpha discarded')
    if str(obj.get_editor_property('compression_settings'))!=str(unreal.TextureCompressionSettings.TC_EDITOR_ICON):error('texture',row['id'],'lossless transfer compression differs')
    if unreal.EditorAssetLibrary.get_metadata_tag(obj,'BlenderSHA256')!=row['sha256']:error('texture',row['id'],'source hash metadata differs')

def mesh(row):
    obj=bridge.asset('Meshes',row['id']);desc=obj.get_static_mesh_description(0)
    if desc.get_triangle_count()!=row['triangles']-row.get('zero_area_triangles',row.get('repeated_index_triangles',0)):error('mesh',row['id'],'triangle count differs')
    sub=unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    uv=sub.get_num_uv_channels(obj,0)
    if uv!=len(row['uv_layers']):error('mesh',row['id'],'UV channel count differs',actual=uv,expected=len(row['uv_layers']))
    samples=json.loads((ROOT/'validation'/f"{row.get('source_mesh',row['id'])}.json").read_text())
    if not row.get('residual_matrix'):
        sample_error=0
        for i,point in enumerate(samples['source_positions_sample']):
            if i>=desc.get_vertex_count():break
            actual=desc.get_vertex_position(unreal.VertexID(i));expected=[point[0]*100,-point[1]*100,point[2]*100]
            sample_error=max(sample_error,max(abs(a-b) for a,b in zip([actual.x,actual.y,actual.z],expected)))
        sample_magnitude=max(abs(v)*100 for p in samples['source_positions_sample'] for v in p)
        sample_tolerance=max(.05,sample_magnitude*4*1.1920929e-7)
        state['maximum_sampled_vertex_error_cm']=max(state.get('maximum_sampled_vertex_error_cm',0),sample_error)
        if sample_error>sample_tolerance:error('mesh',row['id'],'sampled vertex positions differ',error_cm=sample_error,tolerance_cm=sample_tolerance)
    bounds=obj.get_bounds();origin=bounds.origin;extent=bounds.box_extent
    actual_min=[origin.x-extent.x,origin.y-extent.y,origin.z-extent.z]
    actual_max=[origin.x+extent.x,origin.y+extent.y,origin.z+extent.z]
    lo=row['local_min_blender'];hi=row['local_max_blender']
    expected_min=[lo[0]*100,-hi[1]*100,lo[2]*100];expected_max=[hi[0]*100,-lo[1]*100,hi[2]*100]
    tolerance=.3 if row.get('residual_matrix') else .05
    delta=max(abs(a-b) for a,b in zip(actual_min+actual_max,expected_min+expected_max))
    state['maximum_mesh_bounds_error_cm']=max(state.get('maximum_mesh_bounds_error_cm',0),delta)
    if delta>tolerance:error('mesh',row['id'],'local bounds differ',error_cm=delta,tolerance_cm=tolerance)
    defaults=bridge.PLAN['mesh_materials'][row['id']];mapping=bridge.mesh_slot_map(obj)
    for index,mid in enumerate(defaults):
        actual=obj.get_material(mapping[index]);expected=bridge.asset('Materials',mid)
        if actual!=expected:error('mesh',row['id'],'default material binding differs',slot=index)
    # Imported section indices can change order, but their material membership
    # must retain the source face totals for every authored material slot.
    if desc.get_polygon_count()==desc.get_triangle_count():
        groups={}
        for group in range(desc.get_polygon_group_count()):
            if desc.is_polygon_group_valid(unreal.PolygonGroupID(group)):
                groups[group]=desc.get_num_polygon_group_polygons(unreal.PolygonGroupID(group))
        totals={}
        inv={ue:source for source,ue in mapping.items()}
        for section,count in groups.items():
            if not count:continue
            slot=sub.get_lod_material_slot(obj,0,section)
            source=inv.get(slot)
            if source is None:error('mesh',row['id'],'section points outside slot map',section=section);continue
            totals[str(source)]=totals.get(str(source),0)+count
        expected_counts={k:v-row.get('zero_area_face_slot_counts',{}).get(k,0) for k,v in row['face_slot_counts'].items()}
        if totals!={k:v for k,v in expected_counts.items() if v}:
            error('mesh',row['id'],'per-material triangle totals differ',actual=totals,expected=expected_counts)

def material_graph(row):
    obj=bridge.asset('Materials',row['id'])
    if unreal.EditorAssetLibrary.get_metadata_tag(obj,'BlenderGraphSHA256')!=row['sha256']:error('material',row['id'],'DAG hash differs')
    if bool(obj.get_editor_property('two_sided'))!=row['two_sided']:error('material',row['id'],'two-sided flag differs')
    if bool(obj.get_editor_property('tangent_space_normal')):error('material',row['id'],'normal output incorrectly marked tangent-space')
    expected=unreal.BlendMode.BLEND_MASKED if row['masked'] else unreal.BlendMode.BLEND_OPAQUE
    if obj.get_editor_property('blend_mode')!=expected:error('material',row['id'],'blend mode differs')
    root=unreal.MaterialEditingLibrary.get_material_property_input_node(obj,unreal.MaterialProperty.MP_BASE_COLOR)
    if not isinstance(root,unreal.MaterialExpressionCustom) or root.get_editor_property('code')!=row['code']:
        error('material',row['id'],'actual root DAG code differs');return
    for prop,output in [(unreal.MaterialProperty.MP_NORMAL,'OutNormal'),(unreal.MaterialProperty.MP_ROUGHNESS,'OutRoughness'),(unreal.MaterialProperty.MP_METALLIC,'OutMetallic')]:
        connected=unreal.MaterialEditingLibrary.get_material_property_input_node(obj,prop)
        name=unreal.MaterialEditingLibrary.get_material_property_input_node_output_name(obj,prop)
        if connected!=root or name!=output:error('material',row['id'],'actual material output wiring differs',output=output,actual=name)
    seen={};stack=[root]
    while stack:
        node=stack.pop()
        if not node or node.get_path_name() in seen:continue
        seen[node.get_path_name()]=node
        stack.extend(unreal.MaterialEditingLibrary.get_inputs_for_material_expression(obj,node))
    samples=[n for n in seen.values() if isinstance(n,unreal.MaterialExpressionTextureSample)]
    expected_samples={str(t['node']):t for t in row['textures']}
    found=set()
    for sample in samples:
        inputs=unreal.MaterialEditingLibrary.get_inputs_for_material_expression(obj,sample)
        coordinate=next((n for n in inputs if isinstance(n,unreal.MaterialExpressionCustom)),None)
        if coordinate is None:error('material',row['id'],'texture coordinates not explicit');continue
        source_id=coordinate.get_editor_property('description').rsplit(' ',1)[-1]
        if source_id not in expected_samples:error('material',row['id'],'unexpected texture-node ID',source_node=source_id);continue
        expected_sample=expected_samples[source_id];found.add(source_id)
        if sample.get_editor_property('texture')!=bridge.asset('Textures',expected_sample['image']):error('material',row['id'],'actual texture binding differs',source_node=source_id)
        if coordinate.get_editor_property('code')!=expected_sample['coordinate_code']:error('material',row['id'],'actual texture coordinate code differs',source_node=source_id)
    if found!=set(expected_samples):error('material',row['id'],'contributing texture-node set differs',missing=sorted(set(expected_samples)-found))

def material(row):
    obj=bridge.asset('Materials',row['id']);instance=_instance_rows[row['id']]
    if not isinstance(obj,unreal.MaterialInstanceConstant):error('material',row['id'],'material instance missing');return
    parent=bridge.asset('Materials',instance['parent'])
    if obj.get_editor_property('parent')!=parent:error('material',row['id'],'parameterized parent differs')
    if unreal.EditorAssetLibrary.get_metadata_tag(obj,'BlenderGraphSHA256')!=row['sha256']:error('material',row['id'],'source graph identity differs')
    for name,value in instance['scalars'].items():
        actual=unreal.MaterialEditingLibrary.get_material_instance_scalar_parameter_value(obj,name)
        if abs(actual-value)>max(1e-6,abs(value)*1e-6):error('material',row['id'],'numeric parameter differs',parameter=name,expected=value,actual=actual)
    for name,image in instance['textures'].items():
        if unreal.MaterialEditingLibrary.get_material_instance_texture_parameter_value(obj,name)!=bridge.asset('Textures',image):error('material',row['id'],'texture parameter differs',parameter=name)
    if instance['parent'] not in _verified_masters:
        material_graph(_master_rows[instance['parent']]);_verified_masters.add(instance['parent'])

def actor(row):
    obj=state['actor_map'].get(row['id'])
    if obj is None:error('actor',row['id'],'source object missing');return
    expected=bridge.make_transform(row);actual=obj.get_actor_transform()
    a=actual.translation;b=expected.translation
    delta=max(abs(a.x-b.x),abs(a.y-b.y),abs(a.z-b.z))
    if delta>.05:error('actor',row['id'],'world position differs',error_cm=delta)
    a=actual.scale3d;b=expected.scale3d
    if max(abs(a.x-b.x),abs(a.y-b.y),abs(a.z-b.z))>2e-5:error('actor',row['id'],'world scale differs')
    a=actual.rotation;b=expected.rotation
    rotation_delta=min(max(abs(getattr(a,k)-getattr(b,k)) for k in ['x','y','z','w']),max(abs(getattr(a,k)+getattr(b,k)) for k in ['x','y','z','w']))
    if rotation_delta>2e-5:error('actor',row['id'],'world quaternion differs',error=rotation_delta)
    if bool(obj.get_editor_property('hidden'))!=row['hidden_render']:error('actor',row['id'],'game hidden flag differs')
    if row['hidden_editor']:
        if 'Iceland_Blender_Hidden' not in [str(x) for x in obj.get_editor_property('layers')]:error('actor',row['id'],'persistent hidden layer missing')
    if row['type']=='MESH':
        component=obj.static_mesh_component
        if row['hidden_editor'] and component.get_editor_property('visible'):
            error('actor',row['id'],'source helper component visibility was not persisted')
        if component.static_mesh!=bridge.asset('Meshes',row['mesh']):error('actor',row['id'],'mesh reference differs')
        mapping=bridge.mesh_slot_map(component.static_mesh)
        for index,mid in enumerate(bridge.PLAN['object_materials'][row['id']]):
            if component.get_material(mapping[index])!=bridge.asset('Materials',mid):error('actor',row['id'],'object material override differs',slot=index)
    if row['parent']:
        if obj.get_attach_parent_actor()!=state['actor_map'].get(row['parent']):error('actor',row['id'],'parent differs')

def tick(delta):
    global _handle,_busy
    if _busy or not state.get('running'):return
    _busy=True
    try:
        start=time.time();function={'textures':texture,'meshes':mesh,'materials':material,'actors':actor}[state['phase']]
        while state['cursor']<len(rows) and time.time()-start<.2:
            row=rows[state['cursor']];state['current']=row['id'];function(row);state['cursor']+=1
        if state['cursor']>=len(rows):
            state['running']=False;state['complete']=True
            unreal.unregister_slate_post_tick_callback(_handle);_handle=None
        persist()
    except Exception:
        state['running']=False;state['exception']=traceback.format_exc();persist();unreal.log_error(state['exception'])
        unreal.unregister_slate_post_tick_callback(_handle);_handle=None
    finally:_busy=False

def start(phase):
    global state,rows,_handle
    if state.get('running'):raise RuntimeError('Validation already active')
    rows={'textures':bridge.MANIFEST['images'],'meshes':bridge.MANIFEST['meshes'],'materials':bridge.PLAN['materials'],'actors':bridge.MANIFEST['objects']}[phase]
    state={'phase':phase,'cursor':0,'total':len(rows),'running':True,'errors':[],'started':time.time()}
    if phase=='actors':
        actors=bridge.find_actors();expected={r['id'] for r in rows}
        state['actor_map']=actors
        if set(actors)!=expected:error('actor','all','source object ID set differs',missing=sorted(expected-set(actors)),unexpected=sorted(set(actors)-expected))
    persist();_handle=unreal.register_slate_post_tick_callback(tick)
    return {'phase':phase,'total':len(rows)}

# UObject values in actor_map cannot be serialized; keep them outside reports.
_persist_plain=persist
def persist():
    actors=state.pop('actor_map',None)
    try:_persist_plain()
    finally:
        if actors is not None:state['actor_map']=actors
