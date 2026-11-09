"""Saved-state collision readback and scene preservation validation."""
import json,collections
import unreal
import ue_rebuild_iceland_collision as collision
import ue_verify_iceland_collision as verify
import ue_rebuild_iceland_water as water

ROOT=collision.ROOT
plan=json.loads((ROOT/'applied_collision_plan.json').read_text(encoding='utf-8'))
before=json.loads((ROOT/'before_source_objects.json').read_text(encoding='utf-8'))
now=water.snapshot();actors=collision.bridge.find_actors();errors=[]
def check(ok,reason,**detail):
    if not ok:errors.append({'reason':reason,**detail})
check(set(now)==set(before),'source object set changed')
for oid,row in now.items():
    for name,value in row.items():
        old=before[oid][name]
        if name in ['location','rotation','scale']:check(max(abs(a-b) for a,b in zip(value,old))<1e-5,'transform changed',id=oid,field=name)
        else:check(value==old,'render/material/name state changed',id=oid,field=name)
ss=unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
mesh_ids=set();counts=collections.Counter()
for row in plan['actors']:
    c=actors[row['id']].static_mesh_component;kind=row['category'];counts[kind]+=1
    if kind in ['solid','source_pawn_blocker']:
        check(c.get_collision_enabled()==unreal.CollisionEnabled.QUERY_AND_PHYSICS,'solid collision not enabled',id=row['id'])
        check(c.get_collision_object_type()==unreal.CollisionChannel.ECC_WORLD_STATIC,'solid object type differs',id=row['id'])
        mesh_ids.add(row['mesh'])
        check(c.get_collision_response_to_channel(unreal.CollisionChannel.ECC_PAWN)==unreal.CollisionResponseType.ECR_BLOCK,'Pawn is not blocked',id=row['id'])
        if kind=='source_pawn_blocker':
            for channel in [unreal.CollisionChannel.ECC_VISIBILITY,unreal.CollisionChannel.ECC_CAMERA]:
                check(c.get_collision_response_to_channel(channel)==unreal.CollisionResponseType.ECR_IGNORE,'hidden Pawn blocker incorrectly blocks camera/visibility',id=row['id'])
        else:check(str(c.get_collision_profile_name())=='BlockAll','solid profile differs',id=row['id'])
    else:check(c.get_collision_enabled()==unreal.CollisionEnabled.NO_COLLISION,'visual/hidden non-blocker collision enabled',id=row['id'],category=kind)
for mid in mesh_ids:
    m=collision.bridge.asset('Meshes',mid);b=m.get_editor_property('body_setup')
    check(ss.get_collision_complexity(m)==unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE,'static mesh collision complexity differs',mesh=mid)
    check(b.get_editor_property('double_sided_geometry'),'thin surface collision not double sided',mesh=mid)
    for section in range(m.get_num_sections(0)):check(ss.is_section_collision_enabled(m,0,section),'collision section disabled',mesh=mid,section=section)
for r in verify.query_components():check(r['passed'],'representative simple component query missed',sample=r['category'])
landing=json.loads((ROOT/'landing_probe_validation.json').read_text(encoding='utf-8'))
for r in landing:check(r['passed'],'PIE character landing failed',sample=r['category'])
road=next(r for r in landing if r['category']=='road02')
check(road['horizontal_travel_cm']>100,'PIE walking probe did not move on road')
qa=[a.get_actor_label() for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors() if 'IcelandCollisionQA' in [str(t) for t in a.tags]]
check(not qa,'QA characters remain',actors=qa)
output_data={'source_objects':len(now),'collision_mesh_assets':len(mesh_ids),'component_categories':dict(counts),
             'source_hidden_blockers':sum(1 for r in plan['actors'] if r.get('source_collision_policy') in ['hidden_static_blocker','hidden_pawn_blocker_visibility_camera_ignore']),
             'source_helper_audited':plan['audited_hidden_helpers'],'representative_trace_tests':len(verify.get_samples()),
             'PIE_landing_tests_passed':sum(r['passed'] for r in landing),'PIE_road_walk_cm':road['horizontal_travel_cm'],
             'errors':errors,'complete':True}
(ROOT/'final_collision_validation.json').write_text(json.dumps(output_data,ensure_ascii=False,indent=2),encoding='utf-8')
