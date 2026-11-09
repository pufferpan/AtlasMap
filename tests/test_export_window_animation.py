import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.export_window import ExportWindow, SHRINK_MS
from core.system_usage import SystemUsage, cpu_percent


class UsageTests(unittest.TestCase):
    def test_windows_cpu_includes_idle_only_once(self):
        self.assertEqual(cpu_percent((100, 200, 100), (140, 260, 140)), 60)
        self.assertIsNone(cpu_percent(None, (140, 260, 140)))
        self.assertIsNone(cpu_percent((100, 200, 100), (100, 200, 100)))

    @unittest.skipUnless(os.name == 'nt', 'Windows counters')
    def test_native_memory_counter_is_real_and_bounded(self):
        sample = SystemUsage().sample()
        self.assertGreater(sample['memory_total'], 0)
        self.assertGreater(sample['memory_used'], 0)
        self.assertLessEqual(sample['memory_used'], sample['memory_total'])
        self.assertGreaterEqual(sample['memory_percent'], 0)
        self.assertLessEqual(sample['memory_percent'], 100)


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_large_surface_really_shrinks_while_native_window_stays_fixed(self):
        window = ExportWindow()
        try:
            screen = self.app.primaryScreen().availableGeometry()
            start = screen.adjusted(10, 10, -10, -10)
            window.begin('正在导出CollectionRoom', start_rect=start)
            initial_surface = QRect(window.surfaceRect)
            live_layout = QRect(window._surface.geometry())
            native = QRect(window.geometry())
            window.feed('LOG_DURING_ANIMATION')
            QTest.qWait(SHRINK_MS // 3)
            self.assertTrue(window._transitioning)
            self.assertEqual(window.geometry(), native)
            self.assertLess(window.surfaceRect.width(), initial_surface.width())
            self.assertEqual(window._surface.geometry(),live_layout)
            self.assertTrue(window._surface.isHidden())
            self.assertIsNotNone(window._transition_surface.pixmap)
            QTest.qWait(SHRINK_MS)
            self.assertFalse(window._transitioning)
            self.assertEqual(window.surfaceRect, window.rect())
            self.assertIn('LOG_DURING_ANIMATION', window.log_view.toPlainText())
        finally:
            window.close()

    def test_hidden_button_opens_and_stops_resource_sampling(self):
        window = ExportWindow()
        try:
            window.begin('export')
            self.assertTrue(window.btn_debug.isHidden())
            self.assertFalse(window._usage_timer.isActive())
            # The mouse gesture also works while the log editor has focus.
            QTest.mouseDClick(window._surface, Qt.LeftButton, pos=QPoint(80, 30))
            self.assertFalse(window.btn_debug.isHidden())
            values={'cpu_percent':42.5,'memory_used':8*1024**3,'memory_total':16*1024**3,'memory_percent':50}
            with patch.object(window._usage,'sample',return_value=values):
                window.btn_debug.click()
            self.assertTrue(window._usage_timer.isActive())
            self.assertIn('42.5%', window.usage_label.text())
            self.assertIn('8.0/16.0 GB', window.usage_label.text())
            self.assertTrue(window._surface.rect().contains(window.usage_label.geometry()))
            self.assertLess(window.usage_label.geometry().bottom(), window.log_view.geometry().top())
            window.btn_debug.click()
            self.assertFalse(window._usage_timer.isActive())
            window.btn_debug.click()
            window.close()
            self.assertFalse(window._usage_timer.isActive())
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
