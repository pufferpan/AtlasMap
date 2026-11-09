"""Native editor-only distance fields must not disappear during import/audit."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = ROOT/'scripts/official'


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, OFFICIAL/filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = load_module('distance_contract', 'map_lighting.py')
profile = load_module('distance_profile', 'map_game_lighting.py')
with patch.dict(sys.modules, {'unreal': SimpleNamespace(), 'map_lighting': contract,
                              'map_game_lighting': profile}):
    importer = load_module('distance_importer', 'ue_ensure_lighting.py')
state = load_module('distance_state', 'map_scene_state.py')


class EditorOnlyComponent:
    """UE may have a UPROPERTY with no generated Python attribute."""
    def __init__(self, ignored=(), unsupported=()):
        self.values = {'max_draw_distance': 100, 'max_distance_fade_range': 50}
        self.ignored = set(ignored)
        self.unsupported = set(unsupported)

    def get_editor_property(self, name):
        if name in self.unsupported:
            raise AttributeError('Editor property not supported: '+name)
        return self.values[name]

    def set_editor_property(self, name, value):
        if name in self.unsupported:
            raise AttributeError('Editor property not supported: '+name)
        if name not in self.ignored:
            self.values[name] = value


class NativeDistanceTests(unittest.TestCase):
    def row(self, **overrides):
        value = {'Type': 'Spot', 'Name': 'Lamp',
                 'MaxDrawDistance': 32000, 'MaxDistanceFadeRange': 4000}
        value.update(overrides)
        return list(contract.records({'lights': [value]}))[0][1]

    def report(self):
        return {'errors': [], 'compatibility': []}

    def test_inherited_values_and_zero_survive_raw_source_enrichment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root/'source-render'
            folder.mkdir()
            template = {'type': 'SpotLightComponent', 'name': 'Base', 'value': {
                'Properties': {'MaxDrawDistance': 32000, 'MaxDistanceFadeRange': 4000}}}
            component = {'type': 'SpotLightComponent', 'name': 'Lamp', 'value': {
                'Template': {'ObjectPath': 'Template.0', 'ObjectName': "SpotLightComponent'Base'"},
                'Properties': {'MaxDrawDistance': 0}}}
            (folder/'template.json').write_text(json.dumps([template]), encoding='utf-8')
            (folder/'level.json').write_text(json.dumps([component]), encoding='utf-8')
            index = {'complete': True, 'mapRoot': 'Map', 'exporter': {}, 'preservedAssets': [],
                     'packages': {'Template': 'template.json', 'Map.umap': 'level.json'},
                     'levels': [{'level': 'Map.umap', 'lights': [{'Type': 'Spot', 'Name': 'Lamp'}]}]}
            (folder/'state-index.json').write_text(json.dumps(index), encoding='utf-8')
            enriched = state.enrich(root)
            row = list(contract.records(enriched))[0][1]
            self.assertEqual(row['maxdrawdistance'], 0)
            self.assertEqual(row['maxdistancefaderange'], 4000)

    def test_editor_only_properties_apply_and_validate_without_python_attributes(self):
        component = EditorOnlyComponent()
        self.assertFalse(hasattr(component, 'max_draw_distance'))
        self.assertFalse(hasattr(component, 'max_distance_fade_range'))
        report = self.report()
        row = self.row(MaxDrawDistance=0)
        importer._restore_light_distances(component, row, report)
        importer._validate_light_distances(component, row, report)
        self.assertEqual(component.values, {'max_draw_distance': 0., 'max_distance_fade_range': 4000.})
        self.assertEqual(report['distance_fields']['expected_fields'], 2)
        self.assertEqual(report['distance_fields']['applied_fields'], 2)
        self.assertEqual(report['distance_fields']['checked_fields'], 2)
        self.assertEqual(report['distance_fields']['matched_fields'], 2)
        self.assertEqual(report['errors'], [])

    def test_silent_setter_rejection_fails_independent_readback(self):
        component = EditorOnlyComponent(ignored=['max_draw_distance'])
        report = self.report()
        row = self.row()
        importer._restore_light_distances(component, row, report)
        self.assertEqual(report['errors'], [])
        importer._validate_light_distances(component, row, report)
        self.assertEqual(report['distance_fields']['applied_fields'], 2)
        self.assertEqual(report['distance_fields']['checked_fields'], 2)
        self.assertEqual(report['distance_fields']['matched_fields'], 1)
        self.assertEqual(len(report['errors']), 1)
        self.assertEqual(report['errors'][0]['phase'], 'readback')
        self.assertEqual(report['errors'][0]['source_field'], 'MaxDrawDistance')

    def test_unsupported_native_field_is_not_skipped_by_the_validator(self):
        component = EditorOnlyComponent(unsupported=['max_draw_distance'])
        report = self.report()
        row = self.row()
        importer._restore_light_distances(component, row, report)
        importer._validate_light_distances(component, row, report)
        self.assertEqual([error['phase'] for error in report['errors']], ['apply', 'readback'])
        self.assertEqual(report['distance_fields']['expected_fields'], 2)
        self.assertEqual(report['distance_fields']['matched_fields'], 1)

    def test_legacy_sidecar_missing_fields_keeps_existing_values_and_reports_gap(self):
        component = EditorOnlyComponent()
        report = self.report()
        row = list(contract.records({'lights': [{'Type': 'Point', 'Name': 'Legacy'}]}))[0][1]
        importer._restore_light_distances(component, row, report)
        importer._validate_light_distances(component, row, report)
        self.assertEqual(component.values, {'max_draw_distance': 100, 'max_distance_fade_range': 50})
        self.assertEqual(report['distance_fields']['expected_fields'], 0)
        self.assertEqual(len(report['distance_fields']['missing_source_fields']), 2)
        self.assertEqual(report['errors'], [])

    def test_invalid_distance_source_values_are_rejected_before_ue_import(self):
        for field in ('MaxDrawDistance', 'MaxDistanceFadeRange'):
            for invalid in (-1, float('nan'), float('inf')):
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    self.row(**{field: invalid})

    def test_main_cannot_save_a_success_report_after_wrong_native_readback(self):
        component = EditorOnlyComponent(ignored=['max_draw_distance'])
        component.set_mobility = Mock()
        component.set_light_color = Mock()
        component.set_lighting_channels = Mock()
        actor = Mock()
        actor.tags = []
        actor.get_class.return_value.get_name.return_value = 'SpotLight'
        classes = {name: type(name, (), {}) for name in (
            'PointLight', 'PointLightComponent', 'SpotLight', 'SpotLightComponent',
            'RectLight', 'RectLightComponent', 'DirectionalLight', 'DirectionalLightComponent',
            'SkyLight', 'SkyLightComponent', 'ExponentialHeightFog', 'ExponentialHeightFogComponent')}
        actor.get_component_by_class.side_effect = lambda cls: component if cls is classes['SpotLightComponent'] else None
        eas = Mock()
        eas.get_all_level_actors.side_effect = [[], [actor], [actor]]
        eas.spawn_actor_from_class.return_value = actor
        les = Mock()
        les.save_current_level.return_value = True
        editor = Mock()
        editor.get_editor_world.return_value.get_path_name.return_value = '/Game/Test.Test'
        fake = SimpleNamespace(**classes,
            LevelEditorSubsystem='level', UnrealEditorSubsystem='editor', EditorActorSubsystem='actor',
            get_editor_subsystem=lambda cls: {'level': les, 'editor': editor, 'actor': eas}[cls],
            ComponentMobility=SimpleNamespace(MOVABLE=1),
            Rotator=lambda **kwargs: kwargs, Vector=lambda *args: args,
            LinearColor=lambda *args: args, Name=lambda text: text, log=Mock())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'lights.json').write_text(json.dumps({'lights': [{
                'Type': 'Spot', 'Name': 'Lamp', 'MaxDrawDistance': 32000,
                'MaxDistanceFadeRange': 4000}]}), encoding='utf-8')
            (root/'scene.json').write_text(json.dumps({'instances': []}), encoding='utf-8')
            with patch.object(importer, 'unreal', fake), patch.dict('os.environ', {
                'ATLASMAP_UE_LEVEL': '/Game/Test', 'ATLASMAP_SOURCE_ROOT': directory,
                'ATLASMAP_UE_NO_RENDER': '1', 'ATLASMAP_LIGHTING_MODE': 'source', 'ATLASMAP_RENDER_PROFILE':'source'}), \
                    patch.dict(sys.modules, {'ue_actor_spawn':SimpleNamespace(spawn_actor=Mock(return_value=actor))}):
                with self.assertRaisesRegex(RuntimeError, 'Lighting restoration incomplete'):
                    importer.main()
            result = json.loads((root/'lighting_report.json').read_text(encoding='utf-8'))
            self.assertFalse(result['complete'])
            self.assertEqual(result['distance_fields']['matched_fields'], 1)
            self.assertEqual(result['errors'][0]['phase'], 'readback')
            les.save_current_level.assert_not_called()


if __name__ == '__main__':
    unittest.main()
