"""Project library using native FluentPy controls."""
import os
from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog, QTableWidgetItem, QAbstractItemView
from app import fluent_api as F
from core import exporter, mapnames, projects


class ProjectsPage(QWidget):
    def __init__(self, host):
        super().__init__()
        self.host = host
        self.catalogue = projects.Catalogue()
        self._busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 24)
        title = QLabel('我的工程')
        title.setStyleSheet('font-size:24px;font-weight:600')
        layout.addWidget(title)
        tip = QLabel('按地图名称管理 UE 和 Blender 工程。移动和删除会作用于整个工程文件夹，包括分块与贴图。')
        tip.setWordWrap(True)
        layout.addWidget(tip)
        toolbar = QHBoxLayout()
        self.search = F.LineEdit()
        self.search.setPlaceholderText('搜索地图、工程名称或路径')
        self.search.textChanged.connect(self._filter)
        toolbar.addWidget(self.search, 1)
        self.buttons = []
        for label, callback in [('刷新 / 查找旧工程', self.reload), ('扫描工程文件夹', self._scan), ('添加已有工程', self._add)]:
            button = F.PushButton(label)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
            self.buttons.append(button)
        layout.addLayout(toolbar)
        self.notice = F.WarningNotice(parent=self)
        layout.addWidget(self.notice)
        self.table = F.TableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['工程 / 地图名称', '状态', '工程路径', '备注'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 260)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 380)
        self.table.itemDoubleClicked.connect(lambda *_: self._use())
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        for label, callback in [('选择此工程', self._use), ('打开工程', self._open), ('打开文件夹', self._locate),
                                ('修改名称 / 备注', self._edit), ('移动工程', self._move),
                                ('删除工程', self._delete)]:
            button = F.PushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
            self.buttons.append(button)
        layout.addLayout(actions)
        self.rows = []

    def showEvent(self, event):
        super().showEvent(event)
        if not self._busy:
            self.reload()

    def _error(self, error):
        F.set_warning(self.notice, str(error))

    def reload(self):
        if self._busy:
            return
        def load():
            for project in projects.discover(exporter.load_settings()):
                self.catalogue.register(project)
            return self.catalogue.records()
        self._work(load, self._loaded)

    def _loaded(self, rows):
        self.rows = rows
        self._filter()
        F.set_warning(self.notice, '' if rows else '还没有工程。完成一次导出后会自动加入，也可以点击“添加已有工程”。')

    def _filter(self, *_):
        query = self.search.text().strip().casefold()
        self.visible_rows = [r for r in self.rows if query in (projects.title(r) + r['path'] + ' '.join(r.get('maps', []))).casefold()]
        self.table.setRowCount(len(self.visible_rows))
        for index, record in enumerate(self.visible_rows):
            name = projects.title(record)
            if record.get('name') and record.get('maps'):
                name += '\n' + '、'.join(mapnames.label(m) for m in record['maps'])
            values = (name, '可用' if Path(record['path']).is_file() else '路径失效', record['path'], record.get('note', ''))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(index, column, item)
        self.table.resizeRowsToContents()

    def _selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self.visible_rows):
            self._error('请先在列表中选择一个工程。')
            return None
        return self.visible_rows[row]

    def _work(self, fn, done=None, mutation=False):
        self._busy = True
        if mutation:
            self.host._project_mutation = True
            for page in (self.host.ue_page, self.host.map_page, self.host.tools_page):
                page.setEnabled(False)
        for button in self.buttons:
            button.setEnabled(False)
        self.search.setEnabled(False)
        self.table.setEnabled(False)
        def finished(result):
            self._busy = False
            if mutation:
                self.host._project_mutation = False
                for page in (self.host.ue_page, self.host.map_page, self.host.tools_page):
                    page.setEnabled(True)
            for button in self.buttons:
                button.setEnabled(True)
            self.search.setEnabled(True)
            self.table.setEnabled(True)
            if isinstance(result, Exception):
                self._error(result)
            elif done:
                done(result)
        self.host.run_async(fn, finished)

    def _add(self):
        path, _ = QFileDialog.getOpenFileName(self, '添加已有工程', '', '地图工程 (*.uproject *.blend)')
        if path:
            self._work(lambda: self.catalogue.register(path), lambda _: self.reload())

    def _scan(self):
        directory = QFileDialog.getExistingDirectory(self, '选择存放旧工程的文件夹（查找下两层目录）')
        if directory:
            def scan():
                for path in projects.discover({'ue_export_base': directory}):
                    self.catalogue.register(path)
                return self.catalogue.records()
            self._work(scan, self._loaded)

    def _use(self):
        record = self._selected()
        if not record:
            return
        if not Path(record['path']).is_file():
            self._error('工程路径失效，请重新添加实际的工程文件。')
            return
        if self._exporting():
            return
        page = self.host.ue_page
        blender=Path(record['path']).suffix.lower()=='.blend'
        page.cb_target.setCurrentIndex(page.cb_target.findData('blender' if blender else 'ue'))
        if not blender:page.ed_project.setText(record['path'])
        if record.get('maps'):
            name = record['maps'][0]
            if blender:
                settings=exporter.load_settings();settings.setdefault('blender_projects',{})[name]=record['path'];exporter.save_settings(settings)
            page.cb_map.setEditText(name)
            export = record.get('exports', {}).get(name, {})
            if export.get('root'):
                page.ed_root.setText(str(Path(export['root']).parent))
            if export.get('destination'):
                page.ed_dest.setText(export['destination'])
        self.host.switchTo(page)
        self.host.status('已选择工程：' + projects.title(record))

    def _open(self):
        record = self._selected()
        if record and not self._exporting():
            if Path(record['path']).suffix.lower()=='.blend' and Path(record['path']).is_file():
                import subprocess
                blender=str(exporter.load_settings().get('blender') or '')
                if Path(blender).is_file():subprocess.Popen([blender,record['path']]);return
            if not Path(record['path']).is_file() or not QDesktopServices.openUrl(QUrl.fromLocalFile(record['path'])):
                self._error('无法打开工程，请确认路径有效，并已安装对应的 Blender 或 UE。')

    def _locate(self):
        record = self._selected()
        if record:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(record['path']).parent)))

    def _edit(self):
        record = self._selected()
        if not record:
            return
        dialog = F.ChoiceDialog('修改工程信息', '名称用于工程列表展示；地图资源文件名保持原样。', self, yes='保存')
        name = F.LineEdit(record.get('name') or projects.title(record))
        note = F.TextEdit(record.get('note', ''))
        note.setPlaceholderText('备注（可选）')
        note.setMaximumHeight(120)
        dialog.add_content_widget(name)
        dialog.add_content_widget(note)
        if dialog.exec() == type(dialog).DialogCode.Accepted:
            new_name, new_note = name.text(), note.toPlainText()
            self._work(lambda: self.catalogue.edit(record['path'], new_name, new_note), lambda _: self.reload())

    def _exporting(self):
        if (getattr(self.host, 'job', None) and self.host.job.running) or getattr(self.host, '_cleanup_pending', False):
            self._error('正在导出或处理残留文件，请完成后再操作工程。')
            return True
        return False

    def _confirm(self, title, record, action):
        dialog = F.ChoiceDialog(title, projects.title(record) + '\n' + str(Path(record['path']).parent), self,
                                yes=action, warning='这会操作整个工程文件夹，包括其中所有地图。原始地图导出目录另行保留。')
        return dialog.exec() == type(dialog).DialogCode.Accepted

    def _move(self):
        record = self._selected()
        if not record or self._exporting():
            return
        destination = QFileDialog.getExistingDirectory(self, '选择目标父目录（整个工程会移到这里）')
        if not destination or not self._confirm('移动工程到：' + destination, record, '确认移动'):
            return
        def perform():
            new = projects.move(record['path'], destination)
            self.catalogue.replace_path(record['path'], new)
            return new
        def done(new):
            self._sync_current(record['path'], new)
            self.reload()
        self._work(perform, done, mutation=True)

    def _delete(self):
        record = self._selected()
        if not record or self._exporting() or not self._confirm('删除工程（移到回收站）', record, '移到回收站'):
            return
        def perform():
            projects.recycle(record['path'])
            self.catalogue.forget(record['path'])
        def done(_):
            self._sync_current(record['path'], '')
            self.reload()
        self._work(perform, done, mutation=True)

    def _sync_current(self, old, new):
        page = self.host.ue_page
        if projects.key(page.ed_project.text()) == projects.key(old):
            page.ed_project.setText(new)
