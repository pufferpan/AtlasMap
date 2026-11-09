"""One shared, nonmodal map preview for all export progress windows."""
import json
from pathlib import Path
import threading
import zipfile
from PySide6.QtCore import QObject,QTimer,Qt,Signal
from PySide6.QtWidgets import QLabel,QHBoxLayout,QWidget,QVBoxLayout
from app import fluent_api as F
from app.map_viewport import viewport,SoftwareViewport
from core.map_preview import read_chunk
from scripts.official.map_paths import io_path


class MapPreview(QObject):
    loaded=Signal(object)
    def __init__(self,preview,parent=None):
        super().__init__(parent)
        self.preview=preview;self.data={};self.states={};self.stamps={};self.busy=False
        self.closed=False;self.auto_open=True;self.dialog=None;self.canvas=None;self.stage='正在准备地图'
        self.loaded.connect(self._loaded,Qt.QueuedConnection)
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.poll);self.timer.start()

    def show(self):
        if self.closed:return
        if self.dialog is None:
            dialog=F.Dialog(self.preview['name']+' · 地图预览','左键拖动旋转 · 滚轮缩放 · 右键拖动平移 · 双击回到全图')
            dialog.setModal(False);dialog.setWindowModality(Qt.NonModal)
            dialog.setWindowFlag(Qt.WindowStaysOnTopHint,True)
            dialog.setAttribute(Qt.WA_QuitOnClose,False)
            dialog._shadow.setEnabled(False)
            dialog.setYesButtonText('关闭预览');dialog.cancel_button.hide()
            controls=QWidget(dialog);row=QHBoxLayout(controls);row.setContentsMargins(0,0,0,0)
            select=F.ComboBox();select.addItem('显示全图',-1)
            for i in range(self.preview['count']):select.addItem(f'仅显示分块 {i+1}',i)
            row.addWidget(select)
            reset=F.PushButton('回到全图');row.addWidget(reset);row.addStretch(1)
            dialog.add_content_widget(controls)
            container=QWidget(dialog);self.canvas_layout=QVBoxLayout(container);self.canvas_layout.setContentsMargins(0,0,0,0)
            self.canvas=viewport(container);self.canvas_layout.addWidget(self.canvas)
            if hasattr(self.canvas,'failed'):self.canvas.failed.connect(self._software)
            dialog.add_content_widget(container)
            self.label=QLabel('地图数据准备中…',dialog);self.label.setWordWrap(True);dialog.add_content_widget(self.label)
            legend=QLabel('灰蓝：等待处理　橙色：正在处理　绿色：当前步骤完成　红色：失败',dialog)
            dialog.add_content_widget(legend)
            select.currentIndexChanged.connect(lambda _:self.canvas.select_chunk(select.currentData()))
            reset.clicked.connect(lambda:(select.setCurrentIndex(0),self.canvas.fit()))
            self.dialog=dialog;self.selector=select
            for i,(vertices,meta) in self.data.items():self.canvas.set_chunk(i,vertices)
            self.canvas.set_states(self.states);self.canvas.fit()
        self.dialog._prepare_geometry();self.dialog.show();self.dialog.raise_()
        self._status();self.auto_open=False

    def _software(self,error):
        previous=self.canvas;self.canvas=SoftwareViewport(previous.parentWidget())
        self.canvas_layout.replaceWidget(previous,self.canvas);previous.hide();previous.deleteLater()
        for i,(vertices,meta) in self.data.items():self.canvas.set_chunk(i,vertices)
        self.canvas.set_states(self.states)

    def hide(self):
        if self.dialog is not None:self.dialog.hide()

    def close(self):
        self.closed=True;self.timer.stop()
        if self.dialog is not None:self.dialog.close();self.dialog.deleteLater();self.dialog=None

    def poll(self):
        if self.busy or self.closed:return
        pending=[]
        for i in range(self.preview['count']):
            path=Path(self.preview['folder'])/f'worker_{i}.npz'
            try:stamp=io_path(path).stat().st_mtime_ns
            except OSError:continue
            if self.stamps.get(i)!=stamp:pending.append((i,path,stamp))
        if not pending:return
        self.busy=True
        def read():
            result=[]
            for i,path,stamp in pending:
                try:result.append((i,stamp,read_chunk(path,self.preview['run_id'],i)))
                except (OSError,ValueError,KeyError,EOFError,zipfile.BadZipFile):pass
            try:self.loaded.emit(result)
            except RuntimeError:pass
        threading.Thread(target=read,daemon=True).start()

    def _loaded(self,result):
        self.busy=False
        if self.closed:return
        first=not self.data
        for i,stamp,data in result:
            self.stamps[i]=stamp;self.data[i]=data
            if self.canvas is not None:self.canvas.set_chunk(i,data[0])
        if first and self.data and self.auto_open:self.show()
        self._status()

    def _status(self):
        if self.dialog is not None:
            self.label.setText(f'已显示 {len(self.data)}/{self.preview["count"]} 个分块 · {self.stage}')
            self.canvas.set_states(self.states)

    def feed(self,line):
        if line.startswith('@ATLASMAP_PARALLEL '):
            try:
                event=json.loads(line.split(' ',1)[1]);index=int(event['worker'])
                if index not in range(self.preview['count']):return
                kind=event.get('event')
                if kind=='queued':self.states[index]='queued'
                elif kind in ('process','progress','assigned'):self.states[index]='running'
                elif kind=='finished':self.states[index]='finished' if event['code']==0 else 'failed'
                self.stage=event.get('stage',self.stage)
            except (ValueError,KeyError,TypeError):return
        elif '步骤' in line or line.startswith('['):
            self.stage=line[:120]
            if self.preview['count']==1:self.states[0]='running'
        self._status()

    def finish(self,code):
        if code!=0:self.auto_open=False
        self.stage='导出完成' if code==0 else '导出已取消' if code==-2 else '导出失败，详情见完整日志'
        if code==0:self.states={i:'finished' for i in range(self.preview['count'])}
        elif code==-2:self.states={i:'stopped' for i in range(self.preview['count'])}
        self._status();self.poll()
