"""Validate actual source units, fog-only masks, fog and bounded PP in UE."""
import json
import os
from pathlib import Path
import subprocess

BASE=Path(__file__).resolve().parents[1]
OUT=BASE/'work/export-rebuild-20261101'
script=OUT/'check_source_ue.py'
script.write_text('''import os,sys,json,traceback
from pathlib import Path
import unreal
root=Path(os.environ['ATLASMAP_SOURCE_ROOT'])
sys.path.insert(0,os.environ['ATLASMAP_SCRIPTS'])
try:
    import ue_ensure_lighting
    from map_lighting import records
    report=ue_ensure_lighting.main()
    data=json.loads((root/'render_state.json').read_text())
    eas=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors={str(t):a for a in eas.get_all_level_actors() for t in a.tags}
    checked=0
    for key,row in records(data):
        actor=actors['AtlasMapLighting_'+key]
        if row['type']=='Fog':
            c=actor.get_component_by_class(unreal.ExponentialHeightFogComponent)
            assert abs(c.fog_density-.004)<.00001,c.fog_density
            assert abs(c.fog_height_falloff-.7)<.00001
            assert c.volumetric_fog_distance==5000
            continue
        c=actor.get_component_by_class(unreal.LightComponent)
        if not c: continue
        if row.get('intensityunits')=='lumens':assert c.intensity_units==unreal.LightUnits.LUMENS
        assert abs(c.intensity-float(row['intensity']))<.01,(c.intensity,row['intensity'])
        if row.get('fogonly'):
            channels=c.lighting_channels
            assert not channels.channel0 and not channels.channel1 and not channels.channel2
        if 'temperature' in row:assert abs(c.temperature-row['temperature'])<.01
        checked+=1
    pp=[a.get_component_by_class(unreal.PostProcessComponent) for a in actors.values()]
    pp=[c for c in pp if c]
    assert len(pp)==1,len(pp)
    assert not pp[0].unbound and pp[0].priority==2
    assert pp[0].settings.override_color_contrast
    (root/'native-source-check.json').write_text(json.dumps({'complete':True,'light_properties_checked':checked,
        'fog_only':report['fog_only_lights'],'postprocess':report['postprocess'],'source_fog':report.get('source_fog_settings')}))
except Exception:
    (root/'native-source-check.json').write_text(json.dumps({'complete':False,'error':traceback.format_exc()}))
    raise
''',encoding='utf-8')
env=os.environ.copy()
env.update(ATLASMAP_SCRIPTS=str(BASE/'scripts/official'),ATLASMAP_SOURCE_ROOT=str(OUT/'CollectionRoom'),
           ATLASMAP_UE_LEVEL='/Game/AtlasMaps/CollectionRoomAuto2/LV_Map',ATLASMAP_UE_NO_RENDER='1')
with (OUT/'check-source-ue.log').open('w',encoding='utf-8') as log:
    result=subprocess.run(['E:/UE_5.4/Engine/Binaries/Win64/UnrealEditor-Cmd.exe',
        str(BASE/'work/ue_test/AtlasMapTest54/AtlasMapTest54.uproject'),'-ExecutePythonScript='+str(script),
        '-nullrhi','-unattended','-nosplash','-nop4','-SCCProvider=None','-stdout','-UTF8Output'],
        env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=0x08000000,timeout=300)
report=json.loads((OUT/'CollectionRoom/native-source-check.json').read_text())
print(report)
assert result.returncode==0 and report['complete'],result.returncode
