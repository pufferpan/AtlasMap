"""Run the rebuilt CollectionRoom through the real Blender/UE pipeline."""
import json
from pathlib import Path
import sys

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from core import exporter,ue_pipeline
OUT=BASE/'work/export-rebuild-20261101'
PROJECT=OUT/'AtlasMapRebuilt/AtlasMapRebuilt.uproject'
PROJECT.parent.joinpath('Config').mkdir(parents=True,exist_ok=True)
PROJECT.write_text(json.dumps({'FileVersion':3,'EngineAssociation':'5.4','Plugins':[
    {'Name':'PythonScriptPlugin','Enabled':True},{'Name':'EditorScriptingUtilities','Enabled':True},
    {'Name':'GeometryScripting','Enabled':True}]}),encoding='utf-8')
PROJECT.parent.joinpath('Config/DefaultEngine.ini').write_text(
    '[/Script/Engine.RendererSettings]\nr.DynamicGlobalIlluminationMethod=1\nr.ReflectionMethod=1\nr.GenerateMeshDistanceFields=True\n',encoding='utf-8')
p={'exe':exporter.find_exe(),'config':exporter.write_exporter_config(),'map':'CollectionRoom',
   'root':str(OUT/'CollectionRoom'),'transfer':str(OUT/'CollectionRoom_ue'),
   'scripts':str(BASE/'scripts/official'),'blender':'G:/SteamLibrary/steamapps/common/Blender/blender.exe',
   'engine':'E:/UE_5.4/Engine/Binaries/Win64/UnrealEditor.exe',
   'cmd':'E:/UE_5.4/Engine/Binaries/Win64/UnrealEditor-Cmd.exe',
   'project':str(PROJECT),'dest':'/Game/AtlasMaps/CollectionRoomRebuilt','workers':'6'}
ue_pipeline.validate_export(p['root'],p['map'])
ue_pipeline.prepare_dirs(p['root'])
from core.scene_state import enrich
state=enrich(p['root'])
assert state['complete'] and len(state['lights'])==130
steps=ue_pipeline.build_steps(p)[-1:] if '--ue-only' in sys.argv else ue_pipeline.build_steps(p)[2:]
job=ue_pipeline.Pipeline(steps,on_line=lambda line:print(line,flush=True))
job._run()
assert job.code==0,job.code
