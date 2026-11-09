"""Hidden authored fog must not become a globally active fog on import."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
OFFICIAL=ROOT/'scripts/official'


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,OFFICIAL/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


contract=load('fog_visibility_contract','map_lighting.py')
profile=load('fog_visibility_profile','map_game_lighting.py')
with patch.dict(sys.modules,{'unreal':SimpleNamespace(),'map_lighting':contract,'map_game_lighting':profile}):
    importer=load('fog_visibility_importer','ue_ensure_lighting.py')


class Component:
    def __init__(self,visible=True,ignore=False):
        self.visible=visible;self.ignore=ignore;self.calls=[]
    def set_visibility(self,value,propagate):
        self.calls.append((value,propagate))
        if not self.ignore:self.visible=value
    def get_editor_property(self,name):
        if name!='visible':raise AttributeError(name)
        return self.visible
    def set_mobility(self,value):pass


class FogVisibilityTests(unittest.TestCase):
    def report(self):return {'errors':[],'compatibility':[]}
    def test_false_source_is_applied_without_truthiness_default(self):
        component=Component();row={'name':'HiddenFog','type':'Fog','visible':False};report=self.report()
        importer._restore_component_visibility(component,row,report)
        importer._validate_component_visibility(component,row,report)
        self.assertFalse(component.visible)
        self.assertEqual(component.calls,[(False,False)])
        self.assertEqual(report['component_visibility']['matched_fields'],1)
        self.assertEqual(report['errors'],[])

    def test_missing_source_does_not_change_existing_visible_or_hidden_fog(self):
        for visible in [True,False]:
            with self.subTest(visible=visible):
                component=Component(visible);row={'name':'LegacyFog','type':'Fog'};report=self.report()
                importer._restore_component_visibility(component,row,report)
                importer._validate_component_visibility(component,row,report)
                self.assertEqual(component.visible,visible);self.assertEqual(component.calls,[])
                self.assertEqual(report['component_visibility']['expected_fields'],0)
                self.assertEqual(len(report['component_visibility']['missing_source_fields']),1)

    def test_silent_setter_rejection_is_an_independent_readback_error(self):
        component=Component(ignore=True);row={'name':'Fog','type':'Fog','visible':False};report=self.report()
        importer._restore_component_visibility(component,row,report)
        self.assertEqual(report['errors'],[])
        importer._validate_component_visibility(component,row,report)
        self.assertEqual(report['errors'][0]['phase'],'visibility_readback')
        self.assertEqual(report['component_visibility']['matched_fields'],0)

    def run_main(self,ignore=False):
        component=Component(ignore=ignore);actor=Mock();actor.tags=[]
        actor.get_class.return_value.get_name.return_value='ExponentialHeightFog'
        classes={name:type(name,(),{}) for name in (
            'PointLight','PointLightComponent','SpotLight','SpotLightComponent',
            'RectLight','RectLightComponent','DirectionalLight','DirectionalLightComponent',
            'SkyLight','SkyLightComponent','ExponentialHeightFog','ExponentialHeightFogComponent')}
        actor.get_component_by_class.side_effect=lambda cls:component if cls is classes['ExponentialHeightFogComponent'] else None
        eas=Mock();eas.get_all_level_actors.return_value=[actor]
        les=Mock();les.save_current_level.return_value=True
        editor=Mock();editor.get_editor_world.return_value.get_path_name.return_value='/Game/Test.Test'
        fake=SimpleNamespace(**classes,LevelEditorSubsystem='level',UnrealEditorSubsystem='editor',EditorActorSubsystem='actor',
            get_editor_subsystem=lambda cls:{'level':les,'editor':editor,'actor':eas}[cls],
            ComponentMobility=SimpleNamespace(MOVABLE=1),Rotator=lambda **kwargs:kwargs,Vector=lambda *args:args,
            Name=lambda text:text,log=Mock())
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'lights.json').write_text(json.dumps({'lights':[{'Type':'Fog','Name':'Mobile_UnderwaterFog','Visible':False}]}),encoding='utf-8')
            (root/'scene.json').write_text(json.dumps({'instances':[]}),encoding='utf-8')
            with patch.object(importer,'unreal',fake),patch.dict(os.environ,{
                'ATLASMAP_UE_LEVEL':'/Game/Test','ATLASMAP_SOURCE_ROOT':temporary,'ATLASMAP_UE_NO_RENDER':'1',
                'ATLASMAP_LIGHTING_MODE':'source','ATLASMAP_RENDER_PROFILE':'source'}),\
                patch.dict(sys.modules,{'ue_actor_spawn':SimpleNamespace(spawn_actor=Mock(return_value=actor))}):
                if ignore:
                    with self.assertRaisesRegex(RuntimeError,'Lighting restoration incomplete'):importer.main()
                else:importer.main()
            report=json.loads((root/'lighting_report.json').read_text(encoding='utf-8'))
        return component,report,les

    def test_complete_fog_branch_applies_hidden_source_and_saves(self):
        component,report,les=self.run_main()
        self.assertFalse(component.visible);self.assertTrue(report['complete'])
        self.assertEqual(report['component_visibility']['matched_fields'],1)
        self.assertEqual(report['restored']['Fog'],1);les.save_current_level.assert_called_once()

    def test_complete_fog_branch_does_not_save_success_after_readback_failure(self):
        component,report,les=self.run_main(ignore=True)
        self.assertFalse(report['complete']);self.assertTrue(component.visible)
        self.assertEqual(report['errors'][0]['phase'],'visibility_readback')
        les.save_current_level.assert_not_called()


if __name__=='__main__':unittest.main()
