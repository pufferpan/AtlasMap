import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from core.scene_state import Sources,enrich
from core import exporter,ue_pipeline


class SceneStateTests(unittest.TestCase):
    def test_authored_camera_follows_the_source_parent_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            root={'type':'SceneComponent','name':'Root','value':{'Properties':{
                'RelativeLocation':{'X':1000},'RelativeRotation':{'Yaw':90}}}}
            camera={'type':'CameraComponent','name':'Camera','value':{'Properties':{
                'RelativeLocation':{'X':10},'AttachParent':{'ObjectPath':'Level.0','ObjectName':"SceneComponent'Root'"}}}}
            (folder/'level.json').write_text(json.dumps([root,camera]))
            source=Sources(folder,{'packages':{'Level.umap':'level.json'}})
            position,basis=source.pose(camera)
            self.assertAlmostEqual(position[0],1000)
            self.assertAlmostEqual(position[1],10)
            self.assertAlmostEqual(basis[1][0],1)
    def test_regular_map_export_also_captures_source_render_state(self):
        command=exporter.source_state_command(['G:/Tool/map-export.exe','--config','cfg.json','merge','CollectionRoom','G:/Exports/Room','--all'])
        self.assertTrue(command[0].endswith('scene-state.exe'))
        self.assertEqual(Path(command[-2]),Path('G:/Exports/Room'))
        self.assertEqual(Path(command[-1]),Path('G:/Exports/Room/source-render'))
        self.assertIsNone(exporter.source_state_command(['map-export.exe','doctor']))
    def test_inherited_units_and_fog_only_survive_duplicate_component_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'source-render';folder.mkdir()
            template={'type':'RectLightComponent','name':'Lamp','value':{'Properties':{
                'IntensityUnits':'ELightUnits::Lumens','bAffectVolumetricFogOnly':True,'Temperature':4500}}}
            def component(radius):return {'type':'RectLightComponent','name':'Lamp','value':{
                'Template':{'ObjectPath':'Template.0','ObjectName':"RectLightComponent'Lamp'"},
                'Properties':{'Intensity':2000,'AttenuationRadius':radius}}}
            (folder/'template.json').write_text(json.dumps([template]))
            (folder/'level.json').write_text(json.dumps([component(300),component(400)]))
            index={'complete':True,'mapRoot':'Map','exporter':{},'preservedAssets':[],
                'packages':{'Template':'template.json','Level.umap':'level.json'},'levels':[{
                    'level':'Level.umap','lights':[{'Type':'Rect','Name':'Lamp','Loc':[0,0,0],'Rot':[0,0,0]},
                                                  {'Type':'Rect','Name':'Lamp','Loc':[1,0,0],'Rot':[0,0,0]}]}]}
            (folder/'state-index.json').write_text(json.dumps(index))
            result=enrich(root)
            self.assertEqual([x['Radius'] for x in result['lights']],[300,400])
            self.assertTrue(all(x['IntensityUnits']=='lumens' and x['FogOnly'] and x['Temperature']==4500 for x in result['lights']))
            source=Sources(folder,index)
            self.assertIsNotNone(source.resolve({'ObjectPath':'Level.0','ObjectName':"RectLightComponent'Lamp'"}))

    def test_a_nonmatching_exporter_is_rejected_before_export(self):
        with patch.object(exporter,'exporter_is_required',return_value=False):
            with self.assertRaisesRegex(ValueError,'指定版本'):
                ue_pipeline.export_command({'exe':'wrong.exe'})

    def test_a_new_export_invalidates_an_old_import_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root=str(Path(directory)/'CollectionRoom')
            ue_pipeline.prepare_dirs(root)
            result=json.loads(Path(root+'_ue/ue_import_result.json').read_text())
            self.assertFalse(result['complete'])
