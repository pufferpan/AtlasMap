"""简单导出向导：地图 → 保存位置 → 精度 → 区域，四步点完直接开跑。

给第一次用的人准备的一条直线，不替换原来的高级设置——向导里的选择只是填进
「一键导出」那些控件，跑的还是同一套管线。
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWizard,
                               QWizardPage)

from app.fluent_controls import EditableComboBox, LineEdit
from fluentpy import widgets as W

from app.ui_scale import px as _px
from core import export_quality, mapnames

QUALITY_HINTS = {
    'standard': '标准 · 1K 贴图，兼顾清晰度和大小（推荐）',
    'high': '高清 · 2K 贴图，文件明显变大',
    'original': '原始 · 不缩贴图，最清晰也最大',
}


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet('font-size:17px;font-weight:600;background:transparent;')
    return label


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet('color:#9db3c6;background:transparent;')
    return label


class SimpleWizard(QWizard):
    """走完四步后 `values` 里是要写回主界面的设置。"""

    def __init__(self, parent=None, maps: Optional[List[str]] = None,
                 current: Optional[Dict[str, object]] = None):
        super().__init__(parent)
        self.setWindowTitle('简单导出向导')
        self.resize(_px(720), _px(460))
        self.setWizardStyle(QWizard.ModernStyle)
        self.setButtonText(QWizard.NextButton, '下一步')
        self.setButtonText(QWizard.BackButton, '上一步')
        self.setButtonText(QWizard.FinishButton, '开始导出')
        self.setButtonText(QWizard.CancelButton, '取消')
        self.values: Optional[Dict[str, object]] = None
        current = current or {}
        self._maps = maps or []
        self._region: Optional[Tuple[float, float, float, float]] = current.get('region')  # type: ignore[assignment]
        self._root_for_region = str(current.get('base') or '')

        # 1 地图 ---------------------------------------------------------
        page = QWizardPage()
        page.setTitle('第一步 · 选地图')
        box = QVBoxLayout(page)
        box.addWidget(_title('要导出哪张地图？'))
        self.cb_map = EditableComboBox()
        for name in self._maps:
            self.cb_map.addItem(f'{mapnames.label(name)}  ({name})', name)
        if current.get('map'):
            index = self.cb_map.findData(current['map'])
            if index >= 0:
                self.cb_map.setCurrentIndex(index)
            else:
                self.cb_map.setEditText(str(current['map']))
        box.addWidget(self.cb_map)
        box.addWidget(_hint('列表来自本机扫描到的 pak；也可以直接输入英文代号。'))
        box.addStretch(1)
        self.addPage(page)

        # 2 保存位置 -----------------------------------------------------
        page = QWizardPage()
        page.setTitle('第二步 · 存到哪')
        box = QVBoxLayout(page)
        box.addWidget(_title('导出文件放在哪里？'))
        row = QHBoxLayout()
        self.ed_root = LineEdit(str(current.get('base') or ''))
        self.ed_root.setPlaceholderText('例如 D:/AtlasMaps')
        browse = W.Button('选择…')
        browse.clicked.connect(self._pick_root)
        row.addWidget(self.ed_root, 1)
        row.addWidget(browse)
        box.addLayout(row)
        box.addWidget(_hint('每张地图会在下面单独建一个文件夹，贴图与 .blend 都放里面，'
                            '建议留出 10–30 GB。'))
        box.addStretch(1)
        self.addPage(page)

        # 3 精度 ---------------------------------------------------------
        page = QWizardPage()
        page.setTitle('第三步 · 精度')
        box = QVBoxLayout(page)
        box.addWidget(_title('贴图要多清晰？'))
        self.cb_quality = EditableComboBox()
        for key, label in (('standard', '标准 (1K)'), ('high', '高清 (2K)'), ('original', '原始')):
            self.cb_quality.addItem(label, key)
            self.cb_quality.setItemData(self.cb_quality.count() - 1, QUALITY_HINTS.get(key, ''),
                                        Qt.ToolTipRole)
        index = self.cb_quality.findData(str(current.get('quality') or 'standard'))
        self.cb_quality.setCurrentIndex(max(0, index))
        box.addWidget(self.cb_quality)
        box.addWidget(_hint('精度只改贴图分辨率，不改几何。选「原始」会明显更慢、更大。'))
        box.addStretch(1)
        self.addPage(page)

        # 4 区域 ---------------------------------------------------------
        page = QWizardPage()
        page.setTitle('第四步 · 范围')
        box = QVBoxLayout(page)
        box.addWidget(_title('整张图，还是只导一小块？'))
        row = QHBoxLayout()
        self.lab_region = QLabel('整张图')
        self.bt_region = W.Button('框选区域…')
        self.bt_region.clicked.connect(self._pick_region)
        self.bt_clear = W.Button('恢复整张图')
        self.bt_clear.clicked.connect(self._clear_region)
        row.addWidget(self.lab_region, 1)
        row.addWidget(self.bt_region)
        row.addWidget(self.bt_clear)
        box.addLayout(row)
        box.addWidget(_hint('框选按导出分块裁剪：选中的分块整块保留，边缘会多带一点几何。'
                            '第一次导出还没有平面图，可以先整图导一次再回来框。'))
        box.addStretch(1)
        self.addPage(page)
        self._refresh_region()

    # ------------------------------------------------------------- 交互 --
    def _pick_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, '选导出基目录', self.ed_root.text() or os.path.expanduser('~'))
        if path:
            self.ed_root.setText(path)

    def _root(self) -> str:
        root = self.ed_root.text().strip()
        return root

    def _pick_region(self) -> None:
        from app.region_picker import RegionPicker
        name = str(self.cb_map.currentData() or self.cb_map.currentText() or '')
        root = os.path.join(self._root(), name) if name else ''
        dialog = RegionPicker(self, name, root, self._region)
        if dialog.exec() == RegionPicker.Accepted:
            self._region = dialog.picked
            self._refresh_region()

    def _clear_region(self) -> None:
        self._region = None
        self._refresh_region()

    def _refresh_region(self) -> None:
        if not self._region:
            self.lab_region.setText('整张图')
            return
        low_x, low_y, high_x, high_y = self._region
        self.lab_region.setText(
            f'已选 {(high_x - low_x) / 100:.0f} m × {(high_y - low_y) / 100:.0f} m')

    # ------------------------------------------------------------- 完成 --
    def accept(self) -> None:
        name = str(self.cb_map.currentData() or self.cb_map.currentText() or '').strip()
        base = self._root()
        if not name or not base:
            return
        self.values = {'map': name, 'base': base,
                       'quality': str(self.cb_quality.currentData() or 'standard'),
                       'region': self._region}
        super().accept()


def ask_wizard(parent) -> str:
    """导出前问一句：'wizard' 用向导 / 'direct' 直接导 / 'never' 以后都别问。"""
    from app.fluent_controls import Dialog
    from fluentpy import widgets as W
    dialog = Dialog('要不要用简单导出向导？',
                    '向导会带你走四步：选地图 → 保存位置 → 精度 → 区域。点「用向导」可以一步步来，'
                    '点「直接导出」就用当前设置开跑。', parent)
    dialog.setYesButtonText('用向导')
    dialog.setCancelButtonText('直接导出')
    dialog.yes_button.setAutoDefault(False)
    dialog.cancel_button.setAutoDefault(False)
    answer = {'value': ''}
    skip = W.Button('以后不再询问', dialog)
    skip.clicked.connect(lambda: (answer.update(value='never'), dialog.accept()))
    dialog.add_content_widget(skip)
    accepted = dialog.exec() == W.FramelessDialog.DialogCode.Accepted
    if answer['value'] == 'never':
        return 'never'
    return 'wizard' if accepted else 'direct'
