import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QPlainTextEdit
from app.export_window import ExportWindow
from core.ue_pipeline import Pipeline, Step

source = Path(__file__).resolve().parents[1] / "scripts/official/ue_asset_inputs.py"
spec = importlib.util.spec_from_file_location("ue_asset_inputs", source)
inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inputs)


class InputTests(unittest.TestCase):
    def test_parallel_preparation_detects_changed_cached_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content = b"source-texture-contents" * 4
            path = root / "texture.png"
            path.write_bytes(content)
            row = {"id":"T_Test","file":"texture.png","sha256":hashlib.sha256(content).hexdigest()}
            hashes, stats = inputs.prepare(root, [row], [], 4)
            self.assertEqual(hashes['Textures/T_Test']['sha256'],row['sha256'])
            self.assertEqual(stats['files'],1)
            old_time = path.stat().st_mtime_ns
            path.write_bytes(b"x" * len(content))
            os.utime(path, ns=(old_time + 1000000, old_time + 1000000))
            with self.assertRaises(ValueError):
                inputs.prepare(root, [row], [], 4)

    def test_failure_logs_survive_process_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pipeline.log"
            step = Step("failure", [sys.executable, "-c", "print('DIAGNOSTIC_DETAIL');raise SystemExit(3)"],log_path=str(path))
            pipeline = Pipeline([step]).start()
            pipeline._thread.join(10)
            self.assertFalse(pipeline.running)
            self.assertEqual(pipeline.code,3)
            self.assertIn("DIAGNOSTIC_DETAIL",path.read_text(encoding="utf-8"))


class LogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_long_logs_wrap_inside_the_small_window(self):
        window = ExportWindow()
        try:
            window.begin("export")
            line = "G:/Maps/" + "long_section/" * 50 + "asset.fbx"
            window.feed(line)
            window._on_tick()
            self.app.processEvents()
            self.assertEqual(window.log_view.text_edit.lineWrapMode(),QPlainTextEdit.WidgetWidth)
            self.assertGreater(window.log_view.text_edit.document().lastBlock().layout().lineCount(),1)
            self.assertEqual(window.log_view.text_edit.horizontalScrollBar().maximum(),0)
            self.assertTrue(window.rect().contains(window.log_view.geometry()))
            window.feed("FINAL_ERROR_DETAIL")
            window.finish(-4)
            self.assertIn("FINAL_ERROR_DETAIL",window.log_view.toPlainText())
            self.assertIn(line,window.log_view.toPlainText())
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
