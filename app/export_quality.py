"""Native Fluent controls for quality and an asynchronous, non-blocking forecast."""
from PySide6.QtCore import QObject,QTimer,Qt
from PySide6.QtWidgets import QHBoxLayout,QLabel,QVBoxLayout
from app import fluent_api as F
from core import exporter,export_quality as Q


class QualityPanel(QObject):
    def __init__(self,host,scan,parent=None):
        super().__init__(parent)
        self.host=host;self._context=None;self._key=None;self._generation=0;self._evidence=None
        self._disposed=False;self._loading=False
        self.destroyed.connect(self._dispose)
        self.card=F.SimpleCardWidget(parent)
        layout=QVBoxLayout(self.card);layout.setContentsMargins(16,14,16,14)
        row=QHBoxLayout();row.addWidget(QLabel('导出质量',self.card))
        self.combo=F.ComboBox()
        for preset in Q.QUALITIES:self.combo.addItem(preset.title,preset.key)
        selected=Q.quality(exporter.load_settings().get('export_quality')).key
        self.combo.setCurrentIndex(self.combo.findData(selected));row.addWidget(self.combo,1)
        self.scan_button=F.PushButton('更新估算');self.scan_button.clicked.connect(scan);row.addWidget(self.scan_button)
        layout.addLayout(row)
        self.description=QLabel(self.card);self.description.setWordWrap(True);layout.addWidget(self.description)
        self.estimate=QLabel('预计大小：选择地图并扫描后显示',self.card)
        self.estimate.setWordWrap(True);self.estimate.setTextFormat(Qt.PlainText);layout.addWidget(self.estimate)
        self.basis=QLabel(self.card);self.basis.setWordWrap(True);layout.addWidget(self.basis)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(180)
        self.timer.timeout.connect(self._load)
        self.combo.currentIndexChanged.connect(self._render)

    def set_context(self,map_name,root='',files=0,target='ue',parallel=1,project=''):
        context=dict(map=map_name,root=root,files=files,target=target,parallel=parallel,project=project)
        key=(map_name,root,files)
        self._context=context
        if key!=self._key:
            self._key=key;self._generation+=1;self._evidence=None;self._loading=False;self.timer.start()
        self._render()

    def reload(self):
        self._generation+=1;self._evidence=None;self.timer.start();self._render()

    def _dispose(self,*_):
        self._disposed=True

    def _load(self):
        if not self._context or not self._context['map']:return
        current=dict(self._context);generation=self._generation
        self._loading=True;self._render()
        def loaded(result):
            if self._disposed or generation!=self._generation:return
            self._loading=False
            self._evidence=None if isinstance(result,Exception) else result
            self._render()
        work=lambda:Q.evidence(current['map'],current['root'],current['files'])
        if hasattr(self.host,'run_async'):self.host.run_async(work,loaded)
        else:
            try:result=work()
            except (OSError,ValueError):result=None
            loaded(result)

    def _render(self,*_):
        preset=Q.quality(self.combo.currentData())
        self.description.setText(preset.note+' 质量档位只调整贴图分辨率，不改变所选地图内容。')
        context=self._context or {}
        estimate=Q.forecast(self._evidence,preset.key,context.get('target','ue'),context.get('parallel',1))
        if estimate is None:
            self.estimate.setText('预计大小：正在读取统计…' if self.timer.isActive() or self._loading else '预计大小：暂无本图统计，点击“更新估算”扫描地图')
            self.basis.setText('估算仅分析资源信息，不会启动地图导出。')
            return
        label={'ue':'UE 工程新增资源','blender':'Blender 工程','raw':'源导出文件'}[context.get('target','ue')]
        suffix=' 或更多' if estimate['original_unbounded'] else ''
        self.estimate.setText(f"预计 {label}：约 {Q.size_text(estimate['low'])} – {Q.size_text(estimate['high'])}{suffix}\n"
                             f"导出过程建议空闲空间：{Q.size_text(estimate['free_recommended'])} 以上（含临时文件）")
        availability=[]
        from core.export_storage import disk_free
        for name,path in (('导出盘',context.get('root')),('工程盘',context.get('project') if context.get('target')=='ue' else None)):
            if path and '<' not in path:
                try:availability.append(f'{name}可用 {Q.size_text(disk_free(path))}')
                except (OSError,ValueError):pass
        self.basis.setText(('地图库按整图估算，只选部分层时实际通常更小。' if context.get('target')=='raw' else '')+
                           estimate['note']+' 这是参考范围，不是实际大小或保证上限。'+(' 原始贴图分辨率未解析时可能更大。' if estimate['original_unbounded'] else '')+
                           ('\n'+'；'.join(availability) if availability else ''))
