"""Representative collision queries and timed PIE character landing probes."""
import json,time,traceback,math
from pathlib import Path
import unreal
import ue_iceland_bridge as bridge

ROOT=Path('D:/AtlasMap-tooling/out/Iceland/collision_rebuild/20261031')
SAMPLES=[('terrain','O_19654f6e744396f02bf8'),('road02','O_d1d7255df6e514f2621f'),
 ('road01','O_e9e72804dcac9974917c'),('red_factory',None),
 ('cliff',None),('container','O_f7ccb7b3256798b55af1'),
 ('radar','O_f45b6545fbd8952cf74e'),('stairs','O_614473c67eadbc15bb4a'),('sandbags','O_cef2136947ebc3b3bbdf')]
_monitor=None
_busy=False
_started=None
_last_sample=0
_samples=[]

def get_samples():
    rows={r['id']:r for r in bridge.MANIFEST['objects']}
    out=[]
    for name,oid in SAMPLES:
        if name=='red_factory':oid=next(r['id'] for r in rows.values() if 'FactoryRed_Destruction_56F1AADB308925FCDCF522665837E' in r['name'])
        if name=='cliff':oid=next(r['id'] for r in rows.values() if r.get('mesh')=='SM_39d2df1c82629baf13dc')
        out.append((name,oid))
    return out

def query_components():
    actors=bridge.find_actors();results=[]
    for name,oid in get_samples():
        a=actors[oid];c=a.static_mesh_component;center,extent=a.get_actor_bounds(False)
        found=[]
        for axis in [2,0,1]:
            for u,v in [(0,0),(.5,0),(-.5,0),(0,.5),(0,-.5),(.65,.65),(-.65,-.65),(.65,-.65),(-.65,.65)]:
                axes=[i for i in range(3) if i!=axis];coords=[center.x,center.y,center.z];ext=[extent.x,extent.y,extent.z]
                coords[axes[0]]+=u*ext[axes[0]];coords[axes[1]]+=v*ext[axes[1]]
                start=list(coords);end=list(coords);start[axis]+=ext[axis]+500;end[axis]-=ext[axis]+500
                hit=c.line_trace_component(unreal.Vector(*start),unreal.Vector(*end),False,False,False)
                if hit:
                    p,n,bone,raw=hit
                    found.append({'axis':axis,'point':[p.x,p.y,p.z],'normal':[n.x,n.y,n.z]})
                    if len(found)>=3:break
            if len(found)>=3:break
        results.append({'category':name,'id':oid,'actor':a.get_actor_label(),'simple_query_hits':found,'passed':bool(found)})
    (ROOT/'component_trace_validation.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    return results

def create_landing_probes():
    sub=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    w=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    actors=bridge.find_actors();results=[]
    for category,oid in get_samples():
        if category not in ['terrain','road02','red_factory','container','stairs']:continue
        a=actors[oid];center,extent=a.get_actor_bounds(False)
        candidates=[]
        if category=='terrain':
            # Independent open ground near the industrial area, avoiding the sea.
            candidates=[(220000,-190000),(210000,-190000),(190000,-195000)]
        else:candidates=[(center.x+u*extent.x,center.y+v*extent.y) for u,v in [(0,0),(.5,0),(-.5,0),(0,.5),(0,-.5),(.65,.65),(-.65,-.65)]]
        chosen=None
        for x,y in candidates:
            hit=unreal.SystemLibrary.line_trace_single(w,unreal.Vector(x,y,center.z+extent.z+10000),unreal.Vector(x,y,center.z-extent.z-10000),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,False,[],unreal.DrawDebugTrace.NONE)
            if not hit:continue
            data=hit.to_tuple();normal=data[7];point=data[5]
            if normal.z<.85:continue
            if category!='terrain' and data[9]!=a:continue
            # Check character capsule fits without starting inside a side wall.
            p=sub.spawn_actor_from_class(unreal.Character,unreal.Vector(point.x,point.y,point.z+300))
            if not p:continue
            p.set_actor_label('Iceland Collision QA '+category);p.tags=[unreal.Name('IcelandCollisionQA')]
            move=p.character_movement;move.set_editor_property('run_physics_with_no_controller',True)
            move.set_editor_property('max_walk_speed',100.0)
            move.set_movement_mode(unreal.MovementMode.MOVE_FALLING)
            p.set_actor_hidden_in_game(True)
            half=p.capsule_component.get_scaled_capsule_half_height();radius=p.capsule_component.get_scaled_capsule_radius()
            capsule_hit=unreal.SystemLibrary.capsule_trace_single(w,unreal.Vector(point.x,point.y,point.z+300),unreal.Vector(point.x,point.y,point.z-1000),radius,half,unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,False,[p],unreal.DrawDebugTrace.NONE)
            expected_z=capsule_hit.to_tuple()[4].z if capsule_hit else point.z+half
            chosen={'category':category,'label':p.get_actor_label(),'spawn':[point.x,point.y,point.z+300],'surface_z':point.z,'capsule_half_height':half,'capsule_radius':radius,'expected_capsule_support_z':expected_z,'surface_actor':data[9].get_actor_label() if data[9] else None}
            break
        results.append(chosen or {'category':category,'error':'No suitable horizontal support point'})
    (ROOT/'landing_probe_setup.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    return results

def monitor_tick(dt):
    global _busy,_started,_last_sample
    if _busy:return
    _busy=True
    try:
        worlds=unreal.EditorLevelLibrary.get_pie_worlds(False)
        if not worlds:return
        now=time.time()
        if _started is None:_started=now
        if now-_last_sample<.2:return
        _last_sample=now
        for w in worlds:
            for a in unreal.GameplayStatics.get_all_actors_of_class(w,unreal.Character):
                if 'IcelandCollisionQA' not in [str(t) for t in a.tags]:continue
                p=a.get_actor_location();move=a.character_movement
                if a.get_actor_label()=='Iceland Collision QA road02' and 1.5<now-_started<3.5:
                    a.add_movement_input(unreal.Vector(1,0,0),1.0,True)
                _samples.append({'time':now-_started,'label':a.get_actor_label(),'position':[p.x,p.y,p.z],
                                 'on_ground':move.is_moving_on_ground(),'movement_mode':str(move.get_editor_property('movement_mode')),'velocity_z':move.velocity.z})
        (ROOT/'landing_probe_samples.json').write_text(json.dumps(_samples,ensure_ascii=False,indent=2),encoding='utf-8')
    except Exception:
        (ROOT/'landing_probe_error.txt').write_text(traceback.format_exc(),encoding='utf-8')
    finally:_busy=False

def start_monitor():
    global _monitor,_started,_last_sample,_samples
    _started=None;_last_sample=0;_samples=[]
    if _monitor:unreal.unregister_slate_post_tick_callback(_monitor)
    _monitor=unreal.register_slate_post_tick_callback(monitor_tick)
    return {'monitoring':True}

def finish_monitor():
    global _monitor
    if _monitor:unreal.unregister_slate_post_tick_callback(_monitor);_monitor=None
    setup=json.loads((ROOT/'landing_probe_setup.json').read_text(encoding='utf-8'));results=[]
    for row in setup:
        samples=[s for s in _samples if s['label']==row.get('label')]
        end=samples[-1] if samples else None
        movement=math.sqrt(sum((end['position'][i]-row['spawn'][i])**2 for i in [0,1])) if end else 0
        results.append({**row,'sample_count':len(samples),'last':end,'horizontal_travel_cm':movement,
                        'passed':bool(end and end['on_ground'] and abs(end['velocity_z'])<1 and abs(end['position'][2]-row['expected_capsule_support_z'])<25)})
    sub=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for a in sub.get_all_level_actors():
        if 'IcelandCollisionQA' in [str(t) for t in a.tags]:sub.destroy_actor(a)
    (ROOT/'landing_probe_validation.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    return results
