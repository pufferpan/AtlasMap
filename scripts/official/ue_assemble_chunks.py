"""Save one persistent map that always loads the independently completed chunks."""
import json
import os
from pathlib import Path
import traceback

import unreal
import sys
sys.path.insert(0,str(Path(__file__).parent))

ROOT=Path(os.environ['ATLASMAP_UE_ROOT'])
SOURCE=Path(os.environ['ATLASMAP_SOURCE_ROOT'])
LEVEL=os.environ['ATLASMAP_UE_LEVEL']
RUN_ID=os.environ['ATLASMAP_UE_RUN_ID']
RESULT=ROOT/'ue_import_result.json'


def main():
    RESULT.write_text(json.dumps(dict(complete=False,level=LEVEL,run_id=RUN_ID)),encoding='utf-8')
    from ue_headless_renderer import check_headless_renderer
    check_headless_renderer(unreal)
    index=json.loads((ROOT/'chunks/index.json').read_text(encoding='utf-8'))
    if not index.get('complete') or index['run_id']!=RUN_ID:
        raise ValueError('Chunk catalogue belongs to a different export')
    registry=unreal.AssetRegistryHelpers.get_asset_registry()
    registry.scan_paths_synchronous([os.environ['ATLASMAP_UE_DEST']],True)
    # This file is the exporter's generated persistent map. Recreate it so
    # reruns cannot retain old flat actors or stale streaming-level entries.
    world=unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    if world is None:raise RuntimeError('Cannot create persistent map')
    chunks=index['chunks']
    for chunk in chunks:
        streaming=unreal.EditorLevelUtils.add_level_to_world(world,chunk['level'],unreal.LevelStreamingAlwaysLoaded)
        if streaming is None:raise RuntimeError('Cannot load chunk: '+chunk['level'])
        streaming.set_editor_property('should_be_loaded',True)
        streaming.set_editor_property('should_be_visible',True)
        loaded=streaming.get_loaded_level()
        if loaded is None:raise RuntimeError('Chunk did not load: '+chunk['level'])
        unreal.EditorLevelUtils.set_level_visibility(loaded,True,False)
    if not unreal.EditorLoadingAndSavingUtils.save_map(world,LEVEL):
        raise RuntimeError('Cannot save persistent map')
    # Reopen saved data and check actual actor membership, transforms and
    # material slots, rather than trusting process exit codes or receipts.
    les=unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):raise RuntimeError('Cannot reopen persistent map')
    actors=unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    tagged=[actor for actor in actors if any(str(tag).startswith('IcelandBlenderId_') for tag in actor.tags)]
    by_id={str(tag).removeprefix('IcelandBlenderId_'):actor for actor in actors for tag in actor.tags
           if str(tag).startswith('IcelandBlenderId_')}
    expected=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    if len(tagged)!=len(by_id) or set(by_id)!={row['id'] for row in expected['objects']}:
        raise ValueError(f'Saved chunk coverage differs: {len(by_id)} != {len(expected["objects"])}')
    references={}
    hidden_proxies=set()
    for chunk in chunks:
        manifest_path=Path(chunk['manifest'])
        local=json.loads(manifest_path.read_text(encoding='utf-8'))
        plan=json.loads((manifest_path.parent/'material_plan.json').read_text(encoding='utf-8'))
        lod_report=json.loads((manifest_path.parent/'lod_report.json').read_text(encoding='utf-8'))
        if not lod_report.get('complete'):raise ValueError('Incomplete HLOD visibility report')
        hidden_proxies.update(row['object_id'] for row in lod_report['objects'])
        for row in local['objects']:
            references[row['id']]=(chunk['asset_destination'],plan['object_materials'].get(row['id'],[]))
    slot_count=0
    for row in expected['objects']:
        actor=by_id[row['id']]
        pose=row['ue_matrix']
        position=actor.get_actor_location()
        # Serialized matrices are row-major; source coordinates are centimetres.
        if max(abs(v-pose[j][3]) for j,v in enumerate((position.x,position.y,position.z)))>.05:
            raise ValueError('Saved actor moved: '+row['id'])
        if row.get('parent') and actor.get_attach_parent_actor()!=by_id[row['parent']]:
            raise ValueError('Saved parent changed: '+row['id'])
        if row['type']=='MESH':
            component=actor.static_mesh_component
            if row['id'] in hidden_proxies and (not actor.get_editor_property('hidden') or component.is_visible()):
                raise ValueError('Saved duplicate HLOD remained visible: '+row['id'])
            if component.static_mesh is None:raise ValueError('Saved mesh missing')
            asset_root,mids=references[row['id']]
            if component.static_mesh.get_path_name().split('.')[0]!=asset_root+'/Meshes/'+row['mesh']:
                raise ValueError('Saved mesh reference changed: '+row['id'])
            for slot,mid in enumerate(mids):
                actual=component.get_material(slot)
                if mid and (actual is None or actual.get_path_name().split('.')[0]!=asset_root+'/Materials/'+mid):
                    raise ValueError('Saved material reference changed: '+row['id'])
                slot_count+=1
    light_reports=[json.loads((Path(chunk['blend']).parent/'lighting_report.json').read_text(encoding='utf-8')) for chunk in chunks]
    restored={}
    for report in light_reports:
        for kind,value in report['restored'].items():restored[kind]=restored.get(kind,0)+value
    state=json.loads((SOURCE/'render_state.json').read_text(encoding='utf-8'))
    if sum(restored.values())!=len(state['lights']):raise ValueError('Source lights missing from chunks')
    from map_lighting import records
    expected_light_tags={'AtlasMapLighting_'+key for key,row in records(state)}
    saved_lights=[actor for actor in actors if any(str(tag) in expected_light_tags for tag in actor.tags)]
    actual_light_tags={str(tag) for actor in saved_lights for tag in actor.tags if str(tag) in expected_light_tags}
    if len(saved_lights)!=len(state['lights']) or actual_light_tags!=expected_light_tags:
        raise ValueError('Saved light identity coverage differs from source')
    cameras=[actor for actor in actors if any(str(tag).startswith('AtlasMapLighting_camera_') for tag in actor.tags)]
    if len(cameras)!=len(state.get('cameras',[])):raise ValueError('Source cameras missing from chunks')
    profiles=[actor for actor in actors if any(str(tag)=='AtlasMapLighting_game_profile' for tag in actor.tags)]
    profile_expected=any(report.get('game_profile',{}).get('enabled') for report in light_reports)
    if len(profiles)!=int(profile_expected):raise ValueError('Global lighting profile missing or duplicated')
    result=dict(complete=True,level=LEVEL,run_id=RUN_ID,streaming=True,chunks=len(chunks),
                objects=len(by_id),material_slots=slot_count,source_lights=sum(restored.values()),
                source_cameras=len(cameras),global_profiles=len(profiles))
    result['suppressed_hlod_proxies']=len(hidden_proxies)
    environments=[r['source_environment'] for r in light_reports if r.get('source_environment')]
    environment=dict(source_reflections=len(state.get('reflection_captures',[])),
        restored=[row for report in environments for row in report.get('restored',[])],
        unsupported=[row for report in environments for row in report.get('unsupported',[])],
        sky=next((r['sky'] for r in environments if r.get('sky') is not None),None))
    planned={row['guid'] for row in environment['restored']}
    saved=[actor for actor in actors if any(str(t).startswith('AtlasMapEnvironment_reflection_') for t in actor.tags)]
    saved_guids={str(t).removeprefix('AtlasMapEnvironment_reflection_') for actor in saved for t in actor.tags if str(t).startswith('AtlasMapEnvironment_reflection_')}
    if len(saved)!=len(planned) or saved_guids!=planned:raise ValueError('Saved source HDR reflection coverage differs')
    result['source_hdr_reflections']=len(saved)
    RESULT.write_text(json.dumps(result,indent=2),encoding='utf-8')
    for file,extra in (('lighting_report.json',dict(source_count=len(state['lights']),restored=restored,source_environment=environment)),
                       ('collision_report.json',dict(chunks=len(chunks)))):
        (SOURCE/file).write_text(json.dumps(dict(result,**extra),indent=2),encoding='utf-8')
    unreal.log('All complete chunks reopened and verified: '+json.dumps(result))


try:
    main()
except Exception:
    RESULT.write_text(json.dumps(dict(complete=False,level=LEVEL,run_id=RUN_ID,error=traceback.format_exc())),encoding='utf-8')
    raise
