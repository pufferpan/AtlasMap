"""五个页面：地图 / 任务（日志）/ 工具 / 说明 / 设置。

版式沿用同系列查看器的写法：卡片 + 标题 + 说明 + 主按钮，尺寸全部走 `ui_scale.px()`。
"""
from __future__ import annotations

import html
import json
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView,QTableWidgetItem,QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPlainTextEdit,
                               QSizePolicy, QSplitter, QVBoxLayout, QWidget)

from app import fluent_api as F
from app import ui_scale
from app.ui_scale import px as _px
from core import exporter
from core import mapnames as _mn

ACCENT = "#2B579A"


def _label(text: str, size: int = 13, bold: bool = False, color: Optional[str] = None) -> QLabel:
    lab = QLabel(text)
    font = QFont(lab.font())
    font.setPixelSize(_px(size))
    font.setBold(bold)
    lab.setFont(font)
    lab.setStyleSheet(f"color:{color};background:transparent;" if color else "background:transparent;")
    lab.setWordWrap(True)
    return lab


def Section(title,parent=None):
    card=F.SimpleCardWidget(parent)
    card.box=QVBoxLayout(card)
    card.box.setContentsMargins(_px(16),_px(14),_px(16),_px(14))
    card.box.setSpacing(_px(10))
    card.box.addWidget(_label(title,14,True))
    return card


# --------------------------------------------------------------- 地图页 --
# 地图没有预设时，按 BuildMaps_HD/<地图>/Runtime/ 下真实的层目录给默认资源根
RUNTIME_GROUPS = (
    ("Runtime/BigMeshGroup/", "运行时静态几何（BigMeshGroup）", True),
    ("Runtime/MidMeshGroup/", "中景网格（MidMeshGroup）", False),
    ("Runtime/SmallMeshGroup/", "小物件（SmallMeshGroup）", False),
    ("Runtime/Decorations/", "装饰（Decorations）", False),
    ("Runtime/Decorations_HQ/", "装饰 HD（Decorations_HQ）", False),
    ("Runtime/Landmark/", "地标（Landmark）", False),
    ("Runtime/Default/", "默认层（Default）", False),
    ("Runtime/POIResident/", "POI 常驻（POIResident）", False),
)


def map_roots(name: str) -> List[tuple]:
    """Include authored map levels as well as streamed geometry."""
    base = f"DeltaForce/Content/Maps/BuildMaps_HD/{name}/"
    return ([(base + g, label, default) for g, label, default in RUNTIME_GROUPS]
            + [(f'DeltaForce/Content/Maps/{name}/', '源地图关卡 / 光照', True),
               (f'DeltaForce/Content/Maps/BuildMaps/{name}/', '标准流送关卡', True)])


class MapPage(QWidget):
    """左边地图卡片，右边详情 + 导出参数。"""

    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self.host = window
        self._maps: Dict[str, int] = {}
        self._current = ""
        self._stage_boxes: List[tuple] = []
        self._root_boxes: List[tuple] = []
        self._preset: Optional[Dict[str, object]] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(_px(18), _px(14), _px(18), _px(14))
        outer.setSpacing(_px(12))

        head = QHBoxLayout()
        head.addWidget(_label("地图库", 20, True))
        head.addStretch(1)
        self.search = F.LineEdit()
        self.search.setPlaceholderText("搜地图名，例如 Iceland / Mogadishu")
        self.search.setFixedHeight(_px(32))
        self.search.setMinimumWidth(_px(260))
        self.search.textChanged.connect(self._filter)
        head.addWidget(self.search)
        self.scan_btn = F.PushButton("扫描地图")
        self.scan_btn.setFixedHeight(_px(32))
        self.scan_btn.clicked.connect(self.scan)
        head.addWidget(self.scan_btn)
        outer.addLayout(head)

        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split, 1)

        # 左：列表
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, _px(6), 0)
        lv.setSpacing(_px(8))
        self.count_label = _label("还没有扫描过地图", 12, False, "#9fb3c8")
        lv.addWidget(self.count_label)
        self.scroll = F.scroll_area()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.holder = QWidget()
        self.grid = QVBoxLayout(self.holder)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(_px(6))
        self.grid.addStretch(1)
        self.scroll.setWidget(self.holder)
        lv.addWidget(self.scroll, 1)
        split.addWidget(left)

        # 右：详情
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(_px(6), 0, 0, 0)
        rv.setSpacing(_px(10))

        card = Section("导出设置")
        self.title = _label("先选一张地图", 16, True)
        card.box.addWidget(self.title)
        self.subtitle = _label("点左边的卡片，或者先点「扫描地图」从 pak 里列出所有地图。",
                               12, False, "#9fb3c8")
        card.box.addWidget(self.subtitle)

        self.stage_title = _label("阶段（预设来自 presets/*.json）", 13, True)
        card.box.addWidget(self.stage_title)
        self.stage_box = QVBoxLayout()
        self.stage_box.setSpacing(_px(4))
        card.box.addLayout(self.stage_box)

        # 没有预设时手填的资源根（每行一个），也可以给有预设的图补层
        self.custom_roots = F.TextEdit()
        self.custom_roots.setPlaceholderText(
            "自定义资源根（可选，每行一个）\n"
            "DeltaForce/Content/Maps/Iceland/LA_Meshs/LA_Mesh_S2.umap")
        self.custom_roots.setFixedHeight(_px(64))
        self.custom_roots.setVisible(False)
        card.box.addWidget(self.custom_roots)

        row = QHBoxLayout()
        row.addWidget(_label("输出目录", 12))
        self.out_edit = F.LineEdit(exporter.load_settings().get("outdir", ""))
        self.out_edit.setFixedHeight(_px(30))
        row.addWidget(self.out_edit, 1)
        pick = F.PushButton("选择…")
        pick.setFixedHeight(_px(30))
        pick.clicked.connect(self._pick_out)
        row.addWidget(pick)
        card.box.addLayout(row)

        flags = QGridLayout()
        self.cb_split = F.CheckBox("分块 (--split)")
        self.cb_split.setChecked(True)
        self.cb_dedup = F.CheckBox("去重 (--deduplicate)")
        self.cb_dedup.setChecked(True)
        self.cb_base = F.CheckBox("保留基础层 (--keep-base-with-hd)")
        self.cb_base.setChecked(True)
        self.cb_visible = F.CheckBox("只导可见 (--visible-only)")
        self.cb_noscene = F.CheckBox("不合并总场景 (--no-scene)")
        for index,w in enumerate((self.cb_split, self.cb_dedup, self.cb_base, self.cb_visible, self.cb_noscene)):
            flags.addWidget(w,index//2,index%2)
        card.box.addLayout(flags)

        from app.export_quality import QualityPanel
        self.quality=QualityPanel(self.host,self.scan,self)
        self.quality.combo.currentIndexChanged.connect(self._quality_changed)
        self.out_edit.textChanged.connect(self._refresh_estimate)
        card.box.addWidget(self.quality.card)

        actions = QHBoxLayout()
        self.export_btn = F.PrimaryPushButton("开始导出")
        self.export_btn.setFixedHeight(_px(38))
        self.export_btn.clicked.connect(self.export)
        actions.addWidget(self.export_btn)
        self.cmd_btn = F.PushButton("只看命令行")
        self.cmd_btn.setFixedHeight(_px(38))
        self.cmd_btn.clicked.connect(lambda: self.export(dry_run=True))
        actions.addWidget(self.cmd_btn)
        actions.addStretch(1)
        card.box.addLayout(actions)

        rv.addWidget(card)

        hints = Section("说明")
        hints.box.addWidget(_label(
            "· 第一次用先到「工具」里点「导出前检查」，确认目录/密钥/运行时都对。\n"
            "· 阶段只覆盖对应资源根；地形、材质修复、Blender 导入按「说明」里的教程走。\n"
            "· 导出的 split 目录可以直接喂给 scripts/blender_import_verified.py。",
            12, False, "#9fb3c8"))
        rv.addWidget(hints)
        rv.addStretch(1)
        right_scroll=F.scroll_area()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setWidget(right)
        split.addWidget(right_scroll)
        split.setSizes([_px(400), _px(700)])

        self.reload_presets()
        # 没扫描之前，先把 presets 里的地图摆出来（数量未知，显示"预设"）
        self._maps = {str(p.get("map")): 0 for p in self._presets}
        self._fill()
        if self._maps:
            first = next(iter(self._maps))
            self.select(first)

    # ---- 地图列表 ----
    def reload_presets(self) -> None:
        self._presets = exporter.load_presets(exporter.find_exe())
        self._rebuild_stages()

    def _rebuild_stages(self) -> None:
        while self.stage_box.count():
            item = self.stage_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._stage_boxes = []
        self._root_boxes = []
        preset = self._current_preset()
        if not preset:
            # 没有预设 ≠ 不能导出：按 BuildMaps_HD/<地图>/Runtime/ 下真实的层给勾选
            if not self._current:
                self.stage_title.setText("阶段（预设来自 presets/*.json）")
                self.stage_box.addWidget(_label("先在左边选一张地图", 12, False, "#9fb3c8"))
                return
            self.stage_title.setText("资源根（这张图没有预设，勾选要导出的层）")
            for root, label, default in map_roots(self._current):
                cb = F.CheckBox(label)
                cb.setChecked(default)
                cb.setToolTip(root)
                self.stage_box.addWidget(cb)
                self._root_boxes.append((cb, root))
            tip = _label("想加别的层？填到下面「自定义资源根」，每行一个路径（目录以 / 结尾，"
                         "也可以是单个 .umap）", 11, False, "#9fb3c8")
            tip.setWordWrap(True)
            self.stage_box.addWidget(tip)
            self.custom_roots.setVisible(True)
            return
        self.stage_title.setText("阶段（预设来自 presets/*.json）")
        self.custom_roots.setVisible(False)
        self.custom_roots.setPlainText("")
        missing = self._maps.get(self._current, 0) == 0
        for st in preset.get("stages", []):
            cb = F.CheckBox(str(st.get("label") or st.get("id")))
            cb.setChecked(not missing)
            cb.setToolTip(" / ".join(st.get("roots") or []))
            self.stage_box.addWidget(cb)
            self._stage_boxes.append((cb, st))
        if missing:
            warn = F.WarningNotice("这份 pak 里没有这张图（扫不到任何层），预设的资源根无法匹配；"
                          "换一张能扫到文件数的图，或去「设置」确认游戏目录。",self)
            self.stage_box.addWidget(warn)

    def _current_preset(self) -> Optional[Dict[str, object]]:
        name = (self._current or "").strip().lower()
        for p in self._presets:
            if str(p.get("map", "")).lower() == name:
                return p
        return None

    def scan(self) -> None:
        if not self.scan_btn.isEnabled():return
        exe = exporter.find_exe()
        if not exe:
            self.host.status("没找到 map-export.exe，先去「设置」里指定")
            return
        self.scan_btn.setEnabled(False)
        self.quality.scan_button.setEnabled(False)
        self.scan_btn.setText("扫描中…")
        self.host.status("正在扫 pak，通常 8 秒左右…")
        # find 会吐几十万行，别往界面里灌，丢后台线程只取统计结果
        self.host.run_async(lambda: exporter.list_maps(exe), self._scan_result)

    def _scan_result(self, counts) -> None:
        self.quality.scan_button.setEnabled(True)
        self.quality.reload()
        if isinstance(counts, Exception):
            self.host.status(f"扫描失败：{counts}")
            self._maps = {}
        else:
            scanned = dict(counts)
            # presets 里的地图可能不在 BuildMaps_HD 下（比如 Iceland 在 Maps/Iceland/），
            # 扫描结果里要把它并回来，否则「有预设的地图」会被扫没了、根本选不到。
            for p in self._presets:
                name = str(p.get("map") or "").strip()
                if name and name not in scanned:
                    scanned[name] = 0
            preset_names = {str(pr.get("map", "")).lower() for pr in self._presets}
            self._maps = dict(sorted(
                scanned.items(),
                key=lambda kv: (0 if kv[0].lower() in preset_names else 1, -kv[1], kv[0].lower())))
            self.host.status(f"扫描完成：{len(self._maps)} 张地图"
                               f"（其中 {len(self._presets)} 张有预设）")
        self._fill()
        keep = self._current
        self._current = None
        if keep in self._maps:
            self.select(keep)
        elif self._maps:
            self.select(next(iter(self._maps)))
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("扫描地图")

    def _scan_done(self, code: int) -> None:
        lines = self.host.last_job_lines()
        counts = exporter.parse_maps('\n'.join(lines))
        preset_names = {str(pr.get("map", "")).lower() for pr in self._presets}
        self._maps = dict(sorted(
            counts.items(),
            key=lambda kv: (0 if kv[0].lower() in preset_names else 1, -kv[1], kv[0].lower())))
        self._fill()
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("扫描地图")
        self.host.status(f"扫描完成：{len(self._maps)} 张地图")

    def _filter(self) -> None:
        self._fill()

    def _fill(self) -> None:
        while self.grid.count() > 1:
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        key = self.search.text().strip().lower()
        shown = 0
        for name, count in self._maps.items():
            if key and key not in _mn.search_text(name):
                continue
            if count:
                tail = f"{count:,} 个文件"
            elif self._presets and any(str(pr.get("map", "")).lower() == name.lower()
                                       for pr in self._presets):
                tail = "预设 · 本包没有这张图"
            else:
                tail = "未扫描"
            cn = _mn.label(name)
            sub = "代号 " + name
            btn = F.ToggleButton(f"{cn} · {tail}")
            btn.setToolTip(sub)
            btn.setCheckable(True)
            btn.setChecked(name == self._current)
            btn.setFixedHeight(_px(46))
            btn.clicked.connect(lambda _=False, n=name: self.select(n))
            self.grid.insertWidget(self.grid.count() - 1, btn)
            shown += 1
        if shown == 0:
            tip = "点上面「扫描地图」从 pak 里列出所有地图" if not self._maps else "没有匹配的地图"
            self.grid.insertWidget(self.grid.count() - 1, _label(tip, 12, False, "#9fb3c8"))
        self.count_label.setText(f"{len(self._maps)} 张地图" if self._maps else "还没有扫描过地图")

    def select(self, name: str) -> None:
        self._current = name
        self._fill()
        self.title.setText(_mn.label(name))
        files = self._maps.get(name, 0)
        preset = self._current_preset()
        head = f"{files:,} 个文件" if files else "还没扫描过文件数"
        if preset:
            self.subtitle.setText(f"{_mn.subtitle(name)} · {head}"
                                  f" · 有分阶段预设（{len(preset.get('stages', []))} 段）")
        else:
            self.subtitle.setText(f"{_mn.subtitle(name)} · {head}"
                                  f" · 没有预设，按下面的资源根勾选导出")
        self._rebuild_stages()
        # 预设的地图若在本包扫不到任何文件，直接禁用导出，别让人白等
        blocked = bool(preset) and files == 0
        self.export_btn.setEnabled(not blocked)
        self.export_btn.setToolTip(
            "这份 pak 里没有这张地图的关卡，导不出东西；换一张能扫到文件数的图" if blocked else "")
        self._refresh_estimate()

    def _quality_changed(self,*_) -> None:
        settings=exporter.load_settings();settings['export_quality']=self.quality.combo.currentData()
        exporter.save_settings(settings);self._refresh_estimate()
        other=getattr(self.host,'ue_page',None)
        if other is not None and other.quality.combo.currentData()!=self.quality.combo.currentData():
            other.quality.combo.setCurrentIndex(other.quality.combo.findData(self.quality.combo.currentData()))

    def _refresh_estimate(self) -> None:
        self.quality.set_context(self._current or '',self.out_edit.text().strip(),
                                 self._maps.get(self._current,0),target='raw')

    def _pick_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择导出目录", self.out_edit.text() or "")
        if path:
            self.out_edit.setText(path)

    def _flags(self) -> List[str]:
        out: List[str] = []
        if self.cb_split.isChecked():
            out.append("--split")
        if self.cb_base.isChecked():
            out.append("--keep-base-with-hd")
        if self.cb_dedup.isChecked():
            out.append("--deduplicate")
        if self.cb_visible.isChecked():
            out.append("--visible-only")
        if self.cb_noscene.isChecked():
            out.append("--no-scene")
        from core.export_quality import quality
        out += ["--max-tex", str(quality(self.quality.combo.currentData()).max_tex)]
        return out

    def _build_cmd(self) -> Optional[List[str]]:
        exe = exporter.find_exe()
        if not exe:
            self.host.status("没找到 map-export.exe，先去「设置」里指定")
            return None
        name = self._current
        if not name:
            self.host.status("先选一张地图")
            return None
        roots: List[str] = []
        for cb, st in self._stage_boxes:            # 有预设：按阶段取资源根
            if cb.isChecked():
                roots += [r for r in (st.get("roots") or []) if r]
        for cb, root in self._root_boxes:           # 没预设：按层勾选
            if cb.isChecked() and root:
                roots.append(root)
        for line in self.custom_roots.toPlainText().splitlines():   # 手填的补充
            line = line.strip().replace("\\", "/")
            if line and line not in roots:
                roots.append(line)
        if not roots:
            self.host.status("一个资源根都没有：勾一个层，或者在「自定义资源根」里填路径")
            return None
        if self._maps.get(name, 0) == 0 and self._current_preset():
            self.host.status(f"⚠ 这份 pak 里找不到 {name} 的层，导出来会是空的；换一张图试试")
            return None
        out_dir = self.out_edit.text().strip() or exporter.load_settings()["outdir"]
        out_dir = os.path.join(out_dir, f"{name}_{time.strftime('%Y%m%d_%H%M')}")
        settings = exporter.load_settings()
        settings["outdir"] = self.out_edit.text().strip() or settings["outdir"]
        exporter.save_settings(settings)
        return exporter.merge_command(exe, name, out_dir, roots, self._flags())

    def export(self, dry_run: bool = False) -> None:
        if getattr(self.host,'_cleanup_pending',False) and not dry_run:
            self.host.status('请先处理上次导出的残留文件')
            return
        cmd = self._build_cmd()
        if not cmd:
            return
        if dry_run:
            self.host.show_command(cmd)
            return
        out_dir = cmd[cmd.index("merge") + 2] if "merge" in cmd else ""
        try:
            overlay = self.host.show_export_overlay(f"导出 {self._current}", out_dir)
        except Exception as exc:                                  # noqa: BLE001
            # 遮罩挂了也不能让导出跑不了，退化成「任务」页 + 状态栏
            import traceback
            traceback.print_exc()
            self.status(f"遮罩没起来（{type(exc).__name__}: {exc}），改用任务页显示")
            overlay = None
        from core.ue_pipeline import Step
        from core.export_residue import ExportResidue
        job = self.host.run_pipeline(f"导出 {self._current}", [Step('导出地图',cmd)],
                                  residue=ExportResidue([out_dir]),
                                  on_done=(overlay.finish if overlay else None),
                                  on_line=(overlay.feed if overlay else None))
        if job is None and overlay is not None:
            overlay.close()


# --------------------------------------------------------------- 任务页 --
class JobPage(QWidget):
    """实时日志。"""

    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self.host = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(_px(18), _px(14), _px(18), _px(14))
        lay.setSpacing(_px(10))

        head = QHBoxLayout()
        self.title = _label("任务", 20, True)
        head.addWidget(self.title)
        head.addStretch(1)
        self.open_btn = F.PushButton("打开输出目录")
        self.open_btn.clicked.connect(self._open_out)
        self.copy_btn = F.PushButton("复制命令")
        self.copy_btn.clicked.connect(self._copy_cmd)
        self.save_log_btn = F.PushButton("导出完整日志")
        self.save_log_btn.setEnabled(False)
        self.save_log_btn.setToolTip('保存整次任务及所有分块输出，包含界面未显示的历史内容')
        self.save_log_btn.clicked.connect(self.host.export_full_log)
        self.stop_btn = F.PushButton("停止")
        self.stop_btn.clicked.connect(self._stop)
        for w in (self.open_btn, self.copy_btn, self.save_log_btn, self.stop_btn):
            w.setFixedHeight(_px(32))
            head.addWidget(w)
        lay.addLayout(head)

        self.state = _label("空闲", 12, False, "#9fb3c8")
        lay.addWidget(self.state)
        from app.failure_notice import failure_notice
        self.failure_notice=failure_notice(self)
        lay.addWidget(self.failure_notice)

        self.log = F.CodeEditor()
        F.add_context_action(self.log,'导出完整日志',self.host.export_full_log)
        self.log.setReadOnly(True)
        self.log.text_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        mono = QFont("Consolas")
        mono.setPixelSize(_px(12))
        self.log.setFont(mono)
        lay.addWidget(self.log, 1)

        self._cmd: List[str] = []
        self._out_dir = ""

    def begin(self, title: str, cmd: List[str]) -> None:
        from app.failure_notice import show_failure
        show_failure(self.failure_notice,None)
        self._cmd = list(cmd)
        self._out_dir = ""
        for i, part in enumerate(cmd):
            if part == "merge" and i + 2 < len(cmd):
                self._out_dir = cmd[i + 2]
        self.title.setText(f"任务 · {title}")
        self.state.setText(f"运行中 · {time.strftime('%H:%M:%S')}")
        self.log.text_edit.clear()

    # CUE4Parse 启动时会往 stderr 刷几十行 JSON 转换器清单，纯噪音，滤掉
    _NOISE = ("JSON converters:", "FTextLocalizationResourceConverter",
              "Converter, ", "Converters, ")

    def append(self, line: str) -> None:
        if any(tok in line for tok in self._NOISE):
            return
        self.log.text_edit.appendPlainText(line)
        bar = self.log.text_edit.verticalScrollBar()
        bar.setValue(bar.maximum())

    def finish(self, code: int, failure=None) -> None:
        from app.failure_notice import show_failure
        show_failure(self.failure_notice,failure)
        ok = code == 0
        self.state.setText(("完成" if ok else '已取消' if code in (-2,130) else f"失败（退出码 {code}）") +
                           f" · {time.strftime('%H:%M:%S')}")
        self.append('' if ok else '\n[已取消] 本次任务已停止。' if code in (-2,130) else '\n[失败原因]\n'+failure.text() if failure else '\n[失败] 请导出完整日志查看具体错误。')

    def _open_out(self) -> None:
        # 一键进 UE 的产物是 UE 工程，这里优先跳到工程目录
        path = (getattr(self.host, "last_open_dir", "")
                or self._out_dir
                or exporter.load_settings().get("outdir", ""))
        if path and os.path.isfile(path) and path.lower().endswith(".uproject"):
            os.startfile(os.path.dirname(path))                  # noqa: S606
        elif path and os.path.isdir(path):
            os.startfile(path)                                   # noqa: S606
        elif path:
            os.startfile(os.path.dirname(path))                  # noqa: S606

    def _copy_cmd(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(" ".join(
            f'"{a}"' if " " in a else a for a in self._cmd))

    def _stop(self) -> None:
        self.host.stop_job()


# --------------------------------------------------------------- 工具页 --
class ToolsPage(QWidget):
    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self.host = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(_px(18), _px(14), _px(18), _px(14))
        lay.setSpacing(_px(12))
        lay.addWidget(_label("工具", 20, True))

        card = Section("环境检查")
        card.box.addWidget(_label("先确认目录、密钥、.NET 运行时都对，再去导图。结果会打到「任务」里。",
                                  12, False, "#9fb3c8"))
        row = QHBoxLayout()
        b1 = F.PrimaryPushButton("导出前检查 (doctor)")
        b1.clicked.connect(lambda: self._run("导出前检查", ["doctor"]))
        b2 = F.PushButton("挂载检查 (doctor --mount)")
        b2.clicked.connect(lambda: self._run("挂载检查", ["doctor", "--mount"]))
        b3 = F.PushButton("查看密钥 (keys)")
        b3.clicked.connect(lambda: self._run("查看密钥", ["keys"]))
        for b in (b1, b2, b3):
            b.setFixedHeight(_px(34))
            row.addWidget(b)
        row.addStretch(1)
        card.box.addLayout(row)
        lay.addWidget(card)

        card2 = Section("其它")
        row2 = QHBoxLayout()
        b4 = F.PushButton("打开导出器目录")
        b4.clicked.connect(self._open_tool_dir)
        b5 = F.PushButton("打开输出目录")
        b5.clicked.connect(self._open_out_dir)
        b6 = F.PushButton("用 Blender 打开（选择 split 目录）")
        b6.clicked.connect(self._blender)
        for b in (b4, b5, b6):
            b.setFixedHeight(_px(34))
            row2.addWidget(b)
        row2.addStretch(1)
        card2.box.addLayout(row2)
        lay.addWidget(card2)

        card3 = Section("临时文件")
        card3.box.addWidget(_label("清掉导出留下的预览缓存、分块原始文件（source-render/raw）、旧任务配置和旧日志。"
                                   "只动工具自己的目录，导出目录之外的东西一律不碰。", 12, False, "#9fb3c8"))
        row3 = QHBoxLayout()
        b7 = F.PushButton("清理临时文件…")
        b7.setFixedHeight(_px(34))
        b7.clicked.connect(self._cleanup)
        row3.addWidget(b7)
        row3.addStretch(1)
        card3.box.addLayout(row3)
        lay.addWidget(card3)
        lay.addStretch(1)

    def _run(self, title: str, argv: List[str]) -> None:
        exe = exporter.find_exe()
        if not exe:
            self.host.status("没找到 map-export.exe，先去「设置」里指定")
            return
        self.host.run_job(title, exporter._base_cmd(exe) + argv)

    def _cleanup(self) -> None:
        start = exporter.load_settings().get("outdir", "")
        folder = QFileDialog.getExistingDirectory(self, "选择要清理的导出目录", start)
        if not folder:
            return
        from core import cleanup
        plan = cleanup.plan(folder)
        if not plan["items"]:
            self.host.status("这个目录没有可清理的临时文件")
            return
        size = int(plan["size"]) / (1024 ** 3)
        if not F.confirm(self, "清理临时文件",
                         f"将删除 {len(plan['items'])} 项、约 {size:.2f} GB 的中间产物；"
                         "包括预览缓存、source-render/raw、旧任务配置和旧日志。"
                         "已经导出的 split/*.glb 与 .blend 不会动。"):
            return
        result = cleanup.clean(folder, log=self.host.status)
        self.host.status(cleanup.describe(result))

    def _open_tool_dir(self) -> None:
        exe = exporter.find_exe()
        if exe:
            os.startfile(os.path.dirname(exe))                   # noqa: S606

    def _open_out_dir(self) -> None:
        path = exporter.load_settings().get("outdir", "")
        if path and os.path.isdir(path):
            os.startfile(path)                                   # noqa: S606
        else:
            self.host.status("输出目录还不存在，先导一次")

    def _blender(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择导出的 split 目录",
                                                exporter.load_settings().get("outdir", ""))
        if not path:
            return
        blender = (exporter.load_settings().get("blender") or "").strip()
        exe = exporter.find_exe() or ""
        script = os.path.join(os.path.dirname(exe), "scripts", "blender_import_verified.py")
        if not blender or not os.path.isfile(blender):
            self.host.status("先在「设置」里指定 blender.exe")
            return
        out_blend = os.path.join(path, "import_" + time.strftime("%H%M%S") + ".blend")
        cmd = [blender, "--background", "--factory-startup", "--python-exit-code", "1",
               "--python", script, "--", path, "--save", out_blend]
        self.host.run_job("Blender 导入", cmd)


# --------------------------------------------------------------- 说明页 --
class DocsPage(QWidget):
    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self.host = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(_px(18), _px(14), _px(18), _px(14))
        lay.setSpacing(_px(10))
        lay.addWidget(_label("说明与教程", 20, True))

        split = QSplitter(Qt.Horizontal)
        lay.addWidget(split, 1)

        self.list = F.TableWidget(0,1)
        self.list.horizontalHeader().hide();self.list.verticalHeader().hide()
        self.list.horizontalHeader().setStretchLastSection(True)
        self.list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list.setFixedWidth(_px(260))
        self.list.currentCellChanged.connect(lambda row,*_:self._open(self.list.item(row,0)) if row>=0 else None)
        split.addWidget(self.list)

        self.view = F.CodeEditor()
        self.view.setReadOnly(True)
        split.addWidget(self.view)
        split.setSizes([_px(260), _px(800)])

        self._files: Dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        self.list.setRowCount(0)
        self._files.clear()
        bundled=os.path.join(getattr(sys,'_MEIPASS',os.path.dirname(os.path.dirname(__file__))),'docs')
        roots=[exporter.docs_dir(exporter.find_exe()),bundled]
        for root in dict.fromkeys(roots):
            if not root or not os.path.isdir(root):continue
            for name in sorted(os.listdir(root)):
                if not name.lower().endswith('.md'):continue
                path=os.path.join(root,name)
                title=name
                try:
                    with open(path,'r',encoding='utf-8-sig',errors='replace') as source:
                        for line in source:
                            if line.startswith('# '):
                                title=line[2:].strip()
                                break
                except OSError:
                    pass
                self._files[title]=path
        for title in self._files:
            row=self.list.rowCount();self.list.insertRow(row)
            self.list.setItem(row,0,QTableWidgetItem(title))
        if not self._files:self.view.set_code('没找到 docs 目录。')
        if self._files:
            self.list.setCurrentCell(0,0)
            self._open(self.list.item(0,0))

    def _open(self, item) -> None:
        path = self._files.get(item.text())
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except Exception as exc:                                 # noqa: BLE001
            self.view.set_code('读不了：'+str(exc))
            return
        self.view.set_code(text)


def _md_to_html(text: str) -> str:
    """够用的 Markdown → HTML：标题/列表/代码块/表格省略，只求能读。"""
    out: List[str] = ["<style>body{color:#e6edf6;font-size:13px;line-height:165%}"
                      "h1{font-size:20px} h2{font-size:17px;margin-top:18px}"
                      "code{background:#1b2330;padding:1px 4px;border-radius:4px}"
                      "pre{background:#0e141c;padding:10px;border-radius:8px;white-space:pre-wrap}"
                      "li{margin:2px 0}</style>"]
    in_code = False
    in_ul = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.strip().startswith("```"):
            if in_code:
                out.append("</pre>")
            else:
                out.append("<pre>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        if not line.strip():
            if in_ul:
                out.append("</ul>")
                in_ul = False
            continue
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            out.append(f"<h{min(level,3)}>{html.escape(line[level:].strip())}</h{min(level,3)}>")
            continue
        if line.lstrip().startswith(("- ", "* ")):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{html.escape(line.lstrip()[2:])}</li>")
            continue
        if line.startswith("|"):
            out.append(f"<div style='font-family:Consolas;font-size:12px'>{html.escape(line)}</div>")
            continue
        out.append(f"<p>{html.escape(line)}</p>")
    if in_ul:
        out.append("</ul>")
    if in_code:
        out.append("</pre>")
    return "".join(out)


# --------------------------------------------------------------- 设置页 --
class SettingsPage(QWidget):
    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self.host = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(_px(18), _px(14), _px(18), _px(14))
        lay.setSpacing(_px(12))
        lay.addWidget(_label("设置", 20, True))

        card = Section("路径")
        self.exe_edit = self._row(card, "map-export.exe", self._pick_file)
        self.exe_edit.setReadOnly(True)
        self.exe_edit.setToolTip('固定使用指定导出器版本；不会切换到历史设置中的其他导出器')
        self.paks_edit = self._row(card, "游戏 Paks 目录", self._pick_dir)
        self.key_edit = self._row(card, "密钥 JSON", self._pick_file)
        self.out_edit = self._row(card, "默认输出目录", self._pick_dir)
        self.blend_edit = self._row(card, "blender.exe（可选）", self._pick_file)
        lay.addWidget(card)

        card2 = Section("游戏 Profile")
        row = QHBoxLayout()
        row.addWidget(_label("Game", 12))
        self.game_edit = F.LineEdit()
        self.game_edit.setFixedHeight(_px(30))
        row.addWidget(self.game_edit, 1)
        row.addWidget(_label("一般就是 GAME_DeltaForce", 11, False, "#9fb3c8"))
        card2.box.addLayout(row)
        lay.addWidget(card2)

        card4 = Section("导出后清理")
        self.cb_auto = F.CheckBox("导出成功后自动清理临时文件（预览缓存、分块原始文件、旧任务配置与旧日志）")
        self.cb_auto.setChecked(True)
        card4.box.addWidget(self.cb_auto)
        self.cb_keepraw = F.CheckBox("保留 source-render/raw（只在需要重新生成 Blender 工程时才有用）")
        card4.box.addWidget(self.cb_keepraw)
        lay.addWidget(card4)

        row3 = QHBoxLayout()
        save = F.PrimaryPushButton("保存")
        save.setFixedHeight(_px(36))
        save.clicked.connect(self.save)
        check = F.PushButton("保存并检查")
        check.setFixedHeight(_px(36))
        check.clicked.connect(lambda: (self.save(), window.jump_tools_check()))
        row3.addWidget(save)
        row3.addWidget(check)
        wizard = F.PushButton("重看首次向导")
        wizard.setFixedHeight(_px(36))
        wizard.clicked.connect(self._replay_wizard)
        row3.addWidget(wizard)
        row3.addStretch(1)
        lay.addLayout(row3)
        lay.addStretch(1)

        self.load()

    def _replay_wizard(self):
        from app.wizard import WizardWindow
        current = getattr(self, '_wizard', None)
        if current and current.isVisible():
            current.raise_()
            return
        self._wizard = WizardWindow()
        self._wizard.finished.connect(lambda _ok: self.host.refresh_pages())
        self._wizard.start()

    def _row(self, card: Section, label: str, picker) -> QLineEdit:
        row = QHBoxLayout()
        lab = _label(label, 12)
        lab.setFixedWidth(_px(140))
        row.addWidget(lab)
        edit = F.LineEdit()
        edit.setFixedHeight(_px(30))
        row.addWidget(edit, 1)
        btn = F.PushButton("选择…")
        btn.setFixedHeight(_px(30))
        btn.clicked.connect(lambda: picker(edit))
        row.addWidget(btn)
        card.box.addLayout(row)
        return edit

    def _pick_file(self, edit: QLineEdit) -> None:
        if edit is self.exe_edit:
            self.host.status('导出器已固定为指定导出器版本')
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择文件", edit.text() or "")
        if path:
            edit.setText(path)

    def _pick_dir(self, edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择目录", edit.text() or "")
        if path:
            edit.setText(path)

    def load(self) -> None:
        s = exporter.load_settings()
        self.exe_edit.setText(exporter.find_exe() or '')
        self.paks_edit.setText(str(s.get("paks") or ""))
        # 设置里那条路径可能来自别的电脑，先显示真正能找到的那份，省得用户以为没配
        self.key_edit.setText(exporter.resolve_keyfile(s) or str(s.get("keyfile") or ""))
        self.out_edit.setText(str(s.get("outdir") or ""))
        self.blend_edit.setText(str(s.get("blender") or ""))
        self.game_edit.setText(str(s.get("game") or "GAME_DeltaForce"))
        self.cb_auto.setChecked(bool(s.get("auto_clean", True)))
        self.cb_keepraw.setChecked(bool(s.get("keep_raw", False)))
        if not self.exe_edit.text():
            found = exporter.find_exe()
            if found:
                self.exe_edit.setText(found)

    def save(self) -> None:
        data = exporter.load_settings()
        data["exe"] = self.exe_edit.text().strip()
        data["paks"] = self.paks_edit.text().strip()
        data["keyfile"] = self.key_edit.text().strip()
        data["outdir"] = self.out_edit.text().strip()
        data["blender"] = self.blend_edit.text().strip()
        data["game"] = self.game_edit.text().strip() or "GAME_DeltaForce"
        data["auto_clean"] = self.cb_auto.isChecked()
        data["keep_raw"] = self.cb_keepraw.isChecked()
        exporter.save_settings(data)
        exporter.write_exporter_config(data)
        self.host.status("设置已保存")
        self.host.refresh_pages()
