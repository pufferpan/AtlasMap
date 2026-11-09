"""Exercise native Fluent widgets and preserve existing input/dialog behavior."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from fluentpy import widgets as W
from app import fluent_api as F


class FluentControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        F.apply_fluent_theme(True)

    def test_factories_return_exact_native_types_without_control_subclasses(self):
        pairs=((F.LineEdit(),W.LineEdit),(F.TextEdit(),W.TextEdit),(F.CodeEditor(),W.CodeEdit),
               (F.EditableComboBox(),W.EditableComboBox),(F.SpinBox(),W.SpinBox),
               (F.DoubleSpinBox(),W.DoubleSpinBox),(F.WarningNotice(),W.InfoBar),
               (F.Dialog(),W.FramelessDialog),(F.ChoiceDialog('确认','内容'),W.FramelessDialog),
               (F.PushButton(),W.Button),(F.PrimaryPushButton(),W.AccentButton),
               (F.ComboBox(),W.ComboBox),(F.ProgressBar(),W.ProgressBar))
        for widget,native in pairs:
            self.addCleanup(widget.deleteLater)
            self.assertIs(type(widget),native)
        from app.pages import Section,DocsPage
        card=Section('设置');self.addCleanup(card.deleteLater)
        self.assertIs(type(card),W.SimpleCardWidget)
        page=DocsPage(None);self.addCleanup(page.deleteLater)
        self.assertIs(type(page.list),W.TableWidget)

    def test_no_stock_qt_replacements_or_custom_widget_adapter_classes(self):
        import ast
        from pathlib import Path
        forbidden={'QPushButton','QToolButton','QCheckBox','QRadioButton','QComboBox',
                   'QLineEdit','QTextEdit','QPlainTextEdit','QProgressBar','QSpinBox',
                   'QDoubleSpinBox','QTableWidget','QTableView','QMessageBox','QDialog'}
        root=Path(__file__).resolve().parents[1]/'app'
        for path in root.glob('*.py'):
            tree=ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if isinstance(node,ast.Call):
                    function=node.func
                    name=function.id if isinstance(function,ast.Name) else function.attr if isinstance(function,ast.Attribute) else ''
                    self.assertNotIn(name,forbidden,f'{path.name}:{node.lineno}')
                if path.name in ('fluent_controls.py','fluentpy_adapter.py') and isinstance(node,ast.ClassDef):
                    for base in node.bases:
                        self.assertTrue(isinstance(base,ast.Name) and base.id=='QObject',path.name)

    def test_path_is_value_and_keeps_native_fluent_control(self):
        field=F.LineEdit('D:/Games/DeltaForce')
        self.addCleanup(field.deleteLater)
        self.assertIs(type(field),W.LineEdit)
        self.assertEqual(field.text(),'D:/Games/DeltaForce')
        field.setPlaceholderText('选择路径')
        self.assertEqual(field.text(),'D:/Games/DeltaForce')

    def test_ue_logo_renders_visible_pixels_without_icon_plugin_lookup(self):
        from app.ue_logo import ue_icon
        icon=ue_icon()
        self.assertFalse(icon.isNull())
        pixmap=icon.pixmap(32,32)
        self.assertFalse(pixmap.isNull())
        image=pixmap.toImage()
        self.assertTrue(any(image.pixelColor(x,y).alpha() for x in range(image.width())
                            for y in range(image.height())))

    def test_editable_map_does_not_insert_typed_items(self):
        combo=F.EditableComboBox()
        self.addCleanup(combo.deleteLater)
        combo.addItem('CollectionRoom (CollectionRoom)','CollectionRoom')
        combo.addItem('SpaceCenter (Ma1)','Ma1')
        values=[]
        combo.currentTextChanged.connect(values.append)
        combo.setCurrentIndex(1)
        self.assertEqual(combo.currentData(),'Ma1')
        self.assertIn('SpaceCenter (Ma1)',values)
        combo.setEditText('CustomMap')
        combo.lineEdit().returnPressed.emit()
        self.assertEqual(combo.currentText(),'CustomMap')
        self.assertEqual(combo.count(),2)

    def test_warning_is_embedded_native_infobar(self):
        notice=F.WarningNotice('资源占用会增加')
        self.addCleanup(notice.deleteLater)
        self.assertIs(type(notice),W.InfoBar)
        self.assertFalse(notice.graphicsEffect().isEnabled())
        F.set_warning(notice,'资源占用会增加')
        self.assertEqual(notice.detail(),'资源占用会增加')
        F.set_warning(notice,'')
        self.assertFalse(notice.isVisible())

    def test_document_page_includes_app_docs_and_uses_code_editor(self):
        from app.pages import DocsPage
        page=DocsPage(None)
        self.addCleanup(page.deleteLater)
        self.assertIsInstance(page.view,W.CodeEdit)
        self.assertIn('导出完整日志',page._files)
        self.assertIn('FluentPy 界面与完整日志',page._files)
        old=page.list.rowCount();page.reload()
        self.assertEqual(page.list.rowCount(),old)

    def test_dialog_enter_and_escape_keep_files(self):
        for key in (Qt.Key_Return,Qt.Key_Escape):
            dialog=F.ChoiceDialog('清理残留','是否删除？',yes='删除',no='保留')
            self.addCleanup(dialog.deleteLater)
            self.assertIsInstance(dialog,W.FramelessDialog)
            dialog.open();self.app.processEvents()
            QTest.keyClick(dialog,key)
            self.assertEqual(dialog.result(),QDialog.Rejected)
            self.assertFalse(dialog.isVisible())

    def test_explicit_choice_recorded_before_finished(self):
        dialog=F.ChoiceDialog('清理残留','是否删除？')
        self.addCleanup(dialog.deleteLater)
        chosen=[]
        dialog.finished.connect(lambda _:chosen.append(dialog.result()))
        dialog.yes_button.click()
        self.assertEqual(dialog.result(),QDialog.Accepted)
        self.assertEqual(chosen,[QDialog.Accepted])

    def test_spin_values_remain_visible_and_editable_after_resize(self):
        for control,value in ((F.SpinBox(),8),(F.DoubleSpinBox(),-1.5)):
            self.addCleanup(control.deleteLater)
            control.setRange(-10,16);control.setValue(value)
            control.resize(130,34);control.show();self.app.processEvents()
            self.assertGreater(control.lineEdit().width(),40)
            self.assertTrue(control.lineEdit().text())
            control.stepBy(1)
            self.assertGreater(control.value(),value)
            F.apply_fluent_theme(True,"#D13438");self.app.processEvents()
            self.assertGreater(control.lineEdit().width(),40)
            F.apply_fluent_theme(True)
            control.resize(180,34);self.app.processEvents()
            self.assertGreater(control.lineEdit().width(),100)

    def test_compact_export_footer_has_no_overlapping_actions(self):
        from app.export_window import ExportWindow
        from PySide6.QtCore import QRect
        window=ExportWindow()
        self.addCleanup(window.close)
        window.resize(320,340);window.surfaceRect=QRect(0,0,320,340)
        window.btn_open.show();window._layout()
        self.assertFalse(window.btn_copy.geometry().intersects(window.btn_save_log.geometry()))
        self.assertFalse(window.btn_save_log.geometry().intersects(window.btn_stop.geometry()))
        self.assertLess(window.log_view.geometry().bottom(),window.btn_open.geometry().top())

    def test_code_and_context_menu_preserve_full_copy(self):
        editor=F.CodeEditor('说明\n完整日志')
        self.addCleanup(editor.deleteLater)
        editor.setReadOnly(True)
        self.assertIsInstance(editor,W.CodeEdit)
        called=[]
        F.add_context_action(editor,'导出完整日志',lambda:called.append(True))
        editor.resize(600,240);editor.show();self.app.processEvents()
        editor.text_edit.customContextMenuRequested.emit(QPoint(16,16))
        menu=editor.text_edit._fluent_menu
        self.assertIsInstance(menu,W.ActionMenu)
        actions={action.text():action for action in menu.actions()}
        self.assertNotIn('剪切',actions)
        self.assertNotIn('粘贴',actions)
        actions['复制全部'].trigger()
        self.assertEqual(self.app.clipboard().text(),'说明\n完整日志')
        actions['导出完整日志'].trigger()
        self.assertEqual(called,[True])
        menu.dismiss(immediate=True)


if __name__=='__main__':unittest.main()
