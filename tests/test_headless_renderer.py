"""NullRHI must receive renderer overrides before any assets or maps load."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from core.ue_render_config import ensure_game_renderer, headless_renderer_args
from scripts.official.ue_headless_renderer import check_headless_renderer


class HeadlessRendererTests(unittest.TestCase):
    def test_startup_overrides_leave_the_persistent_lumen_settings_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory)/'Test.uproject';project.write_text('{}')
            ensure_game_renderer(project)
            ini=project.parent/'Config/DefaultEngine.ini'
            before=ini.read_bytes()
            argument,=headless_renderer_args()
            self.assertTrue(argument.startswith('-ini:Engine:'))
            self.assertIn('[/Script/Engine.RendererSettings]:r.GenerateMeshDistanceFields=False',argument)
            self.assertIn('[/Script/Engine.RendererSettings]:r.DynamicGlobalIlluminationMethod=0',argument)
            self.assertIn('[/Script/Engine.RendererSettings]:r.ReflectionMethod=0',argument)
            self.assertEqual(ini.read_bytes(),before)
            self.assertIn(b'r.GenerateMeshDistanceFields=True',before)

    def unreal(self,command,values):
        return SimpleNamespace(SystemLibrary=SimpleNamespace(get_command_line=lambda:command,
            get_console_variable_int_value=values.__getitem__),log=Mock())

    def test_nullrhi_startup_fails_before_assets_if_any_override_was_lost(self):
        names=['r.GenerateMeshDistanceFields','r.DynamicGlobalIlluminationMethod','r.ReflectionMethod']
        for enabled in names:
            values={name:int(name==enabled) for name in names}
            with self.subTest(enabled=enabled), self.assertRaisesRegex(RuntimeError,'启动参数未生效'):
                check_headless_renderer(self.unreal('-unattended -NullRHI',values))

    def test_safe_nullrhi_and_normal_editor_are_distinguished(self):
        values=dict.fromkeys(['r.GenerateMeshDistanceFields','r.DynamicGlobalIlluminationMethod','r.ReflectionMethod'],0)
        self.assertTrue(check_headless_renderer(self.unreal('-nullrhi',values))['null_rhi'])
        values={name:1 for name in values}
        self.assertFalse(check_headless_renderer(self.unreal('-dx12',values))['null_rhi'])
