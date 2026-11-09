"""Resumable static scene collision, with source-backed hidden blockers only.

Complex-as-simple supports character/simple scene queries on the exact static
surface. It does not make these meshes dynamically simulated rigid bodies.
"""
import collections,json,time,traceback
from pathlib import Path
import unreal
import ue_iceland_bridge as bridge
import ue_rebuild_iceland_water as water

ROOT=Path('D:/AtlasMap-tooling/out/Iceland/collision_rebuild/20261031')
ROOT.mkdir(parents=True,exist_ok=True)
_handle=None
_busy=False
state={}
rows=[]
_actors={}
_meshsub=unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
SKY='O_ca64216549857f97184c'
WATER=set(water.WATER_IDS)|{water.PROXY,'O_e66f411a88e9aab2e5d0'}

def policy():
    p=ROOT/'source_hidden_collision_policy.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}

def classification(row):
    if row['id'] in WATER:return 'water'
    if row['id']==SKY:return 'sky'
    label=row['name'].lower()
    if row['hidden_editor'] or row['hidden_render']:return 'hidden_pending_source'
    if any(s in label for s in ['/decal/','/decals/','sm_decal','gende cal','gendecaldir']):return 'decal'
    if any(s in label for s in ['/grass/','/bush/','/plants/','/plant/','_grass_','_weed_','_bush_','_shrub_','_reed_','_flower_','_leaf_','_leaves_','_fern_','_straw_']):return 'soft_vegetation'
    return 'solid'

def prepare():
    global _actors
    world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    assert world.get_path_name().split('.')[0]==bridge.MANIFEST['level']
    _actors=bridge.find_actors()
    if not (ROOT/'before_source_objects.json').exists():
        (ROOT/'before_source_objects.json').write_text(json.dumps(water.snapshot(),ensure_ascii=False),encoding='utf-8')
    actor_rows=[];mesh_ids=set();counts=collections.Counter();before=[]
    for row in bridge.MANIFEST['objects']:
        if row['type']!='MESH':continue
        kind=classification(row);counts[kind]+=1
        actor_rows.append({'id':row['id'],'mesh':row['mesh'],'category':kind})
        if kind=='solid':mesh_ids.add(row['mesh'])
        a=_actors[row['id']];c=a.static_mesh_component
        before.append({'id':row['id'],'profile':str(c.get_collision_profile_name()),'enabled':str(c.get_collision_enabled()),'object_type':str(c.get_collision_object_type())})
    plan={'actors':actor_rows,'visible_solid_meshes':sorted(mesh_ids),'category_counts':dict(counts)}
    (ROOT/'collision_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    if not (ROOT/'before_component_collision.json').exists():(ROOT/'before_component_collision.json').write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
    return plan

def source_policy_rows():
    data=policy()
    # Match the independently audited file structure after inspection.
    if isinstance(data,list):return data
    return data.get('matched',data.get('objects',data.get('policies',[])))

def start_component_phase():
    if state.get('running'):raise RuntimeError('Mesh phase still running')
    plan=json.loads((ROOT/'collision_plan.json').read_text(encoding='utf-8'))
    audited={r['id']:r for r in source_policy_rows()}
    counts=collections.Counter();extra_meshes=set()
    for row in plan['actors']:
        source=audited.get(row['id'])
        if row['category']=='hidden_pending_source' and source:
            recommendation=source.get('recommended_policy')
            row['source_collision_policy']=recommendation
            if recommendation=='hidden_pawn_blocker_visibility_camera_ignore':row['category']='source_pawn_blocker'
            elif recommendation=='hidden_static_blocker':row['category']='solid'
            if row['category'] in ['solid','source_pawn_blocker']:extra_meshes.add(row['mesh'])
        counts[row['category']]+=1
    for mid in sorted(extra_meshes):cook_mesh({'id':mid})
    plan['applied_category_counts']=dict(counts)
    plan['audited_hidden_helpers']=len(audited)
    (ROOT/'applied_collision_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    return start_actors(plan['actors'])

def cook_mesh(row):
    mesh=bridge.asset('Meshes',row['id']);body=mesh.get_editor_property('body_setup')
    if body is None:raise RuntimeError('Missing BodySetup '+mesh.get_path_name())
    if unreal.EditorAssetLibrary.get_metadata_tag(mesh,'IcelandStaticCollisionRevision')=='exact_static_v1':
        if body.get_editor_property('collision_trace_flag')==unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE:return
    before={'id':row['id'],'asset':mesh.get_path_name(),'flag':str(body.get_editor_property('collision_trace_flag')),'double_sided':body.get_editor_property('double_sided_geometry'),
            'section_collision':[_meshsub.is_section_collision_enabled(mesh,0,i) for i in range(mesh.get_num_sections(0))]}
    mesh.modify();body.modify()
    body.set_editor_property('collision_trace_flag',unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
    body.set_editor_property('double_sided_geometry',True)
    sections=mesh.get_num_sections(0)
    for i in range(sections):
        if not _meshsub.is_section_collision_enabled(mesh,0,i):_meshsub.enable_section_collision(mesh,True,0,i)
    # EnableSectionCollision issues StaticMesh::PostEditChange, rebuilding the
    # physics state even if all section flags were already true.
    if sections:_meshsub.enable_section_collision(mesh,True,0,0)
    if _meshsub.get_collision_complexity(mesh)!=unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE:raise RuntimeError('Trace flag not applied')
    bridge.metadata(mesh,'IcelandStaticCollisionRevision','exact_static_v1')
    bridge.metadata(mesh,'IcelandCollisionBefore',json.dumps(before))
    bridge.save(mesh)

def configure_actor(row):
    a=_actors[row['id']];c=a.static_mesh_component;kind=row['category']
    c.modify()
    if kind=='solid':
        c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
        c.set_collision_object_type(unreal.CollisionChannel.ECC_WORLD_STATIC)
        c.set_collision_profile_name('BlockAll')
        c.set_collision_enabled(unreal.CollisionEnabled.QUERY_AND_PHYSICS)
    elif kind=='source_pawn_blocker':
        c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
        c.set_collision_profile_name('Custom')
        c.set_collision_response_to_all_channels(unreal.CollisionResponseType.ECR_IGNORE)
        c.set_collision_response_to_channel(unreal.CollisionChannel.ECC_PAWN,unreal.CollisionResponseType.ECR_BLOCK)
        c.set_collision_object_type(unreal.CollisionChannel.ECC_WORLD_STATIC)
        c.set_collision_enabled(unreal.CollisionEnabled.QUERY_AND_PHYSICS)
    else:
        # A mismatched enabled flag under the old BlockAll profile is replaced
        # by profile defaults on load. Persist the NoCollision profile itself.
        c.set_collision_profile_name('NoCollision')
        c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)

def persist():
    state['updated']=time.time()
    (ROOT/'collision_status.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')

def _tick(dt):
    global _busy,_handle
    if _busy or not state.get('running'):return
    _busy=True
    try:
        begin=time.time()
        while state['cursor']<len(rows) and time.time()-begin<.18:
            row=rows[state['cursor']];state['current']=row['id']
            (cook_mesh if state['phase']=='meshes' else configure_actor)(row)
            state['cursor']+=1;persist()
        if state['cursor']==len(rows):
            state['running']=False;state['complete']=True;persist()
            unreal.unregister_slate_post_tick_callback(_handle);_handle=None
    except Exception:
        state['running']=False;state['error']=traceback.format_exc();persist();unreal.log_error(state['error'])
        if _handle:unreal.unregister_slate_post_tick_callback(_handle);_handle=None
    finally:_busy=False

def start_meshes(start_index=0):
    global state,rows,_handle,_actors
    if state.get('running'):raise RuntimeError('Already running')
    plan=prepare();ids=set(plan['visible_solid_meshes'])
    rows=[{'id':mid} for mid in ids]
    priority=['SM_'+bridge.MESHES[next(r['mesh'] for r in bridge.MANIFEST['objects'] if r['id']=='O_19654f6e744396f02bf8')]['id'].removeprefix('SM_')]
    rows.sort(key=lambda r:(r['id'] not in priority,-bridge.MESHES[r['id']]['triangles']))
    state={'phase':'meshes','cursor':start_index,'total':len(rows),'running':True,'complete':False,'started':time.time()}
    persist();_handle=unreal.register_slate_post_tick_callback(_tick);return dict(state)

def start_actors(actor_rows):
    global state,rows,_handle,_actors
    if state.get('running'):raise RuntimeError('Already running')
    _actors=bridge.find_actors();rows=actor_rows
    state={'phase':'actors','cursor':0,'total':len(rows),'running':True,'complete':False,'started':time.time()}
    persist();_handle=unreal.register_slate_post_tick_callback(_tick);return dict(state)

def status():return dict(state)
