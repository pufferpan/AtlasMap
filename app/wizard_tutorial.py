"""First-run instructions paired with captures of the application's own widgets."""
from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QWidget
from app import fluent_api as F

TUTORIALS = (
    dict(title="先选一张地图", image="tutorial_maps.png", caption="地图库 · 扫描、搜索与导出范围",
         body="在「地图」页点击「扫描地图」，再用中文名或地图代号搜索。选中地图后，确认右侧导出范围和输出目录。",
         bullets="① 扫描当前游戏里的地图，避免选择本包不存在的预设\n\n② 只需要模型与贴图：点击「开始导出」\n\n③ 需要完整 UE 场景：到「一键导出」页面操作"),
    dict(title="三步导出，工程自动保存", image="tutorial_ue.png", caption="一键导出 · 地图、保存位置与高级模式",
         body="默认简易模式只需选择地图和保存位置，再点击「一键导出到 UE」。首次使用会检查 Blender 与 UE；缺少配置时自动展开高级模式。没有工程时会自动创建。",
         bullets="① 选择地图 → 选择英文保存路径 → 一键导出\n\n②「高级模式」统一展开性能设置、引擎路径、渲染参数和分步命令\n\n③「我的工程」按地图名管理结果，可修改名称、移动或移到回收站"),
    dict(title="需要更快？开启性能模式", image="tutorial_performance.png", caption="进 UE · 多进程加速与并行数量",
         body="先打开「高级模式」，再勾选「多进程加速导出（高资源占用）」，阅读资源占用提示后确认。界面会变红，导出时显示各分块的独立窗口。",
         bullets="① 多个 Blender 和 UE 进程分别处理地图分块\n\n② 按电脑内存选择数量；软件也会根据内存余量限制实际并发\n\n③ 内存或磁盘紧张时先关闭此选项，使用普通模式"),
    dict(title="随时掌握导出进度", image="tutorial_progress.png", caption="导出窗口 · 进度、日志、隐藏与终止（界面示例）",
         body="导出窗口会持续显示当前步骤和日志。点击「隐藏」可平滑收起到屏幕顶部的小条，单击小条即可恢复原来的窗口。",
         bullets="① 按 F12 或双击标题区域，查看 CPU 和内存占用\n\n② 点击「导出完整日志」，保存主流程与所有分块输出\n\n③ 点击「终止导出」可停止任务；失败或取消后可选择清理残留"),
)


class TutorialPreview(QWidget):
    def __init__(self, asset, parent=None):
        super().__init__(parent)
        self._asset = asset
        self._pixmap = QPixmap()
        self._scaled = QPixmap()
        self._caption = ""
        self._progress = 1.0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(340)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.valueChanged.connect(self._tick)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("点击查看大图 · 截图中的路径仅作示例")
        self.hide()

    def _tick(self, value):
        self._progress = float(value)
        self.update()

    def show_tutorial(self, tutorial, animated=True):
        self.animation.stop()
        self._pixmap = QPixmap(self._asset(tutorial['image']))
        self._caption = tutorial['caption']
        self._rescale()
        self.show()
        if animated:
            self.animation.start()
        else:
            self._tick(1.0)

    def _rescale(self):
        self._scaled = self._pixmap.scaled(max(1, self.width()-32), max(1, self.height()-116),
                                          Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def resizeEvent(self, event):
        self._rescale()
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(self._progress)
        painter.translate(18*(1-self._progress), 0)
        painter.setPen(QColor('#41638A'))
        painter.setBrush(QColor(9,22,38,240))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1,1,-1,-1), 20, 20)
        painter.setPen(QColor('#EAF4FF'))
        font = QFont(self.font()); font.setPixelSize(17); font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect().adjusted(22,18,-22,-18), Qt.AlignTop|Qt.TextWordWrap, self._caption)
        if not self._scaled.isNull():
            painter.drawPixmap((self.width()-self._scaled.width())//2,
                               66+(self.height()-116-self._scaled.height())//2, self._scaled)
        else:
            painter.drawText(self.rect(), Qt.AlignCenter, '截图加载失败，请查看左侧操作说明')
        font.setPixelSize(12); font.setBold(False); painter.setFont(font)
        painter.setPen(QColor('#A9C4DE'))
        painter.drawText(self.rect().adjusted(22,0,-22,-18), Qt.AlignBottom|Qt.AlignHCenter,
                         '真实软件界面 · 路径仅作示例 · 点击查看大图')

    def mousePressEvent(self, event):
        if event.button()!=Qt.LeftButton or self._pixmap.isNull():
            return super().mousePressEvent(event)
        dialog = F.Dialog(self._caption, parent=self)
        dialog.setYesButtonText('关闭'); dialog.cancel_button.hide()
        area=self.screen().availableGeometry()
        image=QLabel(); image.setAlignment(Qt.AlignCenter)
        image.setPixmap(self._pixmap.scaled(int(area.width()*.85),int(area.height()*.65),
                                          Qt.KeepAspectRatio,Qt.SmoothTransformation))
        dialog.add_content_widget(image)
        dialog.exec()
