from pathlib import Path
import tempfile
import unittest

from core.ue_render_config import ensure_game_renderer
from scripts.official.map_lighting import postprocess_box


class IndoorLightingTests(unittest.TestCase):
    def test_existing_project_enables_lumen_dependencies_without_losing_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            project=root/'Test.uproject';project.write_text('{}')
            ini=root/'Config/DefaultEngine.ini';ini.parent.mkdir()
            original='[/Script/Engine.RendererSettings]\nr.GenerateMeshDistanceFields=False\nr.ReflectionMethod=0\ncustom=value\n\n[Other]\nKey=untouched\n'
            ini.write_text(original)
            ensure_game_renderer(project)
            result=ini.read_text()
            self.assertIn('r.GenerateMeshDistanceFields=True',result)
            self.assertIn('r.DynamicGlobalIlluminationMethod=1',result)
            self.assertIn('r.ReflectionMethod=1',result)
            self.assertIn('[Other]\nKey=untouched',result)
            self.assertIn('custom=value',result)
            self.assertEqual(ini.with_suffix('.ini.atlasmap-backup').read_text(),original)
            ensure_game_renderer(project)
            self.assertEqual(ini.read_text(),result)
            self.assertEqual(ini.with_suffix('.ini.atlasmap-backup').read_text(),original)

    def test_missing_section_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'Test.uproject';project.touch()
            ensure_game_renderer(project)
            ini=root/'Config/DefaultEngine.ini'
            ini.write_text(ini.read_text()+'r.GenerateMeshDistanceFields=False\n')
            ensure_game_renderer(project)
            self.assertEqual(ini.read_text().count('r.GenerateMeshDistanceFields='),1)

    def test_brush_local_center_uses_scale_and_rotation(self):
        center,extent=postprocess_box({'transform':{
            'RelativeLocation':{'X':100,'Y':200,'Z':300},
            'RelativeScale3D':{'X':-2,'Y':3,'Z':4},'RelativeRotation':{'Yaw':90}},
            'bounds':{'Origin':{'X':10,'Y':20,'Z':30},'BoxExtent':{'X':5,'Y':6,'Z':7}}})
        for actual,expected in zip(center,(40,180,420)):self.assertAlmostEqual(actual,expected)
        self.assertEqual(extent,[10,18,28])

    def test_unbounded_volume_does_not_invent_bounds(self):
        self.assertEqual(postprocess_box({'transform':{'RelativeLocation':{'X':42}}}),([42,0,0],None))
