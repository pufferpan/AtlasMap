"""框选导出区域：把上一次导出留下来的分块画成平面图，拖一个矩形就选定范围。

平面图来自 `split/manifest.json`（每个分块都带 UE 世界坐标包围盒），所以这张图
只在下过一次整图导出之后才有——导出器本身不给「地图缩略图」，硬凑只会画出错的格子。
没有 manifest 时对话框会说明原因，用户仍可以在下面直接填坐标。
"""
from __future__ import annotations

import json
import os
from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout,
                               QGraphicsScene, QGraphicsView, QLabel, QVBoxLayout)
from app.fluent_controls import DoubleSpinBox

from app.ui_scale import px as _px

PAD = 0.06                      # 平面图四周留白比例


def _levels(manifest_path: str) -> List[dict]:
    try:
        with open(manifest_path, 'r', encoding='utf-8') as handle:
            manifest = json.load(handle)
    except (OSError, ValueError):
        return []
    levels = manifest.get('levels') if isinstance(manifest, dict) else None
    return [row for row in (levels or []) if row.get('ueBoundsMin') and row.get('ueBoundsMax')]


class RegionView(QGraphicsView):
    """支持橡皮筋框选的视图；矩形以 UE 厘米返回。"""

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setRenderHints(self.renderHints())
        self.setBackgroundBrush(QBrush(QColor('#11161d')))
        self.rubberBandChanged.connect(self._changed)
        self.rect_scene: Optional[QRectF] = None

    def _changed(self, _rect, from_scene: QPointF, to_scene: QPointF) -> None:
        if from_scene.isNull() and to_scene.isNull():
            return
        self.rect_scene = QRectF(from_scene, to_scene).normalized()


class RegionPicker(QDialog):
    """返回 (minX, minY, maxX, maxY)，单位 UE 厘米；取消时返回 None。"""

    def __init__(self, parent, map_name: str, root: str,
                 current: Optional[Tuple[float, float, float, float]] = None):
        super().__init__(parent)
        self.setWindowTitle('选择导出区域')
        self.resize(_px(760), _px(560))
        self._levels = _levels(os.path.join(root or '', 'split', 'manifest.json'))
        self._result: Optional[Tuple[float, float, float, float]] = None

        self.scene = QGraphicsScene(self)
        self.view = RegionView(self.scene, self)
        hint = ''
        if not self._levels:
            hint = ('还没有这张图的平面图：先不勾「只导选中区域」整图导一次，'
                    '下次就能在这里框选了。也可以直接在下面填坐标。')
        self.lab_hint = QLabel(hint)
        self.lab_hint.setWordWrap(True)

        box = QVBoxLayout(self)
        box.setContentsMargins(_px(16), _px(14), _px(16), _px(14))
        box.setSpacing(_px(10))
        title = QLabel(f'{map_name or "地图"} · 拖一个矩形选保留范围（按分块裁剪）')
        title.setStyleSheet('font-size:15px;font-weight:600;')
        box.addWidget(title)
        if hint:
            box.addWidget(self.lab_hint)
        box.addWidget(self.view, 1)

        self.spins: List[object] = []
        form = QFormLayout()
        form.setHorizontalSpacing(_px(12))
        from PySide6.QtWidgets import QHBoxLayout, QWidget
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        labels = ('X 最小', 'Y 最小', 'X 最大', 'Y 最大')
        for label, value in zip(labels, current or (0, 0, 0, 0)):
            spin = DoubleSpinBox(self)
            spin.setRange(-400000.0, 400000.0)
            spin.setDecimals(1)
            spin.setSingleStep(100.0)
            spin.setSuffix(' cm')
            spin.setValue(float(value))
            spin.valueChanged.connect(self._spins_changed)
            self.spins.append(spin)
            line.addWidget(QLabel(label))
            line.addWidget(spin)
        form.addRow('范围', row)
        box.addLayout(form)

        buttons = QDialogButtonBox(self)
        self.bt_clear = buttons.addButton('清除区域', QDialogButtonBox.ResetRole)
        buttons.addButton('取消', QDialogButtonBox.RejectRole)
        self.bt_ok = buttons.addButton('用这个范围', QDialogButtonBox.AcceptRole)
        self.bt_clear.clicked.connect(self._clear)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)

        self._preview = None
        self._draw()
        self.view.rubberBandChanged.connect(self._band)
        if current:
            self._preview_from_spins()
        self._spins_changed()

    def showEvent(self, event) -> None:                  # noqa: N802  Qt 命名
        super().showEvent(event)
        if getattr(self, 'bounds', None):
            self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event) -> None:                # noqa: N802  Qt 命名
        super().resizeEvent(event)
        if getattr(self, 'bounds', None):
            self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    # ------------------------------------------------------------- 绘制 --
    def _draw(self) -> None:
        if not self._levels:
            return
        low_x = min(float(row['ueBoundsMin'][0]) for row in self._levels)
        low_y = min(float(row['ueBoundsMin'][1]) for row in self._levels)
        high_x = max(float(row['ueBoundsMax'][0]) for row in self._levels)
        high_y = max(float(row['ueBoundsMax'][1]) for row in self._levels)
        self.bounds = (low_x, low_y, high_x, high_y)
        span_x = max(1.0, high_x - low_x)
        span_y = max(1.0, high_y - low_y)
        self.scene.setSceneRect(QRectF(low_x - span_x * PAD, -high_y - span_y * PAD,
                                       span_x * (1 + 2 * PAD), span_y * (1 + 2 * PAD)))
        pen = QPen(QColor('#20303f'), 0)
        for index, row in enumerate(self._levels):
            x0, y0 = float(row['ueBoundsMin'][0]), float(row['ueBoundsMin'][1])
            x1, y1 = float(row['ueBoundsMax'][0]), float(row['ueBoundsMax'][1])
            shade = QColor('#1b2b3a') if index % 2 else QColor('#20374a')
            item = self.scene.addRect(QRectF(x0, -y1, max(1.0, x1 - x0), max(1.0, y1 - y0)),
                                      pen, QBrush(shade))
            item.setToolTip(f"{row.get('file', '')} · {row.get('level', '')}\n"
                            f"{row.get('instances', 0)} 个实例")
            item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, False)
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def _band(self, _rect, from_scene: QPointF, to_scene: QPointF) -> None:
        if from_scene.isNull() and to_scene.isNull():
            return
        rect = QRectF(from_scene, to_scene).normalized()
        values = (rect.left(), -rect.bottom(), rect.right(), -rect.top())
        self._block(True)
        for spin, value in zip(self.spins, values):
            spin.setValue(round(value, 1))
        self._block(False)
        self._preview_from_spins()

    # ------------------------------------------------------------- 数值 --
    def _block(self, value: bool) -> None:
        for spin in self.spins:
            spin.blockSignals(value)

    def _spins_changed(self) -> None:
        self._preview_from_spins()

    def _preview_from_spins(self) -> None:
        region = self.region()
        if self._preview is not None:
            self.scene.removeItem(self._preview)
            self._preview = None
        if not region:
            self.bt_ok.setEnabled(False)
            return
        self.bt_ok.setEnabled(True)
        low_x, low_y, high_x, high_y = region
        self._preview = self.scene.addRect(
            QRectF(low_x, -high_y, high_x - low_x, high_y - low_y),
            QPen(QColor('#4fb0ff'), 0, Qt.DashLine), QBrush(QColor(79, 176, 255, 48)))
        self._preview.setZValue(5)

    def _clear(self) -> None:
        self._block(True)
        for spin in self.spins:
            spin.setValue(0.0)
        self._block(False)
        self._result = None
        self._spins_changed()

    def region(self) -> Optional[Tuple[float, float, float, float]]:
        values = [spin.value() for spin in self.spins]
        low_x, high_x = sorted((values[0], values[2]))
        low_y, high_y = sorted((values[1], values[3]))
        if high_x - low_x < 1.0 or high_y - low_y < 1.0:
            return None
        return low_x, low_y, high_x, high_y

    def accept(self) -> None:
        self._result = self.region()
        super().accept()

    @property
    def picked(self) -> Optional[Tuple[float, float, float, float]]:
        return self._result
