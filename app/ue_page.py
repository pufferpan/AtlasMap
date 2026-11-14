"""「进 UE」页：把模型导出 → Blender 三段 → UE 七阶段 → 补灯/碰撞 的完整步骤摆出来。

每一步都给一条可以直接粘进 PowerShell 的命令；路径按界面里填的引擎/工程/导出目录自动拼。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QGuiApplication, QPixmap
from PySide6.QtWidgets import (QCompleter,QFrame,QFileDialog,QHBoxLayout,QLabel,QVBoxLayout,QWidget)

from app import fluent_api as F
from app.ui_scale import px as _px
from core import exporter, mapnames, ue_pipeline, export_quality
from app.ue_logo import ue_icon

UE_VERSIONS = ("5.4", "5.3", "5.5")


def _label(text: str, size: int = 13, bold: bool = False, color: Optional[str] = None) -> QLabel:
    lab = QLabel(text)
    font = QFont(lab.font())
    font.setPixelSize(_px(size))
    font.setBold(bold)
    lab.setFont(font)
    lab.setStyleSheet(f"color:{color};background:transparent;" if color else "background:transparent;")
    lab.setWordWrap(True)
    return lab


def _card() -> Tuple[QWidget, QVBoxLayout]:
    frame = F.SimpleCardWidget()
    box = QVBoxLayout(frame)
    box.setContentsMargins(_px(16), _px(14), _px(16), _px(14))
    box.setSpacing(_px(8))
    return frame, box


def _detect_blender() -> str:
    """常见 Blender 安装位置。"""
    cands = [
        os.path.join("G:" + os.sep, "SteamLibrary", "steamapps", "common", "Blender", "blender.exe"),
        os.path.join("D:" + os.sep, "SteamLibrary", "steamapps", "common", "Blender", "blender.exe"),
        os.path.join("C:" + os.sep, "Program Files", "Blender Foundation",
                     "Blender 5.2", "blender.exe"),
        os.path.join("C:" + os.sep, "Program Files", "Blender Foundation",
                     "Blender 5.1", "blender.exe"),
        os.path.join("C:" + os.sep, "Program Files", "Blender Foundation",
                     "Blender 4.5", "blender.exe"),
    ]
    for path in cands:
        if os.path.isfile(path):
            return path
    return ""


def _detect_engine() -> str:
    """在常见盘符里找 UnrealEditor.exe。"""
    for ver in UE_VERSIONS:
        for drive in ("E:", "D:", "C:", "F:", "G:"):
            exe = os.path.join(f"{drive}\\", f"UE_{ver}", "Engine", "Binaries", "Win64",
                               "UnrealEditor.exe")
            if os.path.isfile(exe):
                return exe
    return ""


def _app_root() -> str:
    return exporter.runtime_root()


class UePage(QWidget):
    """完整 UE 流程。"""

    def __init__(self, win, shell) -> None:
        super().__init__()
        self.win = win
        self.shell = shell
        self._settings = exporter.load_settings()
        self._map_counts = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = F.scroll_area()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        body = QWidget()
        scroll.setWidget(body)
        box = QVBoxLayout(body)
        box.setContentsMargins(_px(28), _px(18), _px(28), _px(24))
        box.setSpacing(_px(12))

        box.addWidget(_label("一键导出地图", 20, True))
        box.addWidget(_label('选择地图和保存位置，然后点击“一键导出”。完成的工程可在“我的工程”中管理。', 13))
        mode_row = QHBoxLayout()
        self.advanced_switch = F.ToggleSwitch()
        self.advanced_switch.setAccessibleName('高级模式')
        self.advanced_switch.setChecked(bool(self._settings.get('advanced_mode', False)))
        mode_row.addWidget(_label('高级模式', 13, True))
        mode_row.addWidget(self.advanced_switch)
        mode_row.addWidget(_label('展开引擎路径、性能设置、渲染参数和分步命令', 12), 1)
        box.addLayout(mode_row)
        self._advanced_widgets = []

        # ---------------- 一键全自动 ----------------
        auto_card, auto_box = _card()
        auto_head = QHBoxLayout()
        logo = self.export_logo = QLabel()
        logo.setPixmap(ue_icon().pixmap(QSize(_px(30), _px(30))))
        auto_head.addWidget(logo)
        auto_head.addWidget(_label("一键导出地图工程", 15, True), 1)
        self.cb_target=F.ComboBox()
        self.cb_target.addItem('Unreal Engine 工程','ue')
        self.cb_target.addItem('Blender 工程（.blend）','blender')
        self.cb_target.setCurrentIndex(max(0,self.cb_target.findData(self._settings.get('export_target','ue'))))
        auto_head.addWidget(self.cb_target)
        auto_box.addLayout(auto_head)
        auto_box.addWidget(_label(
            "点击下方按钮后自动处理地图、材质和灯光。进度窗口会显示当前步骤；完成后可直接打开工程查看。", 13))
        row_auto = QHBoxLayout()
        row_auto.setSpacing(_px(8))
        self.btn_auto = F.PushButton("一键导出到 UE")
        self.btn_auto.setIcon(ue_icon())
        self.btn_auto.clicked.connect(self._run_all)
        row_auto.addWidget(self.btn_auto)
        self.btn_open_ue = F.PushButton("打开引擎看结果")
        self.btn_open_ue.clicked.connect(self._open_editor)
        row_auto.addWidget(self.btn_open_ue)
        self.btn_render = F.PushButton("游戏光照渲染预览")
        self.btn_render.clicked.connect(self._render_preview)
        row_auto.addWidget(self.btn_render)
        row_auto.addStretch(1)
        auto_box.addLayout(row_auto)
        parallel_row = QHBoxLayout()
        self.chk_parallel = F.CheckBox('多进程加速导出（高资源占用）')
        self.chk_parallel.setChecked(bool(self._settings.get('parallel_export', False)))
        parallel_row.addWidget(self.chk_parallel)
        parallel_row.addWidget(_label('并行进程数量', 12))
        from app.parallel_export_windows import desktop_capacity
        self.sp_parallel = F.SpinBox()
        self.sp_parallel.setRange(2, desktop_capacity())
        self.sp_parallel.setValue(int(self._settings.get('parallel_processes', 2)))
        self.sp_parallel.setEnabled(self.chk_parallel.isChecked())
        parallel_row.addWidget(self.sp_parallel)
        self.chk_memlimit = F.CheckBox('按内存余量限制并发')
        self.chk_memlimit.setChecked(bool(self._settings.get('mem_limit', True)))
        self.chk_memlimit.setToolTip('勾选：按当前可用物理内存和提交内存自动收紧并发，避免进程多到把内存吃光；'
                                     '不勾：严格按上面的「并行进程数量」跑（内存不够时仍会降为单进程重试）')
        parallel_row.addWidget(self.chk_memlimit)

        region_row = QHBoxLayout()
        self.chk_region = F.CheckBox('只导出选中区域')
        self.chk_region.setToolTip('先在平面图上框一块，导出时只保留落在里面的分块')
        self.chk_region.setChecked(bool(self._settings.get('ue_region')))
        region_row.addWidget(self.chk_region)
        self.btn_region = F.PushButton('框选…')
        self.btn_region.setToolTip('打开平面图，拖一个矩形选保留范围')
        self.btn_region.clicked.connect(self._pick_region)
        region_row.addWidget(self.btn_region)
        self.lab_region = QLabel()
        self.lab_region.setStyleSheet('color:#9db3c6;background:transparent;')
        region_row.addWidget(self.lab_region, 1)
        self._refresh_region_text()
        parallel_row.addStretch(1)
        auto_box.addLayout(parallel_row)
        auto_box.addWidget(_label('开启后界面变红，独立进程分块处理地图；默认会按内存余量收紧并发，可用「按内存余量限制并发」关掉，每个窗口显示自己的任务。', 12))
        self.chk_game_lighting = F.CheckBox("游戏光照兼容：抑制泛白并保留高光细节")
        self.chk_game_lighting.setChecked(self._settings.get('render_profile','game')=='game')
        self.chk_game_lighting.setToolTip('作用于导入后的 UE 工程和预览；原始灯光与烘焙数据保持不变。游戏专用 PRT 仍存在兼容差异。')
        auto_box.addWidget(self.chk_game_lighting)
        self.chk_supplemental = F.CheckBox("缺少环境灯时添加预览补光")
        self.chk_supplemental.setChecked(self._settings.get('lighting_mode') == 'supplemental')
        auto_box.addWidget(self.chk_supplemental)
        view_row = QHBoxLayout()
        view_row.addWidget(_label('渲染视角',12))
        self.cb_render_view = F.ComboBox()
        for label,value in (('自动选择','auto'),('全图俯视','overview'),('光照区域','lights')):
            self.cb_render_view.addItem(label,value)
        self.cb_render_view.setCurrentIndex(max(0,self.cb_render_view.findData(self._settings.get('render_view','auto'))))
        view_row.addWidget(self.cb_render_view)
        view_row.addWidget(_label('预览曝光补偿 EV',12))
        self.sp_render_ev=F.DoubleSpinBox()
        self.sp_render_ev.setRange(-10,10)
        self.sp_render_ev.setSingleStep(.5)
        self.sp_render_ev.setValue(float(self._settings.get('render_ev',0)))
        self.sp_render_ev.setToolTip('只调整预览，不改变导出的原始游戏数据')
        view_row.addWidget(self.sp_render_ev)
        view_row.addStretch(1)
        auto_box.addLayout(view_row)
        box.addWidget(auto_card)

        # ---------------- 环境卡片 ----------------
        env_card, env_box = _card()
        env_box.addWidget(_label("地图与保存位置", 15, True))

        det = _detect_engine()
        self.ed_engine = self._row(env_box, "引擎", det or self._settings.get("ue_engine", ""),
                                   "选 UnrealEditor.exe",
                                   lambda: self._pick_file("选 UnrealEditor.exe",
                                                           "程序 (*.exe)"))
        self.ed_project = self._row(env_box, "工程",
                                    self._settings.get("ue_project", ""),
                                    "选 .uproject（没有就点右边的「新建…」）",
                                    lambda: self._pick_file("选 .uproject",
                                                            "虚幻工程 (*.uproject)"))
        row_proj = env_box.itemAt(env_box.count() - 1).layout()
        btn_new = F.PushButton("新建…")
        btn_new.clicked.connect(self._create_project)
        row_proj.addWidget(btn_new)
        self.ed_blender = self._row(env_box, "Blender",
                                    self._settings.get("blender", "") or _detect_blender(),
                                    "选 blender.exe", lambda: self._pick_file("选 blender.exe",
                                                                              "程序 (*.exe)"))
        legacy_root = str(self._settings.get("ue_root") or "").rstrip("/\\")
        base = (self._settings.get("ue_export_base") or os.path.dirname(legacy_root)
                or self._settings.get("outdir", ""))
        self.ed_root = self._row(env_box, "导出基目录", base,
                                 "每张地图自动保存到此目录下的同名子目录", self._pick_root)
        map_row = QHBoxLayout()
        map_row.addWidget(_label("选择地图", 13))
        self.cb_map = F.EditableComboBox()
        self.cb_map.setMinimumWidth(_px(260))
        self.ed_map = self.cb_map.lineEdit()
        self.ed_map.setPlaceholderText("搜索中文名或地图代号，也可输入代号")
        self._fill_maps(str(self._settings.get("ue_map") or ""))
        map_row.addWidget(self.cb_map, 1)
        self.btn_scan_maps = F.PushButton("扫描游戏地图")
        self.btn_scan_maps.clicked.connect(self._scan_maps)
        map_row.addWidget(self.btn_scan_maps)
        self.btn_current_map = F.PushButton("使用地图库所选地图")
        self.btn_current_map.clicked.connect(self._use_current_map)
        map_row.addWidget(self.btn_current_map)
        self.btn_generic = F.PushButton("其他游戏…")
        self.btn_generic.setToolTip("导出任意 UE 游戏的单张 .umap；加密的包会一个个问我要密钥")
        self.btn_generic.clicked.connect(self._open_generic)
        map_row.addWidget(self.btn_generic)
        env_box.addLayout(map_row)
        initial_map = self._map_name()
        self.ed_dest = self._row(env_box, "UE 资源目录",
                                 "/Game/AtlasMaps/" + initial_map if initial_map else "",
                                 "导入到工程里的哪个目录", None, editable=True)
        self._last_map = initial_map
        thread_row = QHBoxLayout()
        thread_row.addWidget(_label("并行准备线程", 13))
        self.sp_workers = F.SpinBox()
        self.sp_workers.setRange(1, min(16, os.cpu_count() or 1))
        self.sp_workers.setValue(int(self._settings.get("ue_workers", min(8, os.cpu_count() or 1))))
        thread_row.addWidget(self.sp_workers)
        thread_row.addWidget(_label("文件校验并行，支持的资源使用 UE 后台导入任务", 12), 1)
        env_box.addLayout(thread_row)
        self.lab_target = _label("", 12, color="#9aa4b2")
        env_box.addWidget(self.lab_target)
        self.lab_warn = F.WarningNotice(parent=self)
        env_box.addWidget(self.lab_warn)
        box.addWidget(env_card)
        from app.export_quality import QualityPanel
        self.quality=QualityPanel(self.win,self._scan_maps,self)
        box.addWidget(self.quality.card)

        # ---------------- 步骤 ----------------
        self._steps: List[Tuple[str, str, QWidget]] = []
        box.addWidget(self._build_step(
            "② 导出 split（导出器）",
            "一条命令把地图的静态几何/贴图导成 split 分块，`--max-tex 512` 可以先跑快的，"
            "要原图就改 0。", self._cmd_export))
        box.addWidget(self._build_step(
            "③ Blender ①：split → .blend",
            "直接读取所选地图的 split 分块，不需要创建目录软链。",
            self._cmd_blender1, extra="mkdir"))
        box.addWidget(self._build_step(
            "④ Blender ②：.blend → FBX + 贴图 + manifest",
            "每个唯一网格导一个 FBX（几何带世界坐标），贴图和材质节点图一起打包。",
            self._cmd_blender2))
        box.addWidget(self._build_step(
            "⑤ Blender ③：材质计划",
            "把节点图编译成 UE 能落地的母材质 + 实例计划。",
            self._cmd_blender3))
        box.addWidget(self._build_step(
            "⑥ UE 七阶段导入",
            "textures → meshes → masters → instances → bindings → actors → parents；"
            "命令行没有 GUI 帧，脚本自己推状态机，跑完自动存关卡。中断了可以用 "
            "`ATLASMAP_UE_SKIP` / `ATLASMAP_UE_START` 续跑。", self._cmd_ue))
        box.addWidget(self._build_step(
            "⑦ 还原灯光 + 补碰撞",
            "按源数据还原点光、聚光、矩形光、太阳和天光，保留原地图昼夜效果；可单独启用预览补光。"
            "补碰撞：把所有静态网格设为「复杂碰撞当简单用」，能站人能打射线。",
            self._cmd_finish))

        # ---------------- 结尾说明 ----------------
        note_card, note_box = _card()
        note_box.addWidget(_label("说明", 15, True))
        note_box.addWidget(_label(
            "· 导出目录和工程路径都必须是 ASCII，命令行里中文会被 UE 转成 ?。\n"
            "· 导入时请先保存并关闭这个工程的 UE 编辑器，避免工程被占用。\n"
            "· 打开关卡后几何在很远的地方，视口里点一下 → Ctrl+A → F 就能框住。\n"
            "· 官方的 `ue_iceland_source_lighting.py` / `ue_rebuild_iceland_water.py` / "
            "`ue_rebuild_iceland_collision.py` 依赖作者工作区的审计数据（`out/Iceland/...`），"
            "没有那份数据跑不了；原游戏的烘焙光照和自定义天空/GI 无法直接还原，第 ⑦ 步会记录兼容处理。", 12,
            color="#9aa4b2"))
        box.addWidget(note_card)

        row = QHBoxLayout()
        row.setSpacing(_px(8))
        btn_all = F.PushButton("复制全部步骤")
        btn_all.clicked.connect(self._copy_all)
        btn_ps1 = F.PushButton("导出为 .ps1")
        btn_ps1.clicked.connect(self._export_ps1)
        row.addWidget(btn_all)
        row.addWidget(btn_ps1)
        row.addStretch(1)
        box.addLayout(row)
        box.addStretch(1)
        box.removeWidget(env_card)
        box.insertWidget(3, env_card)
        box.removeWidget(self.quality.card)
        box.insertWidget(4,self.quality.card)

        def collect(item,destination=None):
            destination=self._advanced_widgets if destination is None else destination
            if item.widget():
                destination.append(item.widget())
            elif item.layout():
                for i in range(item.layout().count()):
                    collect(item.layout().itemAt(i),destination)
        for i in range(3, auto_box.count()):
            collect(auto_box.itemAt(i))
        for i in (1, 2, 3, 6, 7):
            collect(env_box.itemAt(i))
        self._advanced_widgets.extend([note_card, btn_all, btn_ps1, self.btn_current_map, self.btn_render])
        self._ue_only_widgets=[self.btn_render,note_card,btn_all,btn_ps1]
        for i in (1,2,6,7):collect(env_box.itemAt(i),self._ue_only_widgets)
        for i in (5,6,7):collect(auto_box.itemAt(i),self._ue_only_widgets)
        self.advanced_switch.toggled.connect(self._advanced_changed)
        self._apply_advanced(self.advanced_switch.isChecked())

        for edit in (self.ed_engine, self.ed_blender, self.ed_project):
            edit.textChanged.connect(self._refresh)
        self.cb_map.currentTextChanged.connect(self._refresh)
        for edit in (self.ed_root, self.ed_dest):
            edit.textChanged.connect(self._refresh)
        self.sp_workers.valueChanged.connect(self._refresh)
        self.chk_parallel.toggled.connect(self._parallel_toggled)
        self.sp_parallel.valueChanged.connect(self._refresh)
        self.chk_region.toggled.connect(self._region_toggled)
        self.chk_supplemental.toggled.connect(self._refresh)
        self.chk_game_lighting.toggled.connect(self._refresh)
        self.cb_render_view.currentIndexChanged.connect(self._save)
        self.sp_render_ev.valueChanged.connect(self._save)
        self.cb_target.currentIndexChanged.connect(self._target_changed)
        self.quality.combo.currentIndexChanged.connect(self._refresh)
        self._target_changed()

    # ------------------------------------------------------------------ #
    def _apply_advanced(self, enabled):
        for widget in self._advanced_widgets:
            widget.setVisible(enabled)
        if self.cb_target.currentData()=='blender':
            for widget in self._ue_only_widgets:widget.hide()
            for _,_,editor in self._steps[2:]:editor.parentWidget().hide()

    def _target_changed(self,*_):
        blender=self.cb_target.currentData()=='blender'
        self.btn_auto.setText('一键导出到 Blender' if blender else '一键导出到 UE')
        self.btn_open_ue.setText('打开 Blender 工程' if blender else '打开引擎看结果')
        if blender:self.export_logo.setPixmap(QPixmap());self.export_logo.setText('B')
        else:self.export_logo.setText('');self.export_logo.setPixmap(ue_icon().pixmap(QSize(_px(30),_px(30))))
        self._apply_advanced(self.advanced_switch.isChecked());self._refresh()

    def _advanced_changed(self, enabled):
        self._apply_advanced(enabled)
        settings = exporter.load_settings()
        settings['advanced_mode'] = enabled
        exporter.save_settings(settings)
        if hasattr(self.win, 'set_advanced_mode'):
            self.win.set_advanced_mode(enabled)
        self._refresh()

    def _row(self, parent: QVBoxLayout, title: str, value: str, placeholder: str,
             picker, editable: bool = True):
        line = QHBoxLayout()
        line.setSpacing(_px(8))
        line.addWidget(_label(title, 13))
        edit = F.LineEdit(str(value or ""))
        edit.setPlaceholderText(placeholder)
        edit.setReadOnly(not editable)
        line.addWidget(edit, 1)
        if picker is not None:
            btn = F.PushButton("选择…")
            def choose():
                value = picker()
                if value:
                    edit.setText(value)
            btn.clicked.connect(choose)
            line.addWidget(btn)
        parent.addLayout(line)
        return edit

    def _pick_root(self) -> str:
        return QFileDialog.getExistingDirectory(self, "选择导出基目录", self.ed_root.text())

    def _map_name(self) -> str:
        text = self.ed_map.text().strip()
        index = self.cb_map.currentIndex()
        if index >= 0 and text == self.cb_map.itemText(index):
            return str(self.cb_map.itemData(index) or "")
        for name in self._map_names:
            if name.lower() == text.lower():
                return name
        matches = [name for name in self._map_names if mapnames.label(name) == text]
        return matches[0] if len(matches) == 1 else text

    def _fill_maps(self, selected: str) -> None:
        self.cb_map.blockSignals(True)
        self.ed_map.blockSignals(True)
        self._map_names = sorted(set(mapnames.known()) | set(self._map_counts)
                                 | {str(p.get("map")) for p in exporter.load_presets(exporter.find_exe())})
        self.cb_map.clear()
        for name in self._map_names:
            count = self._map_counts.get(name)
            suffix = f" · {count} 文件" if count is not None else ""
            self.cb_map.addItem(f"{mapnames.label(name)} ({name}){suffix}", name)
        completer = QCompleter([self.cb_map.itemText(i) for i in range(self.cb_map.count())], self.cb_map)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.cb_map.setCompleter(completer)
        self.cb_map.setCurrentIndex(self.cb_map.findData(selected))
        if self.cb_map.currentIndex() < 0:
            self.cb_map.setEditText(selected)
        self.cb_map.blockSignals(False)
        self.ed_map.blockSignals(False)

    def _scan_maps(self) -> None:
        if not self.btn_scan_maps.isEnabled():return
        exe = exporter.find_exe()
        if not exe:
            self.shell.status("没找到 map-export.exe，先去设置中指定")
            return
        self.btn_scan_maps.setEnabled(False)
        self.quality.scan_button.setEnabled(False)
        self.btn_scan_maps.setText("扫描中…")
        self.win.run_async(lambda: exporter.list_maps(exe), self._maps_scanned)

    def _maps_scanned(self, result) -> None:
        self.btn_scan_maps.setEnabled(True)
        self.quality.scan_button.setEnabled(True)
        self.quality.reload()
        self.btn_scan_maps.setText("扫描游戏地图")
        if isinstance(result, Exception):
            self.shell.status(f"扫描失败：{result}")
            return
        selected = self._map_name()
        self._map_counts = dict(result)
        self._fill_maps(selected)
        self._refresh()
        self.shell.status(f"扫描完成：{len(result)} 张地图，可搜索中文名或代号")

    def _cleanup_after_export(self, root: str, map_name: str) -> None:
        """导出成功后清掉预览缓存、分块原始文件等中间产物（可在设置里关）。"""
        settings = exporter.load_settings()
        if not bool(settings.get('auto_clean', True)):
            return
        keep_raw = bool(settings.get('keep_raw', False))
        from core import cleanup
        try:
            self.shell.status('正在清理临时文件…')
            result = cleanup.clean(root, include_raw=not keep_raw)
        except OSError as error:
            self.shell.status('临时文件清理失败：' + str(error))
            return
        message = cleanup.describe(result)
        self.shell.status(message)
        try:
            self.win.feed(message)
        except Exception:                                   # noqa: BLE001
            pass

    def _open_generic(self) -> None:
        """其他游戏（通用 UE 工程）：单独一个对话框，不动当前地图库。"""
        from app.generic_dialog import GenericDialog
        dialog = GenericDialog(self, oodle=str(self._settings.get("oodle") or ""),
                               blender=self.ed_blender.text().strip())
        dialog.exec()

    def _use_current_map(self) -> None:
        name = self.win.map_page._current
        if name:
            index = self.cb_map.findData(name)
            if index >= 0:
                self.cb_map.setCurrentIndex(index)
            else:
                self.cb_map.setEditText(name)
        else:
            self.shell.status("先在地图库中选择一张地图")

    def _pick_file(self, title: str, flt: str) -> str:
        path, _ = QFileDialog.getOpenFileName(self, title, "", flt)
        if path:
            return path
        return ""

    # ------------------------------------------------------------ 工程 --
    def _engine_assoc(self) -> str:
        text = self.ed_engine.text().strip()
        for ver in ("5.5", "5.4", "5.3"):
            if f"UE_{ver}" in text or f"UE {ver}" in text:
                return ver
        return "5.4"

    def _write_project(self, project_root: str) -> str:
        """在 project_root 里写一个能跑 Python 脚本的空工程，返回 .uproject 路径。"""
        name = os.path.basename(project_root.rstrip(chr(92) + "/")) or "AtlasMapUE"
        os.makedirs(os.path.join(project_root, "Config"), exist_ok=True)
        os.makedirs(os.path.join(project_root, "Content"), exist_ok=True)
        uproject = os.path.join(project_root, name + ".uproject")
        data = {
            "FileVersion": 3,
            "EngineAssociation": self._engine_assoc(),
            "Category": "",
            "Description": "AtlasMap 导入用空工程",
            "Plugins": [
                {"Name": "PythonScriptPlugin", "Enabled": True},
                {"Name": "EditorScriptingUtilities", "Enabled": True},
                {"Name": "GeometryScripting", "Enabled": True},
            ],
        }
        with open(uproject, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        ini = os.path.join(project_root, "Config", "DefaultEngine.ini")
        lines = [
            "[/Script/EngineSettings.GameMapsSettings]",
            "EditorStartupMap=/Engine/Maps/Entry",
            "GameDefaultMap=/Engine/Maps/Entry",
            "",
            "[/Script/Engine.RendererSettings]",
            "r.DynamicGlobalIlluminationMethod=1",
            "r.ReflectionMethod=1",
            "r.GenerateMeshDistanceFields=True",
            "",
        ]
        with open(ini, "w", encoding="utf-8") as fh:
            fh.write(chr(10).join(lines))
        return uproject

    def _ensure_project(self) -> Optional[str]:
        """没工程就自己造一个，放在导出目录的父目录下，名字固定 AtlasMapUE。

        父目录不是 ASCII 时退到 LOCALAPPDATA/AtlasMap/UEProject，保证一键能跑。
        """
        current = self.ed_project.text().strip()
        if current and os.path.isfile(current):
            return current

        p = self._paths()
        base = os.path.dirname(p["root"].rstrip(chr(92) + "/"))
        if not base or any(ord(ch) > 127 for ch in base):
            base = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                                "AtlasMap", "UEProject")
        target = os.path.join(base, "AtlasMapUE")
        uproject = os.path.join(target, "AtlasMapUE.uproject")
        try:
            good = False
            if os.path.isfile(uproject) and os.path.getsize(uproject) > 0:
                try:
                    with open(uproject, "r", encoding="utf-8") as fh:
                        good = bool(json.load(fh).get("FileVersion"))
                except Exception:                            # noqa: BLE001
                    good = False
            if not good:                                     # 不存在 / 空文件 / 坏 JSON 都重写
                self._write_project(target)
            self.ed_project.setText(uproject)
            self._save()
            try:
                self.shell.status(f"已自动准备工程：{uproject}")
            except Exception:                                # noqa: BLE001
                pass
            return uproject
        except Exception as exc:                             # noqa: BLE001
            try:
                self.shell.status(f"自动建工程失败：{exc}")
            except Exception:                                # noqa: BLE001
                pass
            return None

    def _create_project(self) -> None:
        """按钮版：让用户挑目录，然后写一个空工程。"""
        base = QFileDialog.getExistingDirectory(self, "选一个空目录放工程（建议 ASCII 路径）",
                                                "C:/")
        if not base:
            return
        try:
            uproject = self._write_project(os.path.join(base.replace("/", os.sep), "AtlasMapUE"))
            self.ed_project.setText(uproject)
            self._save()
            self.shell.status(f"已新建工程：{uproject}")
        except Exception as exc:                             # noqa: BLE001
            self.shell.status(f"新建失败：{exc}")

    def _ask(self, title: str, flt: str, target) -> None:
        path, _ = QFileDialog.getOpenFileName(self, title, "", flt)
        if path:
            target.setText(path)
            self._save()

    def _parallel_toggled(self, enabled):
        if enabled:
            confirmed = F.confirm(self, '开启多进程加速',
                '打开此选项后导出速度会提升很多，但是资源占用也会暴涨，请考虑好')
            if not confirmed:
                self.chk_parallel.blockSignals(True)
                self.chk_parallel.setChecked(False)
                self.chk_parallel.blockSignals(False)
                enabled = False
        self.sp_parallel.setEnabled(enabled)
        self.chk_memlimit.setEnabled(enabled)
        if hasattr(self.win, 'set_parallel_theme'):
            self.win.set_parallel_theme(enabled)
        if enabled:
            from app.performance_effect import show_performance_effect
            show_performance_effect(self.win,self.sp_parallel.value())
        self._refresh()

    # ---------------------------------------------------------- 区域导出 --
    def _region(self):
        """返回 (minX,minY,maxX,maxY)，单位 UE 厘米；没勾就用整张图。"""
        if not self.chk_region.isChecked():
            return None
        from core.region import normalize
        return normalize(self._settings.get('ue_region'))

    def _refresh_region_text(self) -> None:
        region = self._region()
        if not region:
            self.lab_region.setText('整张图')
            return
        self.lab_region.setText('已选 %.0f m × %.0f m' % ((region[2] - region[0]) / 100,
                                                          (region[3] - region[1]) / 100))

    def _region_toggled(self, checked: bool) -> None:
        if checked and not self._settings.get('ue_region'):
            self._pick_region()
            if not self._settings.get('ue_region'):
                self.chk_region.setChecked(False)
        self._refresh_region_text()
        self._refresh()

    def _pick_region(self) -> None:
        from app.region_picker import RegionPicker
        from core.region import normalize
        name = self._map_name()
        root = self._paths()['root']
        dialog = RegionPicker(self, name, root, normalize(self._settings.get('ue_region')))
        if dialog.exec() == RegionPicker.Accepted:
            picked = dialog.picked
            if picked:
                self._settings['ue_region'] = list(picked)
                self.chk_region.setChecked(True)
            else:
                self._settings.pop('ue_region', None)
                self.chk_region.setChecked(False)
            self._refresh_region_text()
            self._refresh()

    # ---------------------------------------------------------- 简单向导 --
    def _offer_wizard(self) -> bool:
        """导出前问一次：要不要按向导一步步来。返回 True 表示继续导出。"""
        if self._settings.get('wizard_never'):
            return True
        from PySide6.QtWidgets import QApplication
        if QApplication.platformName() in ('offscreen', 'minimal') or os.environ.get('ATLASMAP_NO_WIZARD'):
            return True                      # 自动化/无头环境不弹窗
        from app.simple_wizard import ask_wizard
        choice = ask_wizard(self)
        if choice == 'direct':
            return True
        if choice == 'never':
            self._settings['wizard_never'] = True
            try:
                exporter.save_settings(self._settings)
            except Exception:                                   # noqa: BLE001
                pass
            return True
        return self._apply_wizard()

    def _apply_wizard(self) -> bool:
        from app.simple_wizard import SimpleWizard
        dialog = SimpleWizard(self.win, self._map_names,
                              {'map': self._map_name(), 'base': self.ed_root.text().strip(),
                               'quality': self.quality.combo.currentData(),
                               'region': self._region()})
        if dialog.exec() != SimpleWizard.Accepted or not dialog.values:
            return False
        values = dialog.values
        name = values['map']
        index = self.cb_map.findData(name)
        if index >= 0:
            self.cb_map.setCurrentIndex(index)
        else:
            self.cb_map.setEditText(name)
        self.ed_root.setText(values['base'])
        quality_index = self.quality.combo.findData(values['quality'])
        if quality_index >= 0:
            self.quality.combo.setCurrentIndex(quality_index)
        region = values.get('region')
        if region:
            self._settings['ue_region'] = list(region)
            self.chk_region.setChecked(True)
        else:
            self._settings.pop('ue_region', None)
            self.chk_region.setChecked(False)
        self._refresh_region_text()
        self._save()
        self._refresh()
        return True

    def _save(self) -> None:
        self._settings.update(exporter.load_settings())
        self._settings["ue_engine"] = self.ed_engine.text().strip()
        self._settings["ue_project"] = self.ed_project.text().strip()
        self._settings["blender"] = self.ed_blender.text().strip()
        self._settings['export_target']=self.cb_target.currentData()
        self._settings['export_quality']=self.quality.combo.currentData()
        self._settings["ue_export_base"] = self.ed_root.text().strip()
        self._settings["ue_root"] = self._paths()["root"]
        self._settings["ue_map"] = self._map_name()
        self._settings["ue_dest"] = self.ed_dest.text().strip()
        self._settings["ue_workers"] = self.sp_workers.value()
        self._settings['parallel_export'] = self.chk_parallel.isChecked()
        self._settings['parallel_processes'] = self.sp_parallel.value()
        self._settings['mem_limit'] = self.chk_memlimit.isChecked()
        self._settings['ue_region'] = self._region()
        self._settings['lighting_mode'] = 'supplemental' if self.chk_supplemental.isChecked() else 'source'
        self._settings['render_profile'] = 'game' if self.chk_game_lighting.isChecked() else 'source'
        self._settings['render_view'] = self.cb_render_view.currentData()
        self._settings['render_ev'] = self.sp_render_ev.value()
        try:
            exporter.save_settings(self._settings)
        except Exception:                                        # noqa: BLE001
            pass
        other=getattr(self.win,'map_page',None)
        if other is not None and other.quality.combo.currentData()!=self.quality.combo.currentData():
            other.quality.combo.setCurrentIndex(other.quality.combo.findData(self.quality.combo.currentData()))

    # ---------------------------------------------------------- 命令生成 --
    def _paths(self) -> Dict[str, str]:
        name = self._map_name()
        root = os.path.join(self.ed_root.text().strip() or "<导出基目录>", name or "<选择地图>")
        transfer = root + ('_blender_work' if self.cb_target.currentData()=='blender' else '_ue')
        return {
            'target':self.cb_target.currentData(),
            'export_quality':self.quality.combo.currentData(),
            'max_tex':str(export_quality.quality(self.quality.combo.currentData()).max_tex),
            "engine": self.ed_engine.text().strip() or "<UnrealEditor.exe>",
            "cmd": self.ed_engine.text().strip().replace("UnrealEditor.exe",
                                                         "UnrealEditor-Cmd.exe") or
                  "<UnrealEditor-Cmd.exe>",
            "project": self.ed_project.text().strip() or "<你的工程.uproject>",
            "blender": self.ed_blender.text().strip() or "<blender.exe>",
            "root": root,
            "transfer": transfer,
            "map": name,
            "dest": self.ed_dest.text().strip() or "/Game/AtlasMaps/" + name,
            "exe": exporter.find_exe() or "<map-export.exe>",
            "config": exporter.exporter_config_path(),
            "scripts": os.path.join(_app_root(), "scripts", "official"),
            "outdir": os.path.dirname(root),
            "workers": str(self.sp_workers.value()),
            "parallel_export": '1' if self.chk_parallel.isChecked() else '0',
            "parallel_processes": str(self.sp_parallel.value()),
            "mem_limit": '1' if self.chk_memlimit.isChecked() else '0',
            "lighting_mode": 'supplemental' if self.chk_supplemental.isChecked() else 'source',
            "render_profile": 'game' if self.chk_game_lighting.isChecked() else 'source',
            "region": self._region(),
        }

    def _cmd_export(self) -> str:
        p = self._paths()
        try:
            command="& " + " ".join("'" + arg.replace("'", "''") + "'" for arg in ue_pipeline.export_command(p))
            helper=os.path.join(os.path.dirname(p['scripts']),'tools','scene-state','scene-state.exe')
            extra=[helper,os.path.dirname(p['exe']),p['config'],p['root'],os.path.join(p['root'],'source-render')]
            return command+'\nif ($LASTEXITCODE -ne 0) { throw "地图导出失败" }\n& '+ ' '.join("'"+arg.replace("'","''")+"'" for arg in extra)
        except ValueError:
            return "# 请先选择地图或输入有效的英文地图代号"

    def _cmd_blender1(self) -> str:
        p = self._paths()
        return (
            f'New-Item -ItemType Directory -Force "{p["root"]}\\diagnostics" | Out-Null\n'
            f'& "{p["blender"]}" -b --python-exit-code 1 -P "{p["scripts"]}\\blender_iceland.py" -- '
            f'"{p["root"]}" --no-render --materials --flat-split'
        )

    def _cmd_blender2(self) -> str:
        p = self._paths()
        return (
            f'$env:ATLASMAP_UE_ROOT = "{p["transfer"]}"\n'
            f'& "{p["blender"]}" -b "{p["root"]}\\scene_no_terrain.blend" -P '
            f'"{p["scripts"]}\\blender_iceland_to_ue.py"'
        )

    def _cmd_blender3(self) -> str:
        p = self._paths()
        return (
            f'$env:ATLASMAP_UE_ROOT = "{p["transfer"]}"\n'
            f'& "{p["blender"]}" -b -P "{p["scripts"]}\\compile_iceland_ue_materials.py"\n'
            f'& "{p["blender"]}" -b -P "{p["scripts"]}\\group_iceland_ue_materials.py"'
        )

    def _cmd_ue(self) -> str:
        p = self._paths()
        from core.ue_render_config import headless_renderer_args
        renderer_args = ' '.join('"'+arg+'"' for arg in headless_renderer_args())
        return (
            f'$env:ATLASMAP_UE_ROOT  = "{p["transfer"]}"\n'
            f'$env:ATLASMAP_UE_DEST  = "{p["dest"]}"\n'
            f'$env:ATLASMAP_UE_LEVEL = "{p["dest"]}/LV_Map"\n'
            f'$env:ATLASMAP_SOURCE_ROOT = "{p["root"]}"\n'
            f'$env:ATLASMAP_LIGHTING_MODE = "{p["lighting_mode"]}"\n'
            f'$env:ATLASMAP_RENDER_PROFILE = "{p["render_profile"]}"\n'
            f'$env:ATLASMAP_UE_WORKERS = "{p["workers"]}"\n'
            f'$env:ATLASMAP_UE_BATCH_SAVE = "1"\n'
            f'& "{p["cmd"]}" "{p["project"]}" '
            f'-ExecutePythonScript="{p["scripts"]}\\ue_run_headless.py" -nullrhi -unattended -nosplash -SCCProvider=None {renderer_args}'
        )

    def _cmd_finish(self) -> str:
        p = self._paths()
        return (
            f'$env:ATLASMAP_UE_LEVEL = "{p["dest"]}/LV_Map"\n'
            f'$env:ATLASMAP_SOURCE_ROOT = "{p["root"]}"\n'
            f'$env:ATLASMAP_LIGHTING_MODE = "{p["lighting_mode"]}"\n'
            f'$env:ATLASMAP_RENDER_PROFILE = "{p["render_profile"]}"\n'
            f'$env:ATLASMAP_UE_NO_RENDER = "1"\n'
            f'& "{p["cmd"]}" "{p["project"]}" '
            f'-ExecutePythonScript="{p["scripts"]}\\ue_ensure_lighting.py" -nullrhi -unattended -nosplash -SCCProvider=None\n'
            f'& "{p["cmd"]}" "{p["project"]}" '
            f'-ExecutePythonScript="{p["scripts"]}\\ue_build_collision.py" -nullrhi -unattended -nosplash -SCCProvider=None\n'
            f'& "{p["engine"]}" "{p["project"]}" "{p["dest"]}/LV_Map"'
        )

    # ------------------------------------------------------------------ #
    def _build_step(self, title: str, desc: str, builder, extra: str = "") -> QWidget:
        card, box = _card()
        self._advanced_widgets.append(card)
        head = QHBoxLayout()
        head.addWidget(_label(title, 15, True), 1)
        box.addLayout(head)
        box.addWidget(_label(desc, 12, color="#9aa4b2"))
        cmd = builder() if extra != "mkdir" else builder()
        edit = F.CodeEditor(cmd)
        edit.setReadOnly(True)
        edit.setFixedHeight(_px(120))
        box.addWidget(edit)
        row = QHBoxLayout()
        btn = F.PushButton("复制这一步")
        btn.clicked.connect(lambda: self._copy(edit.toPlainText()))
        row.addWidget(btn)
        row.addStretch(1)
        box.addLayout(row)
        self._steps.append((title, cmd, edit))
        return card

    def _refresh(self) -> None:
        name = self._map_name()
        if name != self._last_map:
            parent = self.ed_dest.text().strip().rstrip("/").rsplit("/", 1)[0] or "/Game/AtlasMaps"
            self._last_map = name
            self.ed_dest.blockSignals(True)
            self.ed_dest.setText(parent + "/" + name if name else "")
            self.ed_dest.blockSignals(False)
        p = self._paths()
        counts=self._map_counts or getattr(getattr(self.win,'map_page',None),'_maps',{})
        self.quality.set_context(name,p['root'],counts.get(name,0),p['target'],
                                 int(p['parallel_processes']) if p['parallel_export']=='1' else 1,p['project'])
        self.lab_target.setText(f"导出地图：{mapnames.label(name)} ({name})\n"
                                f"文件目录：{p['root']}\nUE 关卡：{p['dest']}/LV_Map")
        if not self.advanced_switch.isChecked():
            project = p['project'] or '首次导出时自动创建'
            mode = '性能模式（高资源占用）' if self.chk_parallel.isChecked() else '普通模式'
            self.lab_target.setText(f"保存到：{p['root']}\n使用工程：{project}\n当前模式：{mode}")
        if p['target']=='blender':
            self.lab_target.setText(f"Blender 工程保存到：{p['root']}_blender\n贴图内置，分块和主工程保存在同一个工程文件夹中。")
        bad = [path for path in (p['root'],p['project']) if '<' not in path]
        if p['target']=='ue' and any(any(ord(ch) > 127 for ch in text) for text in bad):
            F.set_warning(self.lab_warn,"⚠ 导出目录 / 工程路径里有中文：UE 命令行会把中文转成 ?，"
                                  "请换到纯 ASCII 路径（例如 C:/AtlasMapExports/SafeHouse）。")
        else:
            F.set_warning(self.lab_warn,"")
        builders = (self._cmd_export, self._cmd_blender1, self._cmd_blender2,
                    self._cmd_blender3, self._cmd_ue, self._cmd_finish)
        for (_t, _c, edit), fn in zip(self._steps, builders):
            edit.setPlainText(fn())
        self._save()

    def _open_editor(self) -> None:
        """起编辑器打开已导入的关卡。"""
        import subprocess

        p = self._paths()
        if p['target']=='blender':
            project=exporter.load_settings().get('blender_projects',{}).get(p['map'],'')
            if not os.path.isfile(project):
                self.shell.status('这张地图还没有导出完成的 Blender 工程');return
            if not os.path.isfile(p['blender']):self.shell.status('请先选择 blender.exe');return
            subprocess.Popen([p['blender'],project]);return
        if not os.path.isfile(p["engine"]) or not os.path.isfile(p["project"]):
            self.shell.status("先选好引擎和工程")
            return
        level = p["dest"].rstrip("/") + "/LV_Map"
        relative = level.removeprefix("/Game/")
        level_file = os.path.join(os.path.dirname(p["project"]), "Content", *relative.split("/")) + ".umap"
        if not level.startswith("/Game/") or not os.path.isfile(level_file):
            self.shell.status(f"所选地图尚未导入这个工程：{level}，请先执行一键导出")
            return
        try:
            with open(os.path.join(p["transfer"], "ue_import_result.json"), encoding="utf-8-sig") as fh:
                result = json.load(fh)
            ready = result.get("complete") and result.get("level") == level
        except (OSError, ValueError):
            ready = False
        if not ready:
            self.shell.status("所选地图导入尚未完成，请先重新执行一键导出；已完成的资源会自动复用")
            return
        try:
            subprocess.Popen([p["engine"], p["project"], level],
                             creationflags=0x08000000)
            self.shell.status(f"正在打开 {level}")
        except Exception as exc:                                # noqa: BLE001
            self.shell.status(f"打开失败：{exc}")

    def _render_preview(self):
        p = self._paths()
        p['render_view'] = self.cb_render_view.currentData()
        p['render_ev'] = str(self.sp_render_ev.value())
        level = p['dest'].rstrip('/')+'/LV_Map'
        level_file = os.path.join(os.path.dirname(p['project']), 'Content',
                                  *level.removeprefix('/Game/').split('/'))+'.umap'
        if not all(os.path.isfile(p[k]) for k in ('engine','project')):
            self.shell.status('先选好虚幻引擎和工程')
            return
        if not os.path.isfile(level_file) or not os.path.isfile(os.path.join(p['root'],'lights.json')):
            self.shell.status('所选地图尚未完成导入或缺少源灯光数据，请先执行一键导出')
            return
        if not os.path.isfile(os.path.join(p['root'],'render_state.json')):
            self.shell.status('这张地图缺少完整源渲染数据，请用新版重新一键导出')
            return
        try:
            with open(os.path.join(p['transfer'], 'ue_import_result.json'), encoding='utf-8-sig') as fh:
                imported = json.load(fh)
            if not imported.get('complete') or imported.get('level') != level:
                raise ValueError('Unfinished import')
            ue_pipeline.validate_export(p['root'], p['map'])
        except (OSError, ValueError):
            self.shell.status('所选地图导入尚未完成或源数据不匹配，请先重新执行一键导出')
            return
        if self.win.job and self.win.job.running:
            self.shell.status('当前有任务正在运行，请等它完成')
            return
        self._save()
        def done(code):
            if code:
                self.shell.status('渲染失败，请查看任务日志')
                return
            image = os.path.join(p['root'],'render_preview.png')
            pix = QPixmap(image)
            if pix.isNull():
                self.shell.status('渲染没有生成有效图片')
                return
            dialog = F.Dialog(mapnames.label(p['map'])+' · UE 渲染预览', parent=self)
            dialog.setYesButtonText('关闭')
            dialog.cancel_button.hide()
            label = QLabel()
            area=self.screen().availableGeometry()
            label.setPixmap(pix.scaled(int(area.width()*.8),int(area.height()*.65),Qt.KeepAspectRatio,Qt.SmoothTransformation))
            dialog.add_content_widget(label)
            dialog.add_content_widget(QLabel('图片已保存：'+image))
            self._preview_dialog = dialog
            dialog.open()
        self.win.run_pipeline('UE 渲染：'+p['map'], [ue_pipeline.render_step(p)], on_done=done)

    def _run_all(self) -> None:
        """一键：导出器导出 → Blender 三段 → UE 七阶段 → 补灯 → 补碰撞。"""
        if getattr(self.win, '_project_mutation', False):
            self.shell.status('正在移动或删除工程，请稍候')
            return
        if getattr(self.win,'_cleanup_pending',False):
            self.shell.status('请先处理上次导出的残留文件')
            return
        if not self._offer_wizard():
            return
        try:
            ue_pipeline.map_roots(self._map_name())
        except ValueError as exc:
            self.shell.status(str(exc))
            return
        if self.win.job and self.win.job.running:
            self.shell.status("当前有任务正在运行，请先等它完成")
            return
        blender_target=self.cb_target.currentData()=='blender'
        # 引擎/Blender 没填就自动探一下
        if not blender_target and not os.path.isfile(self.ed_engine.text().strip()):
            guess = _detect_engine()
            if guess:
                self.ed_engine.setText(guess)
        if not os.path.isfile(self.ed_blender.text().strip()):
            guess = _detect_blender()
            if guess:
                self.ed_blender.setText(guess)

        # 没工程就先自动造一个，别让用户卡在「还差 UE 工程」这一步
        if not blender_target and not os.path.isfile(self.ed_project.text().strip()):
            if self._ensure_project() is None:
                self.shell.status("没有 UE 工程，而且自动新建也失败了；请点「新建…」手动指定目录")
                return

        p = self._paths()
        missing = []
        if not os.path.isfile(p["exe"]):
            missing.append("map-export.exe")
        if not blender_target and not os.path.isfile(p["engine"]):
            missing.append("引擎（UnrealEditor.exe）")
        if not blender_target and not os.path.isfile(p["cmd"]):
            missing.append("UnrealEditor-Cmd.exe")
        if not os.path.isfile(p["blender"]):
            missing.append("Blender")
        if not blender_target and not os.path.isfile(p["project"]):
            missing.append("UE 工程（.uproject，可点「新建…」）")
        if missing:
            self.advanced_switch.setChecked(True)
            F.message(self, '首次使用需要完成环境配置', '还缺少：' + '、'.join(missing) + '。\n已展开配置项，请选择对应程序；配置一次后即可切回简易模式。')
            self.shell.status("还差：" + "、".join(missing))
            return
        if not exporter.resolve_keyfile():
            self.advanced_switch.setChecked(True)
            F.message(self, '还没有 AES 密钥文件',
                      '导出器要解开游戏的 pak，必须有一份 AESKey1.json。\n\n'
                      '两种放法任选一种：\n'
                      '1) 在「设置 → 密钥 JSON」里选它；\n'
                      '2) 把它放到程序目录的 assets\\AESKey1.json（单文件版放 exe 旁边也行）。\n\n'
                      '放一次就记住了，之后不用再选。')
            self.shell.status('缺少 AES 密钥文件')
            return
        root = p["root"]
        if not blender_target and any(ord(ch) > 127 for ch in root + p["project"]):
            self.shell.status("导出目录/工程路径里有中文，先换成纯 ASCII 路径")
            return

        # Rescans and game-directory changes must not alter running workers.
        import uuid
        p["config"] = exporter.write_exporter_config(path=os.path.join(exporter.app_dir(),'job-config',uuid.uuid4().hex+'.json'))
        if p['parallel_export'] == '1':
            from app.parallel_export_windows import desktop_capacity
            screen = self.win.screen()
            capacity = desktop_capacity(screen.availableGeometry() if screen else None)
            count = min(int(p['parallel_processes']), capacity)
            p['parallel_processes'] = str(count)
            if count != self.sp_parallel.value():
                self.sp_parallel.setValue(count)
                self.shell.status(f'已按当前屏幕空间调整为 {count} 个并行进程')
        notes = ue_pipeline.prepare_dirs(root,target='blender' if blender_target else 'ue')
        if blender_target:
            from core.blender_pipeline import build_steps
            steps,project=build_steps(p)
        else:
            steps=ue_pipeline.build_steps(p);project=p['project']
        title = ('导出 Blender：' if blender_target else '进 UE：')+p['map']
        from core.map_preview import session,attach
        preview=session(root,mapnames.label(p['map']),int(p['parallel_processes']) if p['parallel_export']=='1' else 1)
        steps=attach(steps,preview)

        win = self.win.show_export_overlay(title, root, parallel_count=int(p['parallel_processes']),preview=preview) \
            if p['parallel_export'] == '1' else self.win.show_export_overlay(title, root,preview=preview)
        total = len(steps)

        def progress(done: int, all_: int, name: str) -> None:
            try:
                win.set_fraction(min(1.0, done / max(1, all_)))
                if hasattr(win, 'set_stage') and done < len(steps):
                    win.set_stage(name, parallel=bool(steps[done].parallel_factory))
                win.feed(f"[{done}/{all_}] {name}")
            except Exception:                                # noqa: BLE001
                pass

        def finished(code: int) -> None:
            if code == 0:
                try:
                    if blender_target:
                        settings=exporter.load_settings()
                        settings.setdefault('blender_projects',{})[p['map']]=project
                        exporter.save_settings(settings)
                    from core.projects import Catalogue
                    Catalogue().register(project, p['map'], root, p['dest'])
                except (OSError, ValueError) as error:
                    self.shell.status('导出成功，但工程记录保存失败：' + str(error))
                try:
                    # 记下这次实际有多大，下次同一张图的预估就是实测值
                    from core import export_quality as _Q
                    _Q.record_export(p['map'], root, project='' if blender_target else project,
                                     max_tex=int(p.get('max_tex',0) or 0))
                except (OSError, ValueError, TypeError):
                    pass
                self._cleanup_after_export(root, p['map'])
            try:
                # 「打开」直接指到刚生成的 .uproject（在资源管理器里选中它），
                # 找不到就退到工程目录
                target = project if os.path.isfile(project) else os.path.dirname(project)
                win.finish(code, root, open_path=target,
                           open_label="打开 Blender 工程" if blender_target else "打开 UE 工程",
                           failure=getattr(self.win,'_failure_report',None))
                try:
                    self.win.last_open_dir = os.path.dirname(project)
                except Exception:                            # noqa: BLE001
                    pass
            except Exception:                                # noqa: BLE001
                pass

        for note in notes:
            win.feed(note)
        from core.export_quality import quality
        win.feed('导出质量：'+quality(p['export_quality']).title+'；贴图上限 '+p['max_tex']+'（0 为原始）')
        win.feed(self.quality.estimate.text())
        from core.export_residue import for_ue_export
        if blender_target:
            from core.export_residue import ExportResidue
            from pathlib import Path
            residue=ExportResidue([root,p['transfer'],Path(project).parent])
        else:residue=for_ue_export(p,steps)
        self.win.run_pipeline(title, steps, on_done=finished,
                              on_line=win.feed, on_progress=progress,
                              residue=residue)

    def _copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        try:
            self.shell.status("已复制到剪贴板")
        except Exception:                                        # noqa: BLE001
            pass

    def _copy_all(self) -> None:
        blocks = []
        for title, _cmd, edit in self._steps:
            blocks.append(f"# ---- {title} ----\n" + edit.toPlainText())
        self._copy("\n\n".join(blocks))

    def _export_ps1(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "保存为 .ps1",
                                              "AtlasMap_to_UE.ps1", "PowerShell (*.ps1)")
        if not path:
            return
        lines = ["# AtlasMap 生成：地图 → Blender → UE 全流程", ""]
        for title, _cmd, edit in self._steps:
            lines.append(f"# ---- {title} ----")
            lines.append(edit.toPlainText())
            lines.append("")
        try:
            with open(path, "w", encoding="utf-8-sig") as fh:
                fh.write("\n".join(lines))
            self.shell.status(f"已保存 {os.path.basename(path)}")
        except Exception as exc:                                 # noqa: BLE001
            self.shell.status(f"保存失败：{exc}")
