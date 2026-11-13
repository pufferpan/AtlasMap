"""其他游戏：选目录 → 逐包问密钥 → 列 .umap → 导出并导进 Blender。

和 Delta Force 那条一键流程分开：别的游戏没有固定的地图目录、也没有固定的
密钥文件，所以这里把「探测哪些包加密、还缺哪几把钥匙」做成一步一步问清楚，
最后同样落到 `<输出目录>/split/manifest.json`，Blender 侧照旧走 --flat-split。
"""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QVBoxLayout,
                               QWidget)
from fluentpy import widgets as W

from app import fluent_api as F
from app.ui_scale import px as _px
from core import exporter, generic


def _app_root() -> str:
    import sys
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return str(Path(__file__).resolve().parents[1])


class GenericDialog(W.FramelessDialog):
    """导出其他游戏的单张 .umap。"""

    _done = Signal(object, str)

    def __init__(self, parent, *, oodle: str = "", blender: str = ""):
        super().__init__("导出其他游戏的 .umap",
                         "选游戏目录 → 检测加密包并逐包填密钥 → 列出 .umap → 导出。", parent)
        self.setWindowTitle("导出其他游戏的 .umap")
        self.setMinimumWidth(_px(720))
        self._oodle = oodle or ""
        self._blender = blender or ""
        self._config = ""
        self._maps: List[str] = []
        self._busy = False
        self._done.connect(self._on_done)

        body = QWidget(self)
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(_px(10))

        root.addWidget(self._label("游戏目录（含 Content/Paks 的那一层，或直接选游戏根目录）", 13))
        self.ed_root = F.LineEdit()
        self.ed_root.setPlaceholderText(r"例如 G:\SteamLibrary\steamapps\common\SomeGame")
        root.addLayout(self._with_button(self.ed_root, "浏览…", self._browse_root))

        row = QHBoxLayout()
        row.addWidget(self._label("引擎版本", 12))
        self.cb_profile = F.ComboBox()
        for name in generic.PROFILES:
            self.cb_profile.addItem(name)
        self.cb_profile.setCurrentText("GAME_UE5_3")
        self.cb_profile.setMinimumWidth(_px(160))
        row.addWidget(self.cb_profile)
        row.addStretch(1)
        self.btn_probe = F.PushButton("检测 / 填密钥")
        self.btn_probe.clicked.connect(self._probe_clicked)
        row.addWidget(self.btn_probe)
        root.addLayout(row)

        root.addWidget(self._label("地图（.umap）", 13))
        self.cb_map = F.EditableComboBox()
        self.cb_map.setMinimumWidth(_px(320))
        root.addLayout(self._with_button(self.cb_map, "列出地图", self._list_clicked))

        root.addWidget(self._label("输出目录", 13))
        self.ed_out = F.LineEdit()
        self.ed_out.setPlaceholderText("留空则用 <游戏目录>_export")
        root.addLayout(self._with_button(self.ed_out, "浏览…", self._browse_out))

        self.lab_status = self._label("先选游戏目录，然后点「检测 / 填密钥」。", 12, "#9aa4b2")
        self.lab_status.setWordWrap(True)
        root.addWidget(self.lab_status)
        root.addStretch(1)

        self.add_content_widget(body)
        self.setYesButtonText("开始导出")
        self.setCancelButtonText("关闭")
        try:
            self.yes_button.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.yes_button.clicked.connect(self._export_clicked)
        self.btn_export = self.yes_button
        self.btn_close = self.cancel_button

    # ------------------------------------------------------------- 小工具 --
    @staticmethod
    def _label(text: str, size: int = 12, color: str = "") -> QLabel:
        lab = QLabel(text)
        style = f"font-size:{_px(size)}px;"
        if color:
            style += f"color:{color};"
        lab.setStyleSheet(style)
        return lab

    def _with_button(self, widget, text: str, slot) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(widget, 1)
        button = F.PushButton(text)
        button.clicked.connect(slot)
        row.addWidget(button)
        return row

    def _say(self, text: str) -> None:
        self.lab_status.setText(text)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (self.btn_probe, self.btn_export, self.btn_close):
            widget.setEnabled(not busy)

    def _async(self, label: str, work: Callable[[], object]) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._say(label + "…")

        def run() -> None:
            try:
                self._done.emit(work(), "")
            except Exception as exc:                     # noqa: BLE001
                self._done.emit(None, f"{type(exc).__name__}: {exc}")

        threading.Thread(target=run, daemon=True).start()

    def _on_done(self, payload, error: str) -> None:
        self._set_busy(False)
        if error:
            self._say("出错：" + error)
            return
        handler = getattr(self, "_after", None)
        if handler:
            self._after = None
            handler(payload)

    # --------------------------------------------------------------- 选择 --
    def _browse_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择游戏目录", self.ed_root.text() or "")
        if folder:
            self.ed_root.setText(folder)
            self._detect_paks()

    def _browse_out(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录", self.ed_out.text() or "")
        if folder:
            self.ed_out.setText(folder)

    def _detect_paks(self) -> Optional[str]:
        root = self.ed_root.text().strip()
        if not root:
            return None
        dirs = generic.paks_dirs(root)
        if not dirs:
            self._say("这个目录里没找到 Content/Paks：请选到含 Paks 的那一层，或选游戏根目录。")
            return None
        self._paks = dirs[0]
        self._say("找到包目录：" + dirs[0])
        return dirs[0]

    # --------------------------------------------------------------- 探测 --
    def _config_path(self) -> str:
        base = Path(exporter.app_dir()) / "generic"
        stem = Path(self._paks).parent.parent.name or "game"
        return str(base / f"config-{stem}.json")

    def _write_config(self, keyfile: str = "") -> str:
        return generic.write_config(self._config_path(), self._paks,
                                    self.cb_profile.currentText() or "GAME_UE5_3",
                                    keyfile=keyfile, oodle=self._oodle)

    def _probe_clicked(self) -> None:
        paks = getattr(self, "_paks", None) or self._detect_paks()
        if not paks:
            return
        self._config = self._write_config()
        exe = exporter.find_exe() or ""
        if not exe:
            self._say("找不到 map-export.exe，请先点「设置」检查导出器路径。")
            return

        def work():
            code, data, _err = generic.probe(exe, self._config)
            return code, data

        self._after = self._after_probe
        self._async("正在检测包是否需要密钥", work)

    def _after_probe(self, payload) -> None:
        _code, data = payload
        if not data:
            self._say("检测失败：导出器没给出结果，请确认目录和引擎版本。")
            return
        pending = generic.pending(data)
        if not pending:
            self._say(f"可以导出：已挂载 {data.get('mounted', 0)} 个包、{data.get('files', 0)} 个文件。")
            self._ask_maps_after = True
            return
        self._ask_keys(pending)

    def _ask_keys(self, pending: List[dict]) -> None:
        """一张一张问：有几个加密包就问几次，主密钥归 GUID 全零的那些。"""
        main_key = ""
        guid_keys = {}
        for row in pending:
            here = row.get("guid") or ""
            title = "这把密钥用在哪个包上"
            hint = (f"包：{row['file']}\n这里要的是主密钥（32 字节，64 个十六进制字符）。"
                    if not here else
                    f"包：{row['file']}\n这个包有独立 GUID（{here}），需要它专属的密钥。")
            value = self._ask_key(title, hint)
            if value is None:
                self._say("还剩加密包没给密钥，导出会失败。可以再点「检测 / 填密钥」继续。")
                return
            if here:
                guid_keys[here] = value
            else:
                main_key = value
        keys_path = str(Path(exporter.app_dir()) / "generic" / "keys.json")
        try:
            generic.write_keys(keys_path, main_key, guid_keys)
        except ValueError as exc:
            self._say(str(exc))
            return
        self._config = self._write_config(keyfile=keys_path)
        exe = exporter.find_exe() or ""

        def work():
            code, data, _err = generic.probe(exe, self._config)
            return code, data, len(generic.pending(data))

        def after(payload) -> None:
            code, data, left = payload
            if left:
                self._say(f"还有 {left} 个包没挂上：可能密钥不对，或者这套 IoStore 版本暂不支持。")
            else:
                self._say(f"密钥通过：已挂载 {data.get('mounted', 0)} 个包、{data.get('files', 0)} 个文件。")

        self._after = after
        self._async("正在验证密钥", work)

    def _ask_key(self, title: str, hint: str) -> Optional[str]:
        from app.fluent_controls import Dialog
        from fluentpy import widgets as W
        dialog = Dialog(title, hint, self)
        field = F.LineEdit()
        field.setPlaceholderText("粘贴 32 字节密钥，例如 0xA1B2… 或连续 64 位 hex")
        dialog.add_content_widget(field)
        dialog.setYesButtonText("用这把")
        dialog.setCancelButtonText("先跳过")
        if dialog.exec() != W.FramelessDialog.DialogCode.Accepted:
            return None
        try:
            return generic.hex_key(field.text())
        except ValueError as exc:
            self._say(str(exc))
            return None

    # --------------------------------------------------------------- 地图 --
    def _list_clicked(self) -> None:
        if not self._config:
            self._probe_clicked()
            return
        exe = exporter.find_exe() or ""

        def work():
            return generic.list_maps(exe, self._config)

        def after(payload) -> None:
            code, maps, _err = payload
            self._maps = maps
            self.cb_map.clear()
            for path in maps:
                self.cb_map.addItem(path)
            if maps:
                self._say(f"找到 {len(maps)} 张 .umap" + ("（只列了前几张）" if code not in (0, 3) else ""))
            else:
                self._say("没有列出 .umap：确认引擎版本选对了，或者包还没挂上。")

        self._after = after
        self._async("正在扫描 .umap", work)

    # --------------------------------------------------------------- 导出 --
    def _export_clicked(self) -> None:
        vpath = (self.cb_map.currentText() or "").strip()
        if not vpath:
            self._say("先点「列出地图」，选一张 .umap。")
            return
        root = (self.ed_root.text() or "").strip()
        out = (self.ed_out.text() or "").strip() or (root.rstrip("\\/") + "_export")
        stem = Path(vpath).stem
        dest = str(Path(out) / stem)
        Path(dest).mkdir(parents=True, exist_ok=True)
        exe = exporter.find_exe() or ""
        config = self._config
        script = os.path.join(_app_root(), "scripts", "official", "blender_iceland.py")
        blender = self._blender

        def work():
            run = generic.export_map(exe, config, vpath, dest)
            log = (run.stdout or "")[-4000:] + (run.stderr or "")[-2000:]
            (Path(dest) / "export.log").write_text(log, encoding="utf-8")
            if run.returncode != 0:
                raise RuntimeError(f"导出器退出码 {run.returncode}：" + log[-400:])
            levels, instances = generic._instances(dest)
            if instances == 0:
                raise RuntimeError(
                    "这张 .umap 和它所在目录都没有可导出的网格（可能是纯配置关卡）。"
                    "换一张地图，或者先确认包的引擎版本选对了。")
            blend = Path(dest) / "scene_no_terrain.blend"
            if blender and os.path.isfile(blender) and os.path.isfile(script):
                import subprocess
                cmd = [blender, "-b", "--python-exit-code", "1",
                       "-P", script, "--", dest, "--flat-split"]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600,
                                      encoding="utf-8", errors="replace")
                text = (proc.stdout or "") + "\n" + (proc.stderr or "")
                (Path(dest) / "blender.log").write_text(text, encoding="utf-8")
                if proc.returncode != 0:
                    tail = [line for line in text.splitlines() if line.strip()][-6:]
                    raise RuntimeError("Blender 导入失败（退出码 %d）：\n%s\n完整日志：%s"
                                       % (proc.returncode, "\n".join(tail),
                                          Path(dest) / "blender.log"))
            return str(blend) if blend.is_file() else dest

        def after(result) -> None:
            self._say("完成：" + str(result))

        self._after = after
        self._async(f"正在导出 {stem}", work)
