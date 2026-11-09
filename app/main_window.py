"""主窗口：套同系列查看器那层 Fluent 导航 + 状态栏。

功能页面都在 `app/pages.py`，这里只负责：装导航、跑任务、把日志送到任务页。
"""
from __future__ import annotations

import os
from collections import deque
import threading
from typing import List, Optional

from PySide6.QtCore import QObject, QRect, Qt, QTimer, Signal, QStandardPaths
from PySide6.QtWidgets import QApplication, QFileDialog, QVBoxLayout, QWidget

from app import fluent_api as F
from app import ui_scale as _ui
from app.pages import DocsPage, JobPage, MapPage, SettingsPage, ToolsPage
from app.ue_page import UePage
from app.projects_page import ProjectsPage
from app.ue_logo import ue_icon
from app.ui_scale import px as _px
from core import exporter

TITLEBAR_LIGHT = "#eef3f9"
TITLEBAR_DARK = "#16181d"


class _TaskBridge(QObject):
    """把「后台线程算完」的结果搬回 GUI 线程。"""

    done = Signal(object)

    def __init__(self, on_done) -> None:
        super().__init__()
        self._on_done = on_done
        self.done.connect(self._emit, Qt.QueuedConnection)

    def _emit(self, value) -> None:
        try:
            self._on_done(value)
        except Exception:                                        # noqa: BLE001
            pass


class _JobBridge(QObject):
    """把子进程读线程里的回调搬回 GUI 线程（直接跨线程碰控件会卡死/崩）。"""

    line = Signal(str)
    done = Signal(int)
    progress = Signal(int, int, str)
    wake = Signal()

    def __init__(self, on_line, on_done, on_progress=None, on_lines=None) -> None:
        super().__init__()
        self._on_line = on_line
        self._on_done = on_done
        self._on_progress = on_progress
        self._on_lines = on_lines
        self._lines = deque()
        self._lock = threading.Lock()
        self._scheduled = False
        self._pending_done = None
        self._drain_timer = QTimer(self)
        self._drain_timer.setSingleShot(True)
        self._drain_timer.timeout.connect(self._drain)
        self.wake.connect(self._drain, Qt.QueuedConnection)
        self.line.connect(self._emit_line, Qt.QueuedConnection)
        self.done.connect(self._emit_done, Qt.QueuedConnection)
        self.progress.connect(self._emit_progress, Qt.QueuedConnection)

    def _emit_progress(self, done: int, total: int, name: str) -> None:
        if self._on_progress:
            self._on_progress(done, total, name)

    def _emit_line(self, text: str) -> None:
        try:
            self._on_line(text)
        except Exception:                                        # noqa: BLE001
            pass

    def _emit_done(self, code: int) -> None:
        with self._lock:
            pending = bool(self._lines)
        if pending:
            self._pending_done = code
            return
        self._deliver_done(code)

    def _deliver_done(self, code):
        try:
            self._on_done(code)
        except Exception:                                        # noqa: BLE001
            pass

    def enqueue(self, text):
        self._enqueue_event('line', text)

    def enqueue_progress(self, *values):
        self._enqueue_event('progress', values)

    def _enqueue_event(self, kind, payload):
        with self._lock:
            self._lines.append((kind, payload))
            wake = not self._scheduled
            self._scheduled = True
        if wake:
            self.wake.emit()

    def _drain(self):
        with self._lock:
            batch = [self._lines.popleft() for _ in range(min(128, len(self._lines)))]
        lines = []
        def flush():
            if self._on_lines:
                self._on_lines(lines)
            else:
                for line in lines:
                    self._emit_line(line)
            lines.clear()
        for kind, value in batch:
            if kind == 'progress':
                flush()
                self._emit_progress(*value)
            else:
                lines.append(value)
        flush()
        with self._lock:
            more = bool(self._lines)
            if not more:
                self._scheduled = False
        if more:
            self._drain_timer.start(8)
        elif self._pending_done is not None:
            code, self._pending_done = self._pending_done, None
            self._deliver_done(code)


class MapViewerWindow(F.FluentWindow):
    def __init__(self, parent=None) -> None:
        super().__init__("AtlasMap",parent)
        self.setObjectName("AtlasMapWindow")
        try:
            from app.version import stamp
            ver = f"  ·  {stamp()}"
        except Exception:                                        # noqa: BLE001
            ver = ""
        self.setWindowTitle("AtlasMap · 地图导出器" + ver)
        w, h = _ui.fit(1440, 900)
        self.resize(w, h)
        self.setMinimumSize(*_ui.min_size(1040, 660))

        self.job = None
        self._last_lines: List[str] = []
        self._bridge = None
        self._task_bridges: List[object] = []
        self._task_log = None
        self._task_log_error = ''
        QApplication.instance().aboutToQuit.connect(self._close_task_log)

        self.map_page = MapPage(self, self)
        self.job_page = JobPage(self, self)
        self.tools_page = ToolsPage(self, self)
        self.docs_page = DocsPage(self, self)
        self.settings_page = SettingsPage(self, self)
        self.ue_page = UePage(self, self)
        self.projects_page = ProjectsPage(self)

        self.addSubInterface(self.ue_page, ue_icon(), "一键导出")
        self.addSubInterface(self.projects_page, F.icon("folder"), "我的工程")
        self.addSubInterface(self.map_page, F.icon("library"), "地图")
        self.addSubInterface(self.job_page, F.icon("play"), "任务")
        self.addSubInterface(self.tools_page, F.icon("setting"), "工具")
        self.addSubInterface(self.docs_page, F.icon("info"), "说明")
        self.addSubInterface(self.settings_page, F.icon("setting"), "设置")

        try:
            self.set_background_colors(TITLEBAR_LIGHT, TITLEBAR_DARK)
            self.set_title_bar_enabled(True)
        except Exception:                                        # noqa: BLE001
            pass

        self.status("就绪 · 选择地图与保存位置后，一键导出；旧工程可在「我的工程」中添加")
        # 没有配置过的话，第一次进来顺手把默认值落盘
        if not os.path.isfile(exporter.settings_path()):
            exporter.save_settings(exporter.load_settings())
        exporter.write_exporter_config()
        QTimer.singleShot(600, self._first_hint)
        self.set_parallel_theme(self.ue_page.chk_parallel.isChecked())
        self.set_advanced_mode(self.ue_page.advanced_switch.isChecked())
        self._restore_failure()

    def _restore_failure(self):
        from core.export_failure import latest_failure
        from core.task_log import TaskLog
        report=latest_failure(os.path.join(exporter.app_dir(),'logs'))
        if report is None:return
        self._failure_report=report
        self._task_log=TaskLog.open_existing(report.log_path)
        self.job_page.begin('上次导出失败',[])
        self.job_page.finish(report.exit_code,report)
        self.job_page.save_log_btn.setEnabled(True)
        self.switchTo(self.job_page)
        self.status('上次导出失败：'+report.title+'；任务页已显示原因和处理建议')

    def set_advanced_mode(self, enabled):
        navigation = self.navigation_view()
        navigation.set_route_visible(navigation.route_for_widget(self.tools_page), enabled)

    def set_parallel_theme(self, enabled):
        self._parallel_theme = bool(enabled)
        F.apply_fluent_theme(True, '#D13438' if enabled else '#2B579A')
        self.set_background_colors('#fff1f1' if enabled else TITLEBAR_LIGHT,
                                   '#241316' if enabled else TITLEBAR_DARK)

    def closeEvent(self, event):
        if getattr(self,'_cleanup_pending',False):
            self.status('正在处理导出残留，请等待清理完成或先选择保留文件')
            event.ignore()
            return
        if getattr(self, '_project_mutation', False):
            self.status('正在移动或删除工程，请完成后再关闭软件')
            event.ignore()
            return
        super().closeEvent(event)

    # ---- 状态 ----
    def status(self, text: str) -> None:
        try:
            self.statusBar().showMessage(text, 12000)
        except Exception:                                        # noqa: BLE001
            pass

    def _first_hint(self) -> None:
        if not exporter.find_exe():
            self.status("没找到 map-export.exe —— 到「设置 → map-export.exe」指一下")

    def refresh_pages(self) -> None:
        self.map_page.reload_presets()
        self.docs_page.reload()

    def jump_tools_check(self) -> None:
        self.tools_page._run("导出前检查", ["doctor"])          # noqa: SLF001

    # ---- 完整任务日志 ----
    def _close_task_log(self):
        if self._task_log is not None:
            self._task_log.close()

    def _begin_task_log(self, title, commands):
        from core.task_log import TaskLog
        from app.version import stamp
        self._close_task_log()
        self._task_log_error = ''
        self._failure_report = None
        try:
            self._task_log = TaskLog(os.path.join(exporter.app_dir(),'logs'), title, commands, stamp())
        except OSError as error:
            self._task_log = None
            self._task_log_error = str(error)
            self.status('无法记录完整日志：'+str(error))
        self.job_page.save_log_btn.setEnabled(self._task_log is not None)
        return self._task_log

    def _log_callbacks(self, task_log, bridge):
        from core.export_failure import FailureTracker
        from dataclasses import replace
        tracker=FailureTracker(self.job_page.title.text())
        warned = False
        warning_lock = threading.Lock()
        def output(line):
            nonlocal warned
            tracker.observe(line)
            if task_log is not None and not task_log.append(line):
                with warning_lock:
                    if not warned:
                        warned = True
                        bridge.enqueue('[完整日志写入失败] '+task_log.error)
            bridge.enqueue(line)
        def done(code):
            report=tracker.finish(code)
            if code in (0,-2,130):report=None
            if report is not None:
                report=replace(report,log_path=str(task_log.path) if task_log else '')
                if task_log:task_log.append('[失败原因]\n'+report.text())
            self._failure_report=report
            if task_log is not None:
                task_log.finish(code)
                if task_log.error:bridge.enqueue('[完整日志写入失败] '+task_log.error)
            bridge.done.emit(code)
        return output, done

    def export_full_log(self):
        task_log = self._task_log
        parent = QApplication.activeWindow() or self
        if task_log is None:
            F.message(parent,'导出完整日志',
                '无法记录完整日志：'+self._task_log_error if self._task_log_error else '当前还没有可导出的任务日志，请先运行任务。')
            return
        directory = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser('~')
        path, selected = QFileDialog.getSaveFileName(parent,'导出完整日志',
            os.path.join(directory,task_log.path.name),'文本日志 (*.txt);;日志文件 (*.log)')
        if not path:return
        if not os.path.splitext(path)[1]:path += '.log' if selected.startswith('日志文件') else '.txt'
        self.status('正在保存完整日志…')
        def saved(result):
            if isinstance(result,Exception):
                F.message(parent,'日志保存失败',str(result),warning=True)
            else:
                self.status('完整日志已保存：'+result)
                if getattr(self,'_overlay',None) is not None:
                    self._overlay.feed('完整日志已保存：'+result)
        self.run_async(lambda:task_log.export(path),saved)

    # ---- 任务 ----
    def run_job(self, title: str, cmd: List[str], on_done=None,
                on_line=None) -> Optional[object]:
        """起一条命令，日志进「任务」页，完成后回调。"""
        if not cmd:
            return None
        if getattr(self, '_project_mutation', False):
            self.status('正在移动或删除工程，请稍候')
            return None
        if getattr(self,'_cleanup_pending',False):
            self.status('请先处理上次导出的残留文件')
            return None
        if self.job is not None and getattr(self.job, "running", False):
            self.status("还有任务在跑，先等它结束或者点「停止」")
            return None
        self._last_lines = []
        task_log = self._begin_task_log(title,cmd)
        self.job_page.begin(title, cmd)
        if self._task_log_error:self.job_page.append('[完整日志不可用] '+self._task_log_error)
        self.status(f"开始：{title}")

        stats = {"n": 0, "shown": 0}

        def push_line(line: str) -> None:
            stats["n"] += 1
            # 只留最近 20000 行做统计，界面每 200 行刷一次，避免几十万行把 QTextEdit 拖死
            if len(self._last_lines) < 20000:
                self._last_lines.append(line)
            if stats["shown"] < 4000:
                stats["shown"] += 1
                self.job_page.append(line)
            elif stats["n"] % 500 == 0:
                self.job_page.append(f"… 已读 {stats['n']:,} 行（日志太多，界面只显示前 4000 行）")
            if on_line is not None:
                on_line(line)

        def done(code: int) -> None:
            report=getattr(self,'_failure_report',None)
            self.job_page.finish(code,report)
            self.status(f"{title}："+('完成' if code==0 else report.title if report else '已取消' if code in (-2,130) else f'失败（{code}）'))
            if on_done:
                on_done(code)

        self._bridge = _JobBridge(push_line, done)
        capture, finished = self._log_callbacks(task_log,self._bridge)
        self.job = exporter.start(cmd, on_line=capture,
                               on_done=finished, title=title)
        return self.job

    def run_pipeline(self, title: str, steps, on_done=None, on_line=None,
                     on_progress=None, residue=None):
        """把一串步骤当一条任务跑：日志进任务页，进度回调给导出小窗。"""
        if getattr(self, '_project_mutation', False):
            self.status('正在移动或删除工程，请稍候')
            return None
        if getattr(self,'_cleanup_pending',False):
            self.status('请先处理上次导出的残留文件')
            return None
        if self.job is not None and getattr(self.job, "running", False):
            self.status("还有任务在跑，先等它结束或者点「停止」")
            return None
        from core import ue_pipeline

        self._last_lines = []
        task_log = self._begin_task_log(title,[dict(step=s.name,command=s.cmd) for s in steps])
        self.job_page.begin(title, [s.name for s in steps])
        if self._task_log_error:self.job_page.append('[完整日志不可用] '+self._task_log_error)
        self.status(f"开始：{title}")

        stats = {"n": 0, "shown": 0}

        def push_line(line: str) -> None:
            stats["n"] += 1
            if len(self._last_lines) < 20000:
                self._last_lines.append(line)
            if stats["shown"] < 4000:
                stats["shown"] += 1
                self.job_page.append(line)
            if on_line is not None:
                on_line(line)

        def done(code: int) -> None:
            report=getattr(self,'_failure_report',None)
            self.job_page.finish(code,report)
            self.status(f"{title}："+('完成' if code==0 else report.title if report else '已取消' if code in (-2,130) else f'失败（{code}）'))
            if on_done:
                on_done(code)
            if code != 0 and residue is not None:
                self._ask_export_cleanup(residue,code)

        def push_lines(lines):
            available = max(0, 20000 - len(self._last_lines))
            self._last_lines.extend(lines[:available])
            shown = lines[:max(0, 4000 - stats['shown'])]
            if shown:
                self.job_page.append('\n'.join(shown))
                stats['shown'] += len(shown)
            stats['n'] += len(lines)
            if on_line:
                for line in lines:
                    on_line(line)

        self._bridge = _JobBridge(push_line, done, on_progress, on_lines=push_lines)
        capture, finished = self._log_callbacks(task_log,self._bridge)
        pipe = ue_pipeline.Pipeline(
            steps, on_line=capture,
            on_progress=self._bridge.enqueue_progress if on_progress else None,
            on_done=finished,
            residue=residue,
        )
        self.job = pipe.start()
        return self.job

    def _ask_export_cleanup(self, plan, code):
        from app.export_cleanup import cleanup_question
        overlay=getattr(self,'_overlay',None)
        windows=getattr(overlay,'windows',[overlay]) if overlay is not None else []
        island=getattr(overlay,'_island',None)
        parent=island.pill if island is not None and island.pill.isVisible() else next(
            (w for w in windows if w is not None and w.isVisible()),self)
        dialog=cleanup_question(parent,plan,code)
        self._cleanup_dialog=dialog
        self._cleanup_pending=True
        def log(text):
            if self._task_log is not None:self._task_log.append(text)
            self.job_page.append(text)
            self.status(text)
            if overlay is not None:
                try:overlay.feed(text)
                except RuntimeError:pass  # A closed progress window cannot stop cleanup.
        progress={}
        timer=QTimer(self);timer.setInterval(1000)
        def show_progress():
            if progress:
                log(f'正在清理残留：{progress["done"]:,}/{progress["total"]:,}；'
                    f'已删除 {progress["removed"]:,} 个，约 {progress["removed_bytes"]/1024**3:.2f} GB')
        timer.timeout.connect(show_progress)
        def cleaned(result):
            timer.stop();timer.deleteLater()
            self._cleanup_pending=False
            if isinstance(result,Exception):log('残留清理失败：'+str(result));return
            log(f'已清理 {result["removed"]:,} 个残留文件；保留 {len(result["skipped"]):,} 个被修改、占用或无法安全删除的文件。')
            if result.get('errors'):
                log('未删除文件及原因：\n'+'\n'.join(f'{p}：{reason}' for p,reason in result['errors'].items()))
            if self._task_log is not None:self._task_log.close()
        def answered(_):
            remove=dialog.result()==type(dialog).DialogCode.Accepted
            self._cleanup_dialog=None
            dialog.deleteLater()
            if remove:
                log('正在后台清理本次残留文件…')
                timer.start()
                self.run_async(lambda:plan.delete(on_progress=progress.update),cleaned)
            else:
                timer.deleteLater()
                self._cleanup_pending=False
                log('已保留本次导出文件，可查看日志或重新导出。')
        dialog.finished.connect(answered)
        dialog.open()

    def run_async(self, fn, on_done=None) -> None:
        """在后台线程跑一个函数，结果用 queued signal 回到 GUI 线程。"""
        import threading

        bridge = _TaskBridge(on_done or (lambda _v: None))
        self._task_bridges.append(bridge)          # 防 GC

        def worker() -> None:
            try:
                value = fn()
            except Exception as exc:                             # noqa: BLE001
                value = exc
            bridge.done.emit(value)

        threading.Thread(target=worker, daemon=True).start()

    def show_export_overlay(self, title: str, out_dir: str = "", parallel_count: int = 0,preview=None):
        """把主窗口就地变成导出小窗口（由大至小），关掉后再变回来。"""
        from app.export_window import ExportWindow
        start = QRect(self.geometry())
        self._restore_rect = start
        self.hide()                      # 导出卡片从此位置平滑缩小到右下角。
        if parallel_count:
            from app.parallel_export_windows import ParallelExportWindows
            win = ParallelExportWindows(self, parallel_count)
        else:
            win = ExportWindow(None)
        win.stop_requested.connect(self.stop_job)
        win.save_log_requested.connect(self.export_full_log)
        win.log_requested.connect(lambda:(self.show(),self.switchTo(self.job_page),self.raise_()))
        win.closed.connect(self._after_export_window)
        win.begin(title, "请勿操作，导出结束后会自动收起", start_rect=start)
        if preview is not None:
            from app.map_preview import MapPreview
            previous=getattr(self,'_map_preview',None)
            if previous is not None:previous.close();previous.deleteLater()
            self._map_preview=MapPreview(preview,self)
            win.bind_preview(self._map_preview)
        self._overlay = win
        return win

    def _after_export_window(self) -> None:
        """导出小窗关掉后，主窗口回到原来的位置和大小。"""
        try:
            if getattr(self, "_restore_rect", None) is not None:
                self.setGeometry(self._restore_rect)
        except Exception:                                       # noqa: BLE001
            pass
        self.show()
        self.raise_()
        self.activateWindow()
        self._overlay = None
        preview=getattr(self,'_map_preview',None)
        if preview is not None:preview.close()

    def stop_job(self) -> None:
        if self.job is not None and getattr(self.job, "running", False):
            self.job.stop()
            self.status("已请求停止")

    def last_job_lines(self) -> List[str]:
        return list(self._last_lines)

    def show_command(self, cmd: List[str]) -> None:
        self.job_page.begin("只看命令行", cmd)
        for line in cmd:
            self.job_page.append(line)
        self.job_page.finish(0)
        self.status("命令行已打到「任务」页，可直接复制")
