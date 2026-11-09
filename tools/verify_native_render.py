"""Build an isolated UE fixture and exercise the shipped native render path."""
import json
import os
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from core.ue_pipeline import render_step

OUT = BASE / 'work/map-render-20261101'
PROJECT = OUT / 'UEProof/UEProof.uproject'
SOURCE = OUT / 'ProofSource'
ENGINE = Path('E:/UE_5.4/Engine/Binaries/Win64/UnrealEditor.exe')


def run():
    PROJECT.parent.joinpath('Config').mkdir(parents=True, exist_ok=True)
    SOURCE.mkdir(parents=True, exist_ok=True)
    PROJECT.write_text(json.dumps({'FileVersion':3, 'EngineAssociation':'5.4', 'Plugins':[
        {'Name':'PythonScriptPlugin','Enabled':True},
        {'Name':'EditorScriptingUtilities','Enabled':True}]}), encoding='utf-8')
    PROJECT.parent.joinpath('Config/DefaultEngine.ini').write_text(
        '[/Script/Engine.RendererSettings]\nr.DynamicGlobalIlluminationMethod=1\n'
        'r.ReflectionMethod=1\nr.GenerateMeshDistanceFields=True\n', encoding='utf-8')
    lights = [
        {'Type':'Directional','Name':'Sun','Loc':[0,0,400], 'Rot':[0,-45,25],
         'Intensity':3, 'Color':[1,.85,.65], 'CastShadows':True},
        {'Type':'Point','Name':'Red','Loc':[-200,-150,160], 'Rot':[0,0,0],
         'Intensity':3000, 'Color':[1,.03,.01], 'Radius':900, 'CastShadows':True},
        {'Type':'Spot','Name':'Blue','Loc':[200,100,350], 'Rot':[0,-80,0],
         'Intensity':5000, 'Color':[.03,.1,1], 'Radius':1200, 'InnerCone':20,'OuterCone':40},
        {'Type':'Rect','Name':'Panel','Loc':[0,300,240], 'Rot':[0,-25,-90],
         'Intensity':1000,'Color':[.1,1,.2], 'Radius':800,'SourceWidth':150,'SourceHeight':80},
        {'Type':'Point','Name':'Off','Loc':[0,0,100], 'Rot':[7,8,9],
         'Intensity':0,'Color':[1,1,1], 'Radius':0},
        {'Type':'Sky','Name':'Ambient','Loc':[0,0,400], 'Rot':[0,0,0],
         'Intensity':.4,'Color':[.3,.4,.5], 'Radius':0},
        {'Type':'Fog','Name':'Fog','Loc':[0,0,-800], 'Rot':[0,0,0], 'Radius':0},
    ]
    SOURCE.joinpath('lights.json').write_text(json.dumps({'lights':lights}), encoding='utf-8')
    SOURCE.joinpath('scene.json').write_text('{"instances":[{"loc":[0,0,0]}]}', encoding='utf-8')
    setup = OUT / 'setup_native_proof.py'
    setup.write_text('''import json, os, sys, traceback
from pathlib import Path
import unreal
root = Path(os.environ['ATLASMAP_SOURCE_ROOT'])
try:
    sys.path.insert(0, os.environ['ATLASMAP_SCRIPTS'])
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    level = os.environ['ATLASMAP_UE_LEVEL']
    if unreal.EditorAssetLibrary.does_asset_exist(level):
        assert les.load_level(level)
    else:
        assert les.new_level(level)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for old in eas.get_all_level_actors():
        if isinstance(old, (unreal.StaticMeshActor, unreal.Light)):
            eas.destroy_actor(old)
    cube = unreal.load_asset('/Engine/BasicShapes/Cube.Cube')
    for label, pos, scale in [('Floor',[0,0,-25],[12,12,.5]),
                              ('Block',[0,0,100],[2,2,2]),
                              ('Column',[250,-120,130],[1,1,2.6])]:
        actor = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*pos))
        actor.set_actor_label(label)
        actor.static_mesh_component.set_static_mesh(cube)
        actor.set_actor_scale3d(unreal.Vector(*scale))
    import ue_ensure_lighting
    report = ue_ensure_lighting.main()
    assert report['complete'] and not report['fallback']
    assert report['restored'] == {'Directional':1, 'Point':2, 'Spot':1, 'Rect':1, 'Sky':1, 'Fog':1}
    def source_actors():
        return [a for a in eas.get_all_level_actors() if any(str(t).startswith('AtlasMapLighting_') for t in a.tags)]
    assert len(source_actors()) == 7
    off = next(a for a in source_actors() if a.get_actor_label().endswith(' Off'))
    assert off.light_component.intensity == 0 and off.light_component.attenuation_radius == 0
    red = next(a for a in source_actors() if a.get_actor_label().endswith(' Red'))
    rgb = red.light_component.get_light_color()
    assert abs(rgb.r-1) < .02 and abs(rgb.g-.03) < .02
    data = json.loads((root/'lights.json').read_text())
    data['lights'][1]['Loc'] = [-210,-160,170]
    (root/'lights.json').write_text(json.dumps(data))
    ue_ensure_lighting.main()
    assert len(source_actors()) == 7
    v = red.get_actor_location()
    assert abs(v.x+210)<.01 and abs(v.y+160)<.01 and abs(v.z-170)<.01
    (root/'native_light_checks.json').write_text(json.dumps({'complete':True,'actor_count':7,
        'zero_preserved':True,'linear_color_preserved':True,'updates_in_place':True,'fallback':report['fallback']}))
except Exception:
    (root/'native_light_checks.json').write_text(json.dumps({'complete':False,'error':traceback.format_exc()}))
    raise
''', encoding='utf-8')
    env = os.environ.copy()
    env.update(ATLASMAP_SOURCE_ROOT=str(SOURCE), ATLASMAP_UE_LEVEL='/Game/AtlasMapRenderProof/LV_Map',
               ATLASMAP_SCRIPTS=str(BASE/'scripts/official'), ATLASMAP_UE_NO_RENDER='1')
    if '--render-only' not in sys.argv:
        with (OUT/'native-setup.log').open('w', encoding='utf-8') as log:
            result = subprocess.run([str(ENGINE.with_name('UnrealEditor-Cmd.exe')),str(PROJECT),
                '-ExecutePythonScript='+str(setup),'-nullrhi','-unattended','-nosplash','-nosound',
                '-SCCProvider=None','-nop4','-stdout','-UTF8Output'], env=env,
                stdout=log,stderr=subprocess.STDOUT,creationflags=0x08000000,timeout=300)
        checks = json.loads((SOURCE/'native_light_checks.json').read_text())
        print('NATIVE LIGHTS', checks, flush=True)
        assert result.returncode == 0 and checks['complete'], result.returncode
    step = render_step({'engine':str(ENGINE),'project':str(PROJECT), 'root':str(SOURCE),
                        'dest':'/Game/AtlasMapRenderProof','scripts':str(BASE/'scripts/official')})
    env = os.environ.copy()
    env.update(step.env)
    import time
    started = time.time()
    with (OUT/'native-render.log').open('w', encoding='utf-8') as log:
        result = subprocess.run(step.cmd,env=env,stdout=log,stderr=subprocess.STDOUT,
                                creationflags=0x08000000,timeout=360)
    print('RENDER EXIT', result.returncode, flush=True)
    assert result.returncode == 0
    step.validate(started)
    print((SOURCE/'render_report.json').read_text(), flush=True)


if __name__ == '__main__':
    run()
