import copy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.official.map_environment import (
    select_authored_sky_cube,known_source_sky_rows,sky_actor_matches)

SID='DFI_fe8897eb5129eb4e5553ef96'
MESH='DeltaForce/Content/MaterialLib/Materials/Scene/Sky/Map/SM_skymesh_A.SM_skymesh_A'
CUBE='DeltaForce/Content/Map/ReflectionCubes_HD/Sunny.Sunny'
REFLECTION='DeltaForce/Content/Map/ReflectionCaptureCubes_HD/Sunny.Sunny'


def source_row():
    actor='Map.Map:PersistentLevel.SkyDomeMesh'
    return {'mesh':MESH,'dfmap':{'sourceId':SID,'unrealMeshPath':MESH,
        'sourceActor':actor,'sourceComponent':'StaticMeshComponent0',
        'sourceComponentPath':actor+'.StaticMeshComponent0','overrideMaterials':[None],
        'visibility':{'renderable':True}}}


def light(cube=CUBE):
    return {'Type':'Sky','Source':{'properties':{'SourceType':'SLS_SpecifiedCubemap',
        'Cubemap':{'ObjectPath':cube.split('.')[0]+'.0','ObjectName':"TextureCube'Sunny'"},
        'ReflectionCubemap':{'ObjectPath':REFLECTION}}}}


class SkyFallbackSelectionTests(unittest.TestCase):
    def test_exact_sky_cube_wins_over_identical_reflection_short_name(self):
        sky={'kind':'cube','source_texture':CUBE};reflection={'kind':'cube','source_texture':REFLECTION}
        self.assertIs(select_authored_sky_cube({'skies':[reflection,sky]},[light()]),sky)

    def test_ambiguous_actual_sky_requests_or_duplicate_descriptors_are_not_guessed(self):
        sky={'kind':'cube','source_texture':CUBE}
        self.assertIsNone(select_authored_sky_cube({'skies':[sky,dict(sky)]},[light()]))
        self.assertIsNone(select_authored_sky_cube({'skies':[sky]},[light(),light(REFLECTION)]))

    def test_game_soft_reference_uses_full_object_identity(self):
        row=light('/Game/Map/ReflectionCubes_HD/Sunny.Sunny')
        self.assertIsNotNone(select_authored_sky_cube({'skies':[{'kind':'cube','source_texture':CUBE}]},[row]))

    def test_captured_scene_source_does_not_authorize_specified_cube_fallback(self):
        row=light();row['Source']['properties']['SourceType']='SLS_CapturedScene'
        self.assertIsNone(select_authored_sky_cube({'skies':[{'kind':'cube','source_texture':CUBE}]},[row]))

    def test_only_full_audited_source_dome_identity_qualifies(self):
        row=source_row();self.assertEqual(known_source_sky_rows({'instances':[row]}),[row])
        for key,value in [('unrealMeshPath','Engine/Content/BasicShapes/Plane.Plane'),
            ('sourceActor','Map.Map:PersistentLevel.OtherSkyDomeMesh'),('overrideMaterials',['CustomSky']),
            ('sourceComponentPath','wrong'),('sourceId','missing')]:
            bad=copy.deepcopy(row);bad['dfmap'][key]=value
            with self.subTest(key=key):self.assertEqual(known_source_sky_rows({'instances':[bad]}),[])

    def test_hidden_or_unrelated_geometry_does_not_qualify(self):
        for update in ({'hiddenInGame':True},{'ownerHidden':True},{'renderable':False}):
            row=source_row();row['dfmap']['visibility'].update(update)
            self.assertEqual(known_source_sky_rows({'instances':[row]}),[])
        row=source_row();row['mesh']='Engine/Content/BasicShapes/Plane.Plane'
        self.assertEqual(known_source_sky_rows({'instances':[row]}),[])

    def test_actor_id_matching_rejects_name_fragments_and_duplicate_suffixes(self):
        self.assertTrue(sky_actor_matches(SID,'C006_'+SID,{}))
        self.assertTrue(sky_actor_matches(SID,SID,{}))
        self.assertFalse(sky_actor_matches(SID,'Wrong_'+SID,{}))
        self.assertFalse(sky_actor_matches(SID,'C006_'+SID+'.001',{}))

    def test_no_source_dome_causes_no_import_material_or_geometry_changes(self):
        # Import the module using minimal UE stubs. The no-identity path must
        # terminate before any texture/material/actor operation is attempted.
        path=Path(__file__).resolve().parents[1]/'scripts/official/ue_source_environment.py'
        spec=importlib.util.spec_from_file_location('source_sky_fallback_test_module',path)
        module=importlib.util.module_from_spec(spec)
        import scripts.official.map_environment as env
        import scripts.official.map_lighting as lighting
        with patch.dict(sys.modules,{'unreal':SimpleNamespace(), 'map_environment':env,'map_lighting':lighting}):
            spec.loader.exec_module(module)
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'scene.json').write_text(json.dumps({'instances':[]}))
            descriptor={'kind':'cube','source_texture':CUBE}
            eas=SimpleNamespace(get_all_level_actors=lambda:[])
            with patch.object(module,'_import',side_effect=AssertionError('Must not import')),patch.object(module,'_sky_material',side_effect=AssertionError('Must not build')):
                state=module._existing_sky_fallback(root,{'lights':[light()]},None,{'skies':[descriptor]},eas,root,'/Game/Test')
            self.assertEqual(state['applied'],[])
            self.assertFalse(state['high_resolution_sky_restored'])

    def test_existing_audited_dome_is_updated_without_spawning_or_moving(self):
        path=Path(__file__).resolve().parents[1]/'scripts/official/ue_source_environment.py'
        spec=importlib.util.spec_from_file_location('source_sky_fallback_positive_module',path)
        module=importlib.util.module_from_spec(spec)
        import scripts.official.map_environment as env
        import scripts.official.map_lighting as lighting
        class Cube:pass
        class Actor:
            def __init__(self):
                self.tags=['preserved_source_tag'];self.transform=('source_position','source_scale')
                self.static_mesh_component=SimpleNamespace(get_editor_property=lambda name:True)
            def get_actor_label(self):return 'C006_'+SID
            def get_editor_property(self,name):return False
            def get_actor_transform(self):return self.transform
            def get_path_name(self):return '/Game/Test:SkyDome'
        ue=SimpleNamespace(TextureCube=Cube,StaticMeshActor=Actor)
        with patch.dict(sys.modules,{'unreal':ue,'map_environment':env,'map_lighting':lighting}):
            spec.loader.exec_module(module)
        import tempfile
        actor=Actor();before=(actor.transform,actor.tags[:])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'scene.json').write_text(json.dumps({'instances':[source_row()]}))
            descriptor={'kind':'cube','source_texture':CUBE,'texture':{'RelativePath':'cube.dds','Width':128,'Height':128}}
            material=SimpleNamespace(get_path_name=lambda:'/Game/TestMaterial')
            with patch.object(module,'_import',return_value=Cube()),patch.object(module,'_sky_material',return_value=material),patch.object(module,'_configure_sky_component') as configure,patch.object(module,'_spawn',side_effect=AssertionError('Must not spawn')):
                state=module._existing_sky_fallback(root,{'lights':[light()]},None,{'skies':[descriptor]},SimpleNamespace(get_all_level_actors=lambda:[actor]),root,'/Game/Test')
                configure.assert_called_once_with(actor.static_mesh_component,material)
        self.assertEqual((actor.transform,actor.tags),before)
        self.assertEqual(state['applied'][0]['source_id'],SID)
        self.assertFalse(state['high_resolution_sky_restored'])
