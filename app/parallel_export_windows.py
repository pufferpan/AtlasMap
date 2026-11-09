"""A group of tiled progress windows with one cancellation lifecycle."""
import json
import math
import re

from PySide6.QtCore import QEasingCurve, QObject, QRect, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from app.export_window import ExportWindow
from app.export_celebration import success_artwork

INTRO_MS = 420
SPLIT_MS = 420
SPLIT_HOLD_MS = 20
SPLIT_STAGGER_MS = 12


def desktop_capacity(area=None):
    screen = QGuiApplication.primaryScreen()
    area = area or (screen.availableGeometry() if screen else QRect(0, 0, 1600, 900))
    return max(2, min(8, (area.width() // 320) * (area.height() // 300)))


def tile_rects(area, count):
    options = []
    for columns in range(1, count + 1):
        rows = math.ceil(count / columns)
        width, height = area.width() // columns, area.height() // rows
        if width >= 320 and height >= 300:
            options.append(((rows * columns - count) * 2 + abs(width / height - 1.28), columns, rows))
    if not options:
        raise ValueError('桌面空间不足，请减少并行进程数量')
    _, columns, rows = min(options)
    cell_w, cell_h = area.width() // columns, area.height() // rows
    width, height = min(640, cell_w - 8), min(500, cell_h - 8)
    return [QRect(area.x() + (i % columns) * cell_w + (cell_w - width) // 2,
                  area.y() + (i // columns) * cell_h + (cell_h - height) // 2, width, height)
            for i in range(count)]


class ParallelExportWindows(QObject):
    stop_requested = Signal()
    closed = Signal()
    animation_finished = Signal()
    save_log_requested = Signal()
    log_requested = Signal()

    def __init__(self, parent, count):
        super().__init__(parent)
        self.windows = [ExportWindow() for _ in range(count)]
        from app.export_island import ExportIsland
        self._island = ExportIsland(self, self.windows, lambda: self._overall_fraction)
        for window in self.windows:
            window._island = self._island
        self._closing = False
        self._done = False
        self._map_preview=None
        self._success_pending = False
        self._success_targets = []
        self._stopping = False
        self._phase = 'idle'
        self._targets = []
        self._settled = set()
        self._split_origin = QRect()
        self._overall_fraction = 0
        self._parallel_stage = False
        self._worker_info = [{} for _ in self.windows]
        self._worker_warnings = [set() for _ in self.windows]
        self._split_timer = QTimer(self)
        self._split_timer.setSingleShot(True)
        self._split_timer.timeout.connect(self._split)
        self._reveal_timers = []
        for index, window in enumerate(self.windows):
            window.set_accelerated()
            window.stop_requested.connect(self._stop)
            window.save_log_requested.connect(self.save_log_requested.emit)
            window.log_requested.connect(self.log_requested.emit)
            window.closed.connect(self.close)
            window.details_requested.connect(self.show_details)
            window.transition_finished.connect(lambda i=index: self._transition_finished(i))

    def begin(self, title, subtitle='', start_rect=None):
        screen = QGuiApplication.screenAt(start_rect.center()) if start_rect is not None else None
        screen = screen or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen else QRect(0, 0, 1600, 900)
        self._targets = tile_rects(area, len(self.windows))
        origin = QRect(0, 0, min(640, area.width() - 16), min(500, area.height() - 16))
        origin.moveCenter(start_rect.center() if start_rect is not None else area.center())
        origin.moveLeft(max(area.left() + 8, min(origin.left(), area.right() - origin.width() - 7)))
        origin.moveTop(max(area.top() + 8, min(origin.top(), area.bottom() - origin.height() - 7)))
        self._phase = 'mother'
        for index, window in enumerate(self.windows):
            window._defer_live_log = True
            window.begin(f'分块 {index + 1} · {title}' if index else f'主窗口 · {title}', subtitle, present=False)
            if index:
                window._phase = f'分块 {index + 1}：等待源数据准备完成'
                window.feed(f'[分块 {index + 1}/{len(self.windows)}] 等待调度，公共日志见窗口 1。')
            window.prepare_transition(self._targets[index].size())
        start = QRect(start_rect).intersected(area) if start_rect is not None else origin
        self.windows[0].show_transition(start if start.isValid() else origin, origin, INTRO_MS)

    def _transition_finished(self, index):
        if self._closing:
            return
        if self._phase == 'mother' and index == 0:
            self._phase = 'waiting'
            self._split_timer.start(SPLIT_HOLD_MS)
        elif self._phase == 'splitting':
            self._settled.add(index)
            if len(self._settled) == len(self.windows):
                self._phase = 'ready'
                for window in self.windows:
                    window._defer_live_log = False
                    window._snapshot_cache.clear()
                    window._transition_surface.pixmap = None
                self.animation_finished.emit()
                if self._success_pending:self._form_success()

    def _split(self):
        if self._closing:
            return
        self._phase = 'splitting'
        self._split_origin = QRect(self.windows[0].geometry())
        for index in range(len(self.windows)):
            if index == 0:
                self._reveal(index)
            else:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(lambda i=index: self._reveal(i))
                self._reveal_timers.append(timer)
                timer.start(index * SPLIT_STAGGER_MS)

    def _reveal(self, index):
        if not self._closing:
            self.windows[index].show_transition(self._split_origin, self._targets[index],
                                                SPLIT_MS, QEasingCurve.OutCubic)

    def feed(self, line):
        if self._map_preview is not None:self._map_preview.feed(line)
        prefix = '@ATLASMAP_PARALLEL '
        if line.startswith(prefix):
            try:
                data = json.loads(line[len(prefix):])
                index = int(data['worker'])
                if 0 <= index < len(self.windows):
                    window = self.windows[index]
                    window._title = str(data['stage'])
                    event = data.get('event', 'line')
                    if self._stopping and event!='line':
                        if data.get('text'):window.feed(data['text'])
                        return
                    info = self._worker_info[index]
                    if info.get('stage') != data['stage']:
                        info.clear()
                        info['stage'] = data['stage']
                    text = data.get('text','')
                    native = bool(re.match(r'^\[\d{4}\.\d{2}\.\d{2}',text))
                    noise = (native or bool(re.search(r'\]Log\w+:', text)) or 'Read blend:' in text
                             or text.startswith(('══', '──', 'manifest {', 'material_manifest {',
                                                     'FBX export starting', 'export finished')))
                    if event == 'line' and noise:
                        if 'warning:' in text.lower():
                            warning = re.sub(r'^\[.*?\]\[.*?\]', '', text)
                            if warning in self._worker_warnings[index]:return
                            self._worker_warnings[index].add(warning)
                        elif not any(token in text.lower() for token in
                                ('error:','exception:','critical error','traceback','失败')):
                            return
                    if event == 'assigned':
                        info.update(data.get('work', {}))
                        window._fraction = None
                    if event == 'process':
                        info['pid'] = data['pid']
                        window._phase=f'分块 {index+1}：进程 {data["pid"]} 已启动'
                    if event == 'queued':
                        window._phase_locked=True
                        window._fraction=None
                        window._phase=data.get('text','等待可用内存')
                    if event == 'progress':
                        window._phase_locked = True
                        done, total = int(data['done']), int(data['total'])
                        window.set_fraction(done / max(1, total))
                        window._phase = f"分块 {index + 1} · {data.get('unit','资源')} {done}/{total} · {data.get('current','')}"
                    if event == 'finished':
                        if data['code'] == 0:
                            window.set_fraction(1)
                            window._phase = f'分块 {index + 1} 已完成，等待其他任务'
                        else:
                            window._phase = f"分块 {index + 1} 退出，状态 {data['code']}"
                    assignment = ' / '.join(f'{label} {info[key]}' for key,label in
                        (('levels','源块'),('objects','对象'),('meshes','模型'),('materials','材质'),('textures','贴图')) if key in info)
                    window._subtitle = f"分块 {index + 1}/{len(self.windows)} · PID {info.get('pid','等待启动')} · {assignment}"
                    if data.get('text'):
                        window.feed(data['text'])
                    return
            except (ValueError, KeyError, TypeError):
                pass
        self.windows[0].feed('[公共] ' + line if line else '')

    def set_fraction(self, fraction):
        self._overall_fraction = fraction
        if not self._parallel_stage:
            self.windows[0].set_fraction(fraction)

    def set_stage(self, name, parallel=False):
        self._parallel_stage = parallel
        for index, window in enumerate(self.windows):
            window._phase_locked = True
            if parallel:
                window._fraction = None
                window._phase = f'分块 {index + 1}：正在分配独立资源'
            elif index:
                window._phase = f'分块 {index + 1}：等待公共步骤完成'
                window._subtitle = f'当前公共步骤：{name}；详细日志见窗口 1'
                window.feed(f'[分块 {index + 1}] 等待：{name}')
            else:
                window._title = '主窗口 · 调度与合并'
                window._phase = name
                window._subtitle = f'公共步骤 · 总进度 {self._overall_fraction:.0%}；各分块日志保留在对应窗口'

    def finish(self, code, *args, **kwargs):
        if self._map_preview is not None:self._map_preview.finish(code)
        self._done = True
        for window in self.windows:
            window.finish(code, *args, **kwargs)
        self._success_pending = code == 0 and not self._closing
        if self._success_pending and self._phase=='ready':self._form_success()

    def bind_preview(self,controller):
        self._map_preview=controller
        for window in self.windows:window.bind_preview(controller,feed=False)

    def _form_success(self):
        if self._closing or not self._success_pending:return
        self._success_pending=False
        self._phase='success'
        self._success_targets=[QRect(w.geometry()) for w in self.windows]
        for window in self.windows:
            artwork=success_artwork(window.size(),len(self.windows),window._elapsed,
                                    window.devicePixelRatioF())
            window._celebration=artwork
            window._transition_surface.pixmap=artwork
            window._defer_live_log=True
            window.surfaceRect=window.rect()
            window._surface.hide()
            window._transition_surface.setGeometry(window.rect())
            window._transition_surface.show()
            window._transition_surface.update()

    def show_details(self):
        if self._closing or self._phase!='success':return
        self._phase='ready'
        for window in self.windows:
            window._celebration=None
            window._snapshot_cache.clear()
            window._defer_live_log=False
            window._transition_surface.hide()
            window._surface.setGeometry(window.rect())
            window._surface.show()

    def _stop(self):
        if self._stopping or self._done:
            return
        self._stopping = True
        for window in self.windows:
            window.btn_stop.setEnabled(False)
            window.btn_stop.setText('正在终止…')
            window._phase_locked=True
            window._phase='正在终止：结束导出进程并取消排队分块…'
            window._surface.update()
        self.stop_requested.emit()

    def close(self):
        if self._closing:
            return
        self._closing = True
        self._phase = 'closed'
        self._success_pending=False
        self._split_timer.stop()
        for timer in self._reveal_timers:
            timer.stop()
        if not self._done:
            self._stop()
        for window in self.windows:
            window.close()
        self.closed.emit()
