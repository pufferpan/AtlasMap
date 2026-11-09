"""Regression coverage for map identity and incomplete lighting exports."""
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from core import exporter, ue_pipeline
from app.ue_page import UePage
from app.main_window import MapViewerWindow


class Shell:
    job = None

    def status(self, message):
        self.message = message


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.saved = {"ue_map": "CollectionRoom", "ue_root": "C:/Export/CollectionRoom",
                      "ue_dest": "/Game/AtlasMaps/CollectionRoomAuto3", "outdir": "C:/Export"}
        self.patches = [patch("core.exporter.load_settings", side_effect=lambda: dict(self.saved)),
                        patch("core.exporter.save_settings", side_effect=lambda data: self.saved.update(data))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.shell = Shell()
        self.page = UePage(self.shell, self.shell)
        self.addCleanup(self.page.deleteLater)

    def test_selection_moves_both_output_and_level(self):
        self.page.cb_map.setCurrentIndex(self.page.cb_map.findData("SafeHouse"))
        p = self.page._paths()
        self.assertEqual(p["map"], "SafeHouse")
        self.assertEqual(Path(p["root"]).name, "SafeHouse")
        self.assertEqual(p["dest"], "/Game/AtlasMaps/SafeHouse")
        self.assertNotIn("CollectionRoom", self.page._cmd_export())
        self.assertIn("ATLASMAP_SOURCE_ROOT", self.page._cmd_finish())

    def test_blender_target_uses_native_selector_and_hides_unreal_configuration(self):
        from fluentpy import widgets as W
        self.assertIs(type(self.page.cb_target),W.ComboBox)
        self.page.cb_target.setCurrentIndex(self.page.cb_target.findData('blender'))
        self.page.advanced_switch.setChecked(True)
        self.assertTrue(self.page.ed_engine.isHidden())
        self.assertTrue(self.page.ed_project.isHidden())
        self.assertFalse(self.page.ed_blender.isHidden())
        self.assertIn('Blender',self.page.btn_auto.text())
        self.assertEqual(self.page._paths()['target'],'blender')
        self.assertEqual(self.saved['export_target'],'blender')
        self.page.cb_target.setCurrentIndex(self.page.cb_target.findData('ue'))
        self.assertFalse(self.page.ed_engine.isHidden())

    def test_blender_button_starts_without_detecting_or_creating_unreal(self):
        self.page.cb_target.setCurrentIndex(self.page.cb_target.findData('blender'))
        self.page.ed_engine.clear();self.page.ed_project.clear();self.page.ed_blender.setText('Blender.exe')
        self.shell.show_export_overlay=Mock(return_value=Mock())
        self.shell.run_pipeline=Mock()
        with patch('os.path.isfile',return_value=True),patch('core.exporter.find_exe',return_value='map-export.exe'),\
             patch('core.exporter.write_exporter_config',return_value='config'),patch('core.ue_pipeline.prepare_dirs',return_value=[]),\
             patch('core.blender_pipeline.build_steps',return_value=([ue_pipeline.Step('test',[])],'C:/Maps/Test.blend')),\
             patch('app.ue_page._detect_engine') as engine,patch.object(self.page,'_ensure_project') as project:
            self.page._run_all()
        engine.assert_not_called();project.assert_not_called()
        self.shell.run_pipeline.assert_called_once()

    def test_simple_mode_hides_complex_controls_without_resetting_values(self):
        from fluentpy import widgets as W
        self.assertIs(type(self.page.advanced_switch), W.ToggleSwitch)
        self.assertFalse(self.page.advanced_switch.isChecked())
        self.assertTrue(self.page.ed_engine.isHidden())
        self.assertFalse(self.page.ed_root.isHidden())
        old = self.page.sp_workers.value()
        self.page.advanced_switch.setChecked(True)
        self.assertFalse(self.page.ed_engine.isHidden())
        self.assertTrue(self.saved['advanced_mode'])
        self.page.advanced_switch.setChecked(False)
        self.assertEqual(self.page.sp_workers.value(), old)
        self.assertTrue(self.page._steps[0][2].parentWidget().isHidden())

    def test_typed_codename_and_display_name(self):
        for typed, expected in [("BombDefusal_Watch", "BombDefusal_Watch"), ("SafeHouse", "SafeHouse"),
                                ('Brakkesh Long3','Brakkesh_Long3'),('Collapse','Collapse')]:
            self.page.cb_map.setEditText(typed)
            p = self.page._paths()
            self.assertEqual(p["map"], expected)
            self.assertEqual(Path(p["root"]).name, expected)
            self.assertTrue(p["dest"].endswith("/" + expected))

    def test_no_silent_default_map(self):
        self.page.cb_map.setEditText("")
        self.page._run_all()
        self.assertIn("请选择地图", self.shell.message)

    def test_export_includes_lighting_and_both_source_trees(self):
        self.page.cb_map.setEditText("SafeHouse")
        cmd = ue_pipeline.export_command(self.page._paths())
        roots = cmd[cmd.index("--root") + 1]
        self.assertEqual(cmd.count("--root"), 1)
        self.assertIn("BuildMaps_HD/SafeHouse/", roots)
        self.assertIn("Maps/SafeHouse/", roots)
        self.assertIn("--all", cmd)
        self.assertNotIn("Lighting", cmd[cmd.index("--exclude") + 1])
        p = dict(self.page._paths(), map="Dam_Iris_WithoutEvent")
        variant = ue_pipeline.export_command(p)
        self.assertNotIn("_Without", variant[variant.index("--exclude") + 1])

    def test_missing_or_wrong_map_export_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "split").mkdir()
            (root / "split/manifest.json").write_text(json.dumps({"levels": [{"instances": 1}]}))
            (root / "lights.json").write_text('{"lights": []}')
            scene = {"mapRoot": " + ".join(ue_pipeline.map_roots("CollectionRoom")), "instances": [{}]}
            (root / "scene.json").write_text(json.dumps(scene))
            with self.assertRaises(ValueError):
                ue_pipeline.validate_export(temporary, "SafeHouse")
            scene["mapRoot"] = " + ".join(ue_pipeline.map_roots("SafeHouse"))
            (root / "scene.json").write_text(json.dumps(scene))
            ue_pipeline.validate_export(temporary, "SafeHouse")
            (root / "split/manifest.json").write_text('{"levels": []}')
            with self.assertRaises(ValueError):
                ue_pipeline.validate_export(temporary, "SafeHouse")

    def test_library_multiple_roots_are_not_discarded(self):
        with patch("core.exporter.write_exporter_config", return_value="config.json"):
            cmd = exporter.merge_command("map-export.exe", "SafeHouse", "out", ["first/", "second/"])
        self.assertEqual(cmd.count("--root"), 1)
        self.assertEqual(cmd[cmd.index("--root") + 1], "first/,second/")

    def test_progress_is_delivered_on_gui_thread(self):
        host = SimpleNamespace(job=None, job_page=Mock(), status=Mock(),
                               _begin_task_log=Mock(return_value=None),_task_log_error='')
        host._log_callbacks=lambda log,bridge:MapViewerWindow._log_callbacks(host,log,bridge)
        received = []
        with patch("core.ue_pipeline.Pipeline") as pipeline:
            MapViewerWindow.run_pipeline(host, "test", [], on_progress=lambda *args: received.append(args))
            emit = pipeline.call_args.kwargs["on_progress"]
            worker = threading.Thread(target=lambda: emit(1, 8, "灯光"))
            worker.start()
            worker.join()
            self.assertEqual(received, [])
            self.app.processEvents()
            self.assertEqual(received, [(1, 8, "灯光")])

    def test_regular_export_still_starts(self):
        host = SimpleNamespace(job=None, job_page=Mock(), status=Mock(),
                               _begin_task_log=Mock(return_value=None),_task_log_error='')
        host._log_callbacks=lambda log,bridge:MapViewerWindow._log_callbacks(host,log,bridge)
        with patch("core.exporter.start", return_value="started"):
            self.assertEqual(MapViewerWindow.run_job(host, "test", ["map-export.exe"]), "started")

    def test_open_result_does_not_fall_back_to_another_map(self):
        self.page.cb_map.setEditText("SafeHouse")
        self.page.ed_engine.setText("C:/UE/UnrealEditor.exe")
        self.page.ed_project.setText("C:/Project/Test.uproject")
        with patch("os.path.isfile", side_effect=lambda path: not str(path).endswith(".umap")), \
                patch("subprocess.Popen") as launch:
            self.page._open_editor()
        launch.assert_not_called()
        self.assertIn("SafeHouse", self.shell.message)
        self.assertIn("尚未导入", self.shell.message)

    def test_single_ue_process_uses_no_gpu_and_finishes_all_steps(self):
        self.page.cb_map.setEditText("CollectionRoom")
        steps = ue_pipeline.build_steps(self.page._paths())
        engine = [step for step in steps if any(arg.startswith("-ExecutePythonScript=") for arg in step.cmd)]
        self.assertEqual(len(engine), 1)
        self.assertIn("-nullrhi", engine[0].cmd)
        from core.ue_render_config import headless_renderer_args
        self.assertTrue(all(arg in engine[0].cmd for arg in headless_renderer_args()))
        self.assertTrue(all(arg in self.page._cmd_ue() for arg in headless_renderer_args()))
        parallel=ue_pipeline.build_steps(dict(self.page._paths(),parallel_export='1'))
        masters=[step for step in parallel if any('ue_assemble_chunks.py' in arg for arg in step.cmd)]
        self.assertEqual(len(masters),1)
        self.assertTrue(all(arg in masters[0].cmd for arg in headless_renderer_args()))
        self.assertEqual(engine[0].env["ATLASMAP_UE_FINISH"], "1")
        self.assertEqual(engine[0].env["ATLASMAP_UE_BATCH_IMPORT"], "1")
        self.assertTrue(steps[0].log_path.endswith("pipeline.log"))

    def test_preview_preferences_update_commands_and_persist(self):
        self.assertEqual(self.page._paths()['lighting_mode'],'source')
        self.page.chk_supplemental.setChecked(True)
        self.assertEqual(self.saved['lighting_mode'],'supplemental')
        self.assertIn('ATLASMAP_LIGHTING_MODE = "supplemental"',self.page._cmd_finish())
        self.page.cb_render_view.setCurrentIndex(self.page.cb_render_view.findData('lights'))
        self.assertEqual(self.saved['render_view'],'lights')

    def test_game_lighting_option_updates_import_preview_and_manual_commands(self):
        self.assertEqual(self.page._paths()['render_profile'],'game')
        self.page.chk_game_lighting.setChecked(False)
        self.assertEqual(self.saved['render_profile'],'source')
        self.assertEqual(self.page._paths()['render_profile'],'source')
        self.assertIn('ATLASMAP_RENDER_PROFILE = "source"',self.page._cmd_finish())

    def test_a_previous_success_cannot_mask_current_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ue_import_result.json"
            path.write_text(json.dumps({"complete": True, "level": "/Game/Test", "run_id": "old"}))
            with self.assertRaises(ValueError):
                ue_pipeline.validate_result(str(path), "/Game/Test", 0, "new")

    def test_failed_import_cannot_open_its_partial_level(self):
        self.page.cb_map.setEditText("CollectionRoom")
        with patch("os.path.isfile", return_value=True), patch("subprocess.Popen") as launch:
            self.page._open_editor()
        launch.assert_not_called()
        self.assertIn("尚未完成", self.shell.message)

    def test_failed_import_cannot_render_a_partial_or_other_level(self):
        self.page.cb_map.setEditText('CollectionRoom')
        with patch('os.path.isfile',return_value=True), patch.object(self.shell,'run_pipeline',create=True) as launch:
            self.page._render_preview()
        launch.assert_not_called()
        self.assertIn('尚未完成',self.shell.message)


if __name__ == "__main__":
    unittest.main()
