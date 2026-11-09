"""Render the selected imported level with UE's native lit viewport and lights.

Run through -ExecCmds (editor ticks stay alive), without -nullrhi. The preview
uses the actual UE renderer, materials, shadows, GI and tone mapping.
"""
import json
import math
import os
from pathlib import Path
import statistics
import time
import traceback
import unreal

ROOT = Path(os.environ['ATLASMAP_SOURCE_ROOT'])
LEVEL = os.environ['ATLASMAP_UE_LEVEL']
RUN_ID = os.environ.get('ATLASMAP_RENDER_RUN_ID', '')
IMAGE = ROOT / 'render_preview.png'
RESULT = ROOT / 'render_report.json'
STATE = {'started': time.monotonic(), 'frames': 0, 'task': None, 'handle': None, 'busy': False}


def finish(error=None):
    if STATE['handle'] is not None:
        unreal.unregister_slate_post_tick_callback(STATE['handle'])
        STATE['handle'] = None
    report = {'complete': error is None, 'error': error, 'level': LEVEL,
              'run_id': RUN_ID, 'image': str(IMAGE), 'renderer': 'Unreal Engine native lit viewport',
              'engine': unreal.SystemLibrary.get_engine_version(),
              'lighting_mode': os.environ.get('ATLASMAP_LIGHTING_MODE', 'source'),
              'seconds': time.monotonic()-STATE['started'], 'frames': STATE['frames']}
    report['camera'] = STATE.get('camera')
    report['preview_exposure_compensation_ev']=float(os.environ.get('ATLASMAP_RENDER_EV','0'))
    report['render_profile']=os.environ.get('ATLASMAP_RENDER_PROFILE','game')
    RESULT.write_text(json.dumps(report, indent=2), encoding='utf-8')
    unreal.log('[render] ' + json.dumps(report))
    unreal.SystemLibrary.quit_editor()


def tick(_delta):
    # Screenshot setup flushes shader compilation and pumps Slate recursively.
    if STATE['busy']:
        return
    try:
        STATE['frames'] += 1
        elapsed = time.monotonic()-STATE['started']
        if elapsed > 600:
            raise RuntimeError('Native renderer timed out before completing the image')
        if STATE['task'] is None and elapsed >= 8 and STATE['frames'] >= 60:
            STATE['busy'] = True
            STATE['capture_started'] = time.time()
            STATE['task'] = unreal.AutomationLibrary.take_high_res_screenshot(1600, 900, str(IMAGE),camera=STATE.get('camera_actor'))
            STATE['busy'] = False
        elif STATE['task'] is not None and STATE['task'].is_task_done():
            if (not IMAGE.is_file() or IMAGE.stat().st_size < 1000
                    or IMAGE.stat().st_mtime < STATE['capture_started']-1):
                raise RuntimeError('UE screenshot task did not produce the requested image')
            finish()
    except Exception:
        finish(traceback.format_exc())


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(LEVEL):
        raise RuntimeError('Cannot load selected level: ' + LEVEL)
    import ue_ensure_lighting
    ue_ensure_lighting.main()
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    geometry = [a for a in eas.get_all_level_actors() if isinstance(a, unreal.StaticMeshActor)
                and not a.is_hidden_ed() and 'sky' not in a.get_actor_label().lower()]
    if not geometry:
        raise RuntimeError('Selected level has no visible static mesh geometry')
    low = [float('inf')]*3
    high = [-float('inf')]*3
    for actor in geometry:
        center, extent = actor.get_actor_bounds(False)
        for i, axis in enumerate(('x','y','z')):
            low[i] = min(low[i], getattr(center, axis)-getattr(extent, axis))
            high[i] = max(high[i], getattr(center, axis)+getattr(extent, axis))
    center = [(a+b)/2 for a,b in zip(low,high)]
    span = max(max(b-a for a,b in zip(low,high)), 100)
    view = os.environ.get('ATLASMAP_RENDER_VIEW', 'auto')
    data=json.loads((ROOT/('render_state.json' if (ROOT/'render_state.json').is_file() else 'lights.json')).read_text(encoding='utf-8-sig'))
    source = list(__import__('map_lighting').records(data))
    local = [r for _,r in source if r['type'] in ('Point','Spot','Rect')
             and float(r.get('intensity',0)) > 0 and float(r.get('radius',0)) > 0]
    has_sun = any(r['type']=='Directional' and float(r.get('intensity',0)) > 0 for _,r in source)
    authored=data.get('cameras',[])
    if view=='auto' and authored:
        source_camera=next((c for c in authored if 'Main' in c.get('actor','')),authored[0])
        roll,pitch,yaw=source_camera['rot']
        camera=unreal.Vector(*source_camera['loc'])
        rotation=unreal.Rotator(pitch=pitch,yaw=yaw,roll=roll)
        key=ue_ensure_lighting.TAG+ue_ensure_lighting.camera_key(source_camera)
        camera_actor=next((a for a in eas.get_all_level_actors() if key in {str(t) for t in a.tags}),None)
        if camera_actor is None:camera_actor=eas.spawn_actor_from_class(unreal.CameraActor,camera,rotation)
        camera_actor.camera_component.set_field_of_view(float(source_camera['fov']))
        STATE['camera_actor']=camera_actor
        STATE['camera']='source game camera: '+source_camera.get('actor','')
    elif local and (view == 'lights' or (view == 'auto' and not has_sun)):
        median = [statistics.median(r['loc'][i] for r in local) for i in range(3)]
        focus = min(local,key=lambda r:sum((r['loc'][i]-median[i])**2 for i in range(3)))
        yaw = focus['rot'][2]
        angle = math.radians(yaw)
        location = focus['loc']
        camera = unreal.Vector(location[0]+35*math.cos(angle),location[1]+35*math.sin(angle),location[2]-80)
        rotation = unreal.Rotator(pitch=-20,yaw=yaw,roll=0)
        STATE['camera'] = 'source light area'
    else:
        camera = unreal.Vector(center[0]-span*.9, center[1]-span*.9, center[2]+span*.65)
        rotation = unreal.Rotator(pitch=-27,yaw=45,roll=0)
        STATE['camera'] = 'map overview'
    ev=float(os.environ.get('ATLASMAP_RENDER_EV','0'))
    if ev:
        if 'camera_actor' not in STATE:
            STATE['camera_actor']=eas.spawn_actor_from_class(unreal.CameraActor,camera,rotation)
        component=STATE['camera_actor'].camera_component
        settings=component.get_editor_property('post_process_settings')
        from map_game_lighting import build_profile
        profile=build_profile(data,ROOT,os.environ.get('ATLASMAP_RENDER_PROFILE','game'))
        base=float(settings.get_editor_property('auto_exposure_bias')) if settings.get_editor_property('override_auto_exposure_bias') else (profile.get('exposure_bias_ev') or 0)
        settings.set_editor_property('override_auto_exposure_bias',True)
        settings.set_editor_property('auto_exposure_bias',base+ev)
        component.set_editor_property('post_process_settings',settings)
        component.set_editor_property('post_process_blend_weight',1.0)
    unreal.EditorLevelLibrary.set_level_viewport_camera_info(camera, rotation)
    unreal.EditorLevelLibrary.editor_set_game_view(True)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    unreal.SystemLibrary.execute_console_command(world, 'viewmode lit')
    STATE['handle'] = unreal.register_slate_post_tick_callback(tick)
    unreal.log('[render] Native UE view warming up for ' + LEVEL)


try:
    main()
except Exception:
    finish(traceback.format_exc())
