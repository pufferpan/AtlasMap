"""Regenerate tutorial screenshots from real widgets; never run export or write user settings."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget
from app.__main__ import _apply_theme
from app.pages import MapPage
from app.ue_page import UePage
from app.export_window import ExportWindow
from app import fluent_api as F
from core import exporter

app=QApplication.instance() or QApplication([])
_apply_theme(app)
for name in ('msyh.ttc','msyhbd.ttc','segoeui.ttf'):
    font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/name
    if font.exists(): QFontDatabase.addApplicationFont(str(font))
app.setFont(QFont('Microsoft YaHei',10))
destination=Path(__file__).resolve().parents[1]/'assets'
settings=dict(paks='D:/AtlasMap-build/Game/DeltaForce/Content/Paks',outdir='D:/AtlasMaps/Export',
              ue_engine='C:/Program Files/Epic Games/UE_5.4/Engine/Binaries/Win64/UnrealEditor.exe',
              ue_project='D:/AtlasMaps/MapProject/MapProject.uproject',
              blender='C:/Program Files/Blender Foundation/Blender 4.2/blender.exe',ue_export_base='D:/AtlasMaps/Export',
              ue_map='CollectionRoom',parallel_export=False,parallel_processes=2)
class Host(QWidget):
    def status(self,*args): pass

def save(widget,name):
    widget.setStyleSheet(widget.styleSheet()+';background-color:#161C27;')
    widget.resize(1160,840)
    widget.show()
    app.processEvents()
    assert widget.grab().save(str(destination/name))

with patch.object(exporter,'load_settings',side_effect=lambda:dict(settings)), \
     patch.object(exporter,'save_settings'),patch.object(exporter,'write_exporter_config'), \
     patch('app.ue_page._detect_engine',return_value=settings['ue_engine']), \
     patch('app.ue_page._detect_blender',return_value=settings['blender']):
    host=Host()
    with patch.object(exporter,'load_presets',return_value=[]):
        host.map_page=MapPage(host)
    save(host.map_page,'tutorial_maps.png')
    host.map_page.hide()
    ue=UePage(host,host)
    save(ue,'tutorial_ue.png')
    ue.advanced_switch.setChecked(True)
    ue.chk_parallel.blockSignals(True)
    ue.chk_parallel.setChecked(True)
    ue.chk_parallel.blockSignals(False)
    ue.sp_parallel.setEnabled(True)
    F.apply_fluent_theme(True,'#D13438')
    save(ue,'tutorial_performance.png')
    performance_card=ue.chk_parallel.parentWidget()
    assert performance_card.grab().save(str(destination/'tutorial_performance.png'))
    F.apply_fluent_theme(True,'#2B579A')
    ue.hide()
    progress=ExportWindow()
    progress.begin('导出进度 · 教程界面示例',present=False)
    progress.resize(720,560)
    progress.surfaceRect=QRect(0,0,720,560)
    progress.show()
    progress.feed('教程示例：这里显示当前分块的实际步骤和日志。')
    progress.feed('点击「隐藏」收起为顶部进度条，点击进度条恢复窗口。')
    progress.feed('点击「终止导出」停止任务；失败或取消后可选择清理残留。')
    progress.set_fraction(.35)
    progress._flush_log(all_lines=True)
    progress._on_tick()
    app.processEvents()
    assert progress._surface.grab().save(str(destination/'tutorial_progress.png'))
    progress._closing=True
    progress.close()
    ue.close()
    host.map_page.close()
print('Captured four tutorial screenshots without exporting or saving settings.')
