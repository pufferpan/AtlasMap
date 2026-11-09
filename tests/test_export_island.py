import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.export_window import ExportWindow
from app.parallel_export_windows import ParallelExportWindows


class IslandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def window(self):
        window = ExportWindow()
        window.begin('CollectionRoom', start_rect=QRect(20, 60, 640, 500),
                     target_rect=QRect(20, 60, 640, 500), duration=1)
        QTest.qWait(70)
        return window

    def test_single_live_progress_stop_restore_and_logs(self):
        window = self.window()
        try:
            original = QRect(window.geometry())
            stops = []
            window.stop_requested.connect(lambda: stops.append(True))
            window.btn_hide.click()
            island = window._island
            QTest.qWait(100)
            self.assertEqual(island.state, 'collapsing')
            self.assertEqual(window.geometry(), original)
            self.assertTrue(island.flights)
            self.assertGreater(island.flights[0].image.blur, 0)
            self.assertNotEqual(island.flights[0].image.pixmap.toImage(),
                                island.flights[0].image.blurred.toImage())
            QTest.qWait(500)
            self.assertEqual(island.state, 'collapsed')
            self.assertTrue(window.isHidden())
            self.assertTrue(island.pill.isVisible())
            self.assertEqual(island.pill.size().height(), 52)
            window.feed('LOG_WHILE_COLLAPSED')
            window.set_fraction(.63)
            QTest.qWait(100)
            self.assertEqual(island.fraction(), .63)
            self.assertIn('LOG_WHILE_COLLAPSED', window.log_view.toPlainText())
            island.pill.stop.click()
            island.pill.stop.click()
            self.assertEqual(len(stops), 1)
            QTest.mouseClick(island.pill, Qt.LeftButton)
            QTest.qWait(550)
            self.assertEqual(island.state, 'expanded')
            self.assertTrue(window.isVisible())
            self.assertEqual(window.geometry(), original)
            self.assertFalse(island.pill.isVisible())
        finally:
            window.close()
        self.assertFalse(island.timer.isActive())

    def test_group_completion_collapsed_restores_success_at_same_rects(self):
        group = ParallelExportWindows(None, 2)
        try:
            group.begin('CollectionRoom')
            QTest.qWait(1200)
            self.assertEqual(group._phase, 'ready')
            original = [QRect(w.geometry()) for w in group.windows]
            group.windows[1].btn_hide.click()
            QTest.qWait(550)
            self.assertTrue(all(w.isHidden() for w in group.windows))
            group.set_fraction(.72)
            self.assertEqual(group._island.fraction(), .72)
            group.finish(0)
            QTest.qWait(100)
            self.assertTrue(all(w.isHidden() for w in group.windows))
            self.assertTrue(group._island.pill.stop.isHidden())
            group._island.restore()
            # Image snapshots and other native GUI tests can delay animation
            # frames under load. Wait for its state rather than a 30 ms margin.
            for _ in range(60):
                if group._island.state=='expanded':break
                QTest.qWait(50)
            self.assertTrue(all(w.isVisible() and w._celebration is not None for w in group.windows))
            self.assertEqual([w.geometry() for w in group.windows], original)
            group.show_details()
            group.windows[0].btn_hide.click()
            QTest.qWait(80)
        finally:
            group.close()
        self.assertFalse(group._island.timer.isActive())
        self.assertFalse(group._island.flights)
        self.assertFalse(group._island.pill.isVisible())

    def test_failure_during_collapse_does_not_reopen_window(self):
        window = self.window()
        try:
            window.btn_hide.click()
            window.finish(-1)
            QTest.qWait(600)
            self.assertEqual(window._island.state, 'collapsed')
            self.assertTrue(window.isHidden())
            self.assertTrue(window._island.pill.stop.isHidden())
            window._island.restore()
            for _ in range(60):
                if window._island.state=='expanded':break
                QTest.qWait(50)
            self.assertEqual(window._title, '导出失败')
            self.assertTrue(window.btn_close.isVisible())
        finally:
            window.close()
