"""Small license-gated check of quality/size UI; does not run a map export."""
from pathlib import Path
from types import SimpleNamespace
import json,sys


def run(output):
    from PySide6.QtCore import Qt,QEventLoop,QTimer
    from PySide6.QtWidgets import QApplication
    from fluentpy import widgets as W
    from app.ue_page import UePage
    from app.pages import MapPage
    from app.version import stamp
    from core import exporter,ue_pipeline,export_quality as Q
    from unittest.mock import patch
    app=QApplication.instance();app.setQuitOnLastWindowClosed(False)
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    saved=exporter.load_settings()
    saved.update(ue_map='CollectionRoom',ue_export_base='I:/AtlasMapExports',export_quality='standard',
                 advanced_mode=False,parallel_export=False,export_target='ue')
    host=SimpleNamespace(job=None,status=lambda *a:None,run_async=lambda fn,cb:cb(fn()))
    with patch.object(dfmap,'load_settings',side_effect=lambda:dict(saved)),patch.object(dfmap,'save_settings',side_effect=lambda d:saved.update(d)):
        page=UePage(host,host);host.ue_page=page
        page.setAttribute(Qt.WA_DontShowOnScreen);page.resize(1150,940);page.show()
        host.map_page=MapPage(host);host.map_page.setAttribute(Qt.WA_DontShowOnScreen)
        host.map_page.resize(1250,940);host.map_page.select('CollectionRoom')
        loop=QEventLoop();QTimer.singleShot(300,loop.quit);loop.exec()
        assert type(page.quality.combo) is W.ComboBox and not page.quality.card.isHidden()
        assert type(page.quality.scan_button) is W.Button
        limits=[];ranges=[]
        for preset in Q.QUALITIES:
            page.quality.combo.setCurrentIndex(page.quality.combo.findData(preset.key))
            assert host.map_page.quality.combo.currentData()==preset.key
            cmd=ue_pipeline.export_command(page._paths())
            limits.append(int(cmd[cmd.index('--max-tex')+1]))
            assert limits[-1]==preset.max_tex
            if page.quality._evidence:
                estimate=Q.forecast(page.quality._evidence,preset.key)
                ranges.append(dict(quality=preset.key,**estimate))
                assert '建议空闲空间' in page.quality.estimate.text()
                assert str(estimate['note']) in page.quality.basis.text()
        assert len(ranges)==5,'验证前请提供真实地图扫描缓存；不会假造显示数字'
        page.quality.combo.setCurrentIndex(page.quality.combo.findData('standard'))
        app.processEvents();page.grab().save(str(out/'quality-simple.png'))
        page.quality.combo.setCurrentIndex(page.quality.combo.findData('ultra'))
        app.processEvents();page.grab().save(str(out/'quality-ultra.png'))
        page.cb_target.setCurrentIndex(page.cb_target.findData('blender'))
        assert page._paths()['max_tex']=='4096' and 'Blender' in page.quality.estimate.text()
        app.processEvents();page.grab().save(str(out/'quality-blender.png'))
        host.map_page.quality.combo.setCurrentIndex(host.map_page.quality.combo.findData('draft'))
        assert page.quality.combo.currentData()=='draft'
        flags=host.map_page._flags();assert flags[flags.index('--max-tex')+1]=='512'
        host.map_page.show();app.processEvents();host.map_page.grab().save(str(out/'quality-library.png'))
        report=dict(version=stamp(),frozen=bool(getattr(sys,'frozen',False)),native_controls=True,
                    simple_mode_visible=True,limits=limits,blender_quality=True,raw_quality=True,
                    selection_synchronised=True,range_not_exact=True,ranges=ranges)
        (out/'export-quality-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        host.map_page.close();page.close();host.map_page.deleteLater();page.deleteLater();app.processEvents()
    print(json.dumps({k:v for k,v in report.items() if k!='ranges'},ensure_ascii=False),flush=True)
    return 0
