"""入口：开屏动画（含 HyperOS 光斑 + maplogo）→ 主窗口。

环境变量（调试用）：
  ATLASMAP_NOSPLASH=1   跳过开屏，直接开主窗口
  ATLASMAP_DEBUG=1      出异常时打印完整 traceback
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from typing import Optional

from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication,QLabel

from app import fluent_api as F
from app import ui_scale as _ui
from core import exporter

MIN_SPLASH_MS = 900          # 开屏至少露脸这么久，别一闪而过
EXPAND_MS = 760


def _asset(name: str) -> str:
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    if getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"):
        base = os.path.join(getattr(sys, "_MEIPASS", base), "assets")
    return os.path.join(base, name)


def _apply_theme(app: QApplication) -> None:
    try:
        F.apply_fluent_theme(True)
    except Exception:                                            # noqa: BLE001
        pass
    try:
        F.apply_dark_palette(app, True)
    except Exception:                                            # noqa: BLE001
        pass
    try:
        app.setWindowIcon(QIcon(_asset("maplogo.png")))
    except Exception:                                            # noqa: BLE001
        pass


def _splash_icon() -> Optional[QPixmap]:
    path = _asset("maplogo.png")
    if os.path.isfile(path):
        pix = QPixmap(path)
        if not pix.isNull():
            return pix
    return None


def run(argv: Optional[list] = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(argv)
    app.setApplicationName(exporter.APP_NAME)
    app.setOrganizationName(exporter.APP_NAME)
    app.setApplicationDisplayName("AtlasMap · 地图导出器")
    _apply_theme(app)

    # Enforce activation before constructing the main window, including
    # no-splash and packaged self-check launches.
    from app.activation import require_activation
    if not require_activation():
        return 0

    if len(argv)==3 and argv[1]=='--verify-failure-ui':
        from tools.verify_failure_ui import run as verify_failure_ui
        return verify_failure_ui(argv[2])
    if len(argv)==3 and argv[1]=='--verify-export-quality':
        from tools.verify_export_quality import run as verify_export_quality
        return verify_export_quality(argv[2])

    from app.main_window import MapViewerWindow
    from app.splash import SplashWindow

    # A frozen-build check must construct the real Qt window, rather than
    # treating a live bootloader error dialog as a successful launch.
    check_output = os.environ.get("ATLASMAP_SELF_TEST_OUTPUT", "")
    if check_output:
        import json
        from app.version import stamp
        win = MapViewerWindow()
        app.processEvents()
        paths = win.ue_page._paths()
        from app.export_window import ExportWindow
        from PySide6.QtWidgets import QPlainTextEdit
        export = ExportWindow()
        log_wrap = export.log_view.text_edit.lineWrapMode() == QPlainTextEdit.WidgetWidth
        export.setAttribute(Qt.WA_DontShowOnScreen)
        large = app.primaryScreen().availableGeometry().adjusted(12, 12, -12, -12)
        export.begin('正在导出CollectionRoom', start_rect=large)
        original_surface = QRect(export.surfaceRect)
        original_native = QRect(export.geometry())
        loop = QEventLoop()
        QTimer.singleShot(300, loop.quit)
        loop.exec()
        shrinking = (export._transitioning and export.surfaceRect.width() < original_surface.width()
                     and export.geometry() == original_native)
        export.visual_surface().grab().save(os.path.splitext(check_output)[0]+'-export-shrinking.png')
        QTimer.singleShot(600, loop.quit)
        loop.exec()
        compact = not export._transitioning and export.surfaceRect == export.rect()
        debug_hidden = export.btn_debug.isHidden()
        export.reveal_debug_button()
        export.btn_debug.click()
        QTimer.singleShot(1100, loop.quit)
        loop.exec()
        usage = export._usage_snapshot
        cpu_memory = (usage.get('cpu_percent') is not None and usage.get('memory_total',0) > 0
                      and export._usage_timer.isActive() and export.usage_label.isVisible())
        export.feed('CollectionRoom · 实时日志与资源占用检查')
        export._on_tick()
        export._surface.grab().save(os.path.splitext(check_output)[0]+'-export-debug.png')
        result = {"complete": True, "version": stamp(), "map": paths["map"],
                  "level": paths["dest"].rstrip("/") + "/LV_Map",
                  "ue_logo_valid": not win.ue_page.btn_auto.icon().isNull(),
                  "log_wrap": log_wrap, "ue_workers": win.ue_page.sp_workers.value(),
                  "export_shrink_animation": shrinking, "export_compact": compact,
                  "export_debug_hidden": debug_hidden, "export_cpu_memory": cpu_memory,
                  "export_usage_sample": usage}
        runtime = exporter.runtime_root()
        result['runtime_root'] = runtime
        result['runtime_scripts_complete'] = all(os.path.isfile(os.path.join(runtime, relative)) for relative in (
            'scripts/official/ue_run_headless.py', 'scripts/official/ue_iceland_bridge.py',
            'scripts/official/map_geometry.py', 'scripts/official/ue_sky_capture.py',
            'scripts/official/map_image_header.py',
            'scripts/official/blender_save_project.py','scripts/official/blender_assemble_project.py',
            'scripts/official/blender_live_preview.py','scripts/official/map_preview_geometry.py',
            'scripts/tools/scene-state/scene-state.exe', 'scripts/tools/scene-state/scene-state.dll'))
        bundled = os.path.join(runtime, 'runtime', 'map-export.exe')
        result['runtime_exporter_valid'] = exporter.exporter_is_required(bundled)
        result['runtime_exporter_selected'] = os.path.normcase(exporter.find_exe() or '') == os.path.normcase(bundled)
        result['game_lighting_default']=paths['render_profile']=='game'
        from fluentpy import widgets as fluent_widgets
        result['project_manager_native'] = (type(win.projects_page.table) is fluent_widgets.TableWidget
            and type(win.projects_page.search) is fluent_widgets.LineEdit
            and type(win.ue_page.advanced_switch) is fluent_widgets.ToggleSwitch)
        from send2trash import send2trash
        import psutil
        result['project_file_tools'] = send2trash.__module__ == 'send2trash.win.modern' and psutil.pid_exists(os.getpid())
        prior_mode = win.ue_page.advanced_switch.isChecked()
        win.ue_page.advanced_switch.setChecked(False)
        simple_ok = win.ue_page.ed_engine.isHidden() and not win.ue_page.ed_root.isHidden()
        win.ue_page.advanced_switch.setChecked(True)
        result['simple_mode_toggle'] = simple_ok and not win.ue_page.ed_engine.isHidden()
        win.ue_page.advanced_switch.setChecked(prior_mode)
        result['fluent_native_controls']=(type(win.ue_page.ed_root) is fluent_widgets.LineEdit
            and type(win.ue_page.chk_parallel) is fluent_widgets.CheckBox
            and type(win.ue_page.sp_workers) is fluent_widgets.SpinBox
            and type(export.log_view) is fluent_widgets.CodeEdit
            and all(type(edit) is fluent_widgets.CodeEdit for _,_,edit in win.ue_page._steps)
            and type(export._surface) is fluent_widgets.CardWidget
            and type(export.progress_bar) is fluent_widgets.ProgressBar
            and type(win.docs_page.list) is fluent_widgets.TableWidget)

        from app.wizard import WizardWindow, PRIMARY
        wizard = WizardWindow()
        wizard.setAttribute(Qt.WA_DontShowOnScreen)
        wizard.start()
        loop = QEventLoop()
        QTimer.singleShot(3800, loop.quit)
        loop.exec()
        result.update(wizard_rows=wizard.bg.row_count(), wizard_intro_finished=not wizard._intro,
                      wizard_color=PRIMARY, lighting_mode=paths['lighting_mode'],
                      render_button=win.ue_page.btn_render.text(), map_exe=exporter.find_exe(),
                      manual_lighting_mode='ATLASMAP_LIGHTING_MODE' in win.ue_page._cmd_finish(),
                      render_views=[win.ue_page.cb_render_view.itemData(i) for i in range(win.ue_page.cb_render_view.count())])
        wizard.grab().save(os.path.splitext(check_output)[0]+'-wizard.png')
        from app.wizard_tutorial import TUTORIALS
        tutorial_ok=[]
        for index,tutorial in enumerate(TUTORIALS,2):
            wizard._show_step(index)
            loop=QEventLoop()
            QTimer.singleShot(780,loop.quit)
            loop.exec()
            tutorial_ok.append(not wizard.tutorial._pixmap.isNull()
                and wizard.tutorial.isVisible()
                and wizard.tutorial._caption==tutorial['caption']
                and wizard.tutorial.x()>wizard.panel.geometry().right()
                and wizard.tutorial.geometry().right()<wizard.width())
            wizard.grab().save(os.path.splitext(check_output)[0]+f'-tutorial-{index-1}.png')
            wizard._on_next()
            wizard.back_btn.click()
            tutorial_ok[-1]=tutorial_ok[-1] and wizard._step==index
        result['wizard_tutorial_pages']=len(TUTORIALS)
        result['wizard_tutorial_screenshots']=all(tutorial_ok)
        wizard._closing = True
        wizard.close()
        splash=SplashWindow('AtlasMap')
        splash.setAttribute(Qt.WA_DontShowOnScreen)
        splash.center_on_screen()
        splash.show()
        loop=QEventLoop()
        QTimer.singleShot(500,loop.quit)
        loop.exec()
        first=splash._card.grab().toImage()
        first.save(os.path.splitext(check_output)[0]+'-splash-0.png')
        QTimer.singleShot(650,loop.quit)
        loop.exec()
        second=splash._card.grab().toImage()
        second.save(os.path.splitext(check_output)[0]+'-splash-1.png')
        points=[(first.width()*x//10,first.height()*y//10) for x,y in ((1,6),(2,8),(8,2),(9,7))]
        colors=[first.pixelColor(x,y).rgb() for x,y in points]
        result['splash_gradient']=len(set(colors))>2
        result['splash_flow']=any(first.pixelColor(x,y)!=second.pixelColor(x,y) for x,y in points)
        result['state_helper']=os.path.isfile(os.path.join(os.path.dirname(paths['scripts']),'tools','scene-state','scene-state.exe'))
        result['exporter_pinned']=exporter.exporter_is_required(result['map_exe'])
        from app.parallel_export_windows import ParallelExportWindows
        group = ParallelExportWindows(win,max(2,min(8,int(os.environ.get('ATLASMAP_SELF_TEST_WORKERS','2')))))
        result['parallel_window_count']=len(group.windows)
        for window in group.windows:
            window.setAttribute(Qt.WA_DontShowOnScreen)
        win.set_parallel_theme(True)
        win.switchTo(win.ue_page)
        app.processEvents()
        win.grab().save(os.path.splitext(check_output)[0]+'-parallel-theme.png')
        group.begin('CollectionRoom · 并行导出', start_rect=large)
        result['parallel_single_origin'] = (group.windows[0].isVisible()
                                            and all(w.isHidden() for w in group.windows[1:]))
        from app.parallel_export_windows import INTRO_MS, SPLIT_MS, SPLIT_HOLD_MS, SPLIT_STAGGER_MS
        def capture_split():
            if result.get('parallel_split_motion'):return
            result['parallel_split_motion'] = (all(w.isVisible() and w._transitioning for w in group.windows)
                and all(w.surfaceRect.translated(w.geometry().topLeft()) != group._split_origin
                        for w in group.windows))
            if not result['parallel_split_motion']:return
            for i, window in enumerate(group.windows):
                window.visual_surface().grab().save(os.path.splitext(check_output)[0]+f'-splitting-{i+1}.png')
        split_capture=QTimer();split_capture.setInterval(20);split_capture.timeout.connect(capture_split);split_capture.start()
        group.animation_finished.connect(loop.quit)
        split_timeout = QTimer()
        split_timeout.setSingleShot(True)
        split_timeout.timeout.connect(loop.quit)
        split_timeout.start(4000)
        loop.exec()
        split_timeout.stop()
        split_capture.stop()
        group.animation_finished.disconnect(loop.quit)
        result['parallel_split_finished'] = group._phase == 'ready'
        rectangles = [window.geometry() for window in group.windows]
        result['parallel_tiling'] = (all(app.primaryScreen().availableGeometry().contains(r) for r in rectangles)
                                     and all(not a.intersects(b) for i,a in enumerate(rectangles) for b in rectangles[i+1:]))
        group.feed('@ATLASMAP_PARALLEL '+json.dumps({'worker':1,'stage':'UE 2/2','text':'WORKER_TWO_ONLY'}))
        for index, window in enumerate(group.windows):
            window.reveal_debug_button()
            window.btn_debug.click()
            window._flush_log(True)
            window.grab().save(os.path.splitext(check_output)[0]+f'-parallel-{index+1}.png')
        result['parallel_log_routing'] = ('WORKER_TWO_ONLY' not in group.windows[0].log_view.toPlainText()
                                          and 'WORKER_TWO_ONLY' in group.windows[1].log_view.toPlainText())
        group.set_stage('独立分块进度检查',parallel=True)
        for index,(done,total) in enumerate(((8,32),(10,17))):
            group.feed('@ATLASMAP_PARALLEL '+json.dumps({'worker':index,'stage':f'Blender {index+1}/2',
                'event':'progress','done':done,'total':total,'unit':'模型','current':f'SM_WORKER_{index}','text':f'SM_WORKER_{index}'}))
        group.feed('COORDINATOR_LOG_ONLY')
        for window in group.windows:window._flush_log(True)
        result['parallel_independent_progress'] = (abs(group.windows[0]._fraction-8/32)<1e-6
                                                    and abs(group.windows[1]._fraction-10/17)<1e-6)
        result['parallel_common_log_not_duplicated'] = ('COORDINATOR_LOG_ONLY' in group.windows[0].log_view.toPlainText()
                                                       and 'COORDINATOR_LOG_ONLY' not in group.windows[1].log_view.toPlainText())
        result['parallel_red_theme'] = win._parallel_theme and all(w._accelerated for w in group.windows)
        result['parallel_default_off'] = paths['parallel_export'] == '0'
        original_geometries=[w.geometry() for w in group.windows]
        group.set_fraction(.68)
        group.windows[0].btn_hide.click()
        QTimer.singleShot(160, loop.quit); loop.exec()
        result['island_blur_transition']=bool(group._island.flights and
            0 < group._island.flights[0].image.blur <= 1)
        if group._island.flights:
            group._island.flights[0].image.grab().save(os.path.splitext(check_output)[0]+'-island-blur.png')
        QTimer.singleShot(500, loop.quit); loop.exec()
        result['island_collapsed']=(group._island.state=='collapsed'
            and all(w.isHidden() for w in group.windows) and group._island.pill.isVisible()
            and group._island.fraction()==.68)
        group._island.pill.grab().save(os.path.splitext(check_output)[0]+'-island.png')
        group.finish(0)
        QTimer.singleShot(80, loop.quit); loop.exec()
        result['island_success_hidden']=(all(w.isHidden() for w in group.windows)
            and group._island.pill.stop.isHidden())
        group._island.pill.grab().save(os.path.splitext(check_output)[0]+'-island-success.png')
        group._island.restore()
        QTimer.singleShot(600, loop.quit); loop.exec()
        result['island_restored']=(group._island.state=='expanded'
            and all(w.isVisible() and w.geometry()==r for w,r in zip(group.windows,original_geometries)))
        result['success_preserves_geometry']=all(w.geometry()==r for w,r in zip(group.windows,original_geometries))
        from app.export_celebration import SUCCESS_MS
        success_loop=QEventLoop()
        QTimer.singleShot(SUCCESS_MS+120,success_loop.quit)
        success_loop.exec()
        result['parallel_green_success']=(group._phase=='success' and all(
            w._celebration is not None and w.geometry()==r and w.visual_surface().geometry()==w.rect()
            for w,r in zip(group.windows,group._success_targets)))
        for i,w in enumerate(group.windows):
            w.visual_surface().grab().save(os.path.splitext(check_output)[0]+f'-success-{i+1}.png')
        group.show_details()
        details_loop=QEventLoop();QTimer.singleShot(500,details_loop.quit);details_loop.exec()
        result['parallel_success_logs_accessible']=all(w._celebration is None and w._surface.isVisible() for w in group.windows)
        from app.performance_effect import show_performance_effect
        win.show()
        app.processEvents()
        effect=show_performance_effect(win,2)
        app.processEvents()
        effect._frame(.5)
        effect.grab().save(os.path.splitext(check_output)[0]+'-performance-effect.png')
        result['performance_effect_visible']=effect.isVisible() and effect.isWindow() and effect.pos()==effect.anchor
        effect.close()
        group.close()
        # Exercise the actual queued completion and choice callbacks without
        # launching exporters or touching the user's map/project files.
        import tempfile
        from pathlib import Path
        from core.export_residue import ExportResidue
        from core.ue_pipeline import Step
        def wait_for(check):
            pending=QEventLoop();poll=QTimer();poll.setInterval(20)
            poll.timeout.connect(lambda: pending.quit() if check() else None)
            poll.start();QTimer.singleShot(5000,pending.quit);pending.exec();poll.stop()
            return bool(check())
        with tempfile.TemporaryDirectory(prefix='atlasmap-cleanup-ui-') as test_folder:
            test_root=Path(test_folder)
            old=test_root/'existing.blend';old.write_text('existing data')
            keep_file=test_root/'keep.fbx'
            def fail_job(pipe):
                keep_file.write_text('partial export')
                raise ValueError('Cleanup UI validation')
            win.run_pipeline('残留保留检查',[Step('模拟失败',[],action=fail_job)],
                             residue=ExportResidue([test_root]))
            shown=wait_for(lambda: getattr(win,'_cleanup_dialog',None) is not None)
            result['cleanup_failure_question']=shown and any('失败' in label.text() for label in win._cleanup_dialog.findChildren(QLabel))
            if shown:
                win._cleanup_dialog.grab().save(os.path.splitext(check_output)[0]+'-cleanup-question.png')
                win._cleanup_dialog.cancel_button.click()
            result['cleanup_keep_files']=keep_file.exists() and not win._cleanup_pending
            wait_for(lambda: not win.job.running)
            remove_file=test_root/'delete.fbx';log_file=test_root/'process.log'
            def cancel_job(pipe):
                remove_file.write_text('partial export');log_file.write_text('diagnostics')
                pipe.stop()
            win.run_pipeline('残留删除检查',[Step('模拟取消',[],action=cancel_job)],
                             residue=ExportResidue([test_root]))
            shown=wait_for(lambda: getattr(win,'_cleanup_dialog',None) is not None)
            result['cleanup_cancel_question']=shown and any('取消' in label.text() for label in win._cleanup_dialog.findChildren(QLabel))
            if shown:win._cleanup_dialog.delete_residue_button.click()
            finished=wait_for(lambda: not win._cleanup_pending)
            result['cleanup_delete_files']=(finished and not remove_file.exists()
                and old.exists() and keep_file.exists() and log_file.exists())
            wait_for(lambda: not win.job.running)
            win.run_pipeline('成功无清理提示',[Step('模拟成功',[],action=lambda pipe: None)],
                             residue=ExportResidue([test_root]))
            wait_for(lambda: not win.job.running)
            QTimer.singleShot(150,loop.quit);loop.exec()
            result['cleanup_success_quiet']=getattr(win,'_cleanup_dialog',None) is None
        # The exported file must include output discarded by both GUI limits,
        # and a button on any parallel window must save the same whole task.
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(prefix='atlasmap-full-log-ui-') as log_folder:
            def many_lines(pipe):
                pipe._emit('JSON converters: FULL_LOG_FIRST_UNFILTERED')
                for index in range(25050):pipe._emit(f'FULL_OUTPUT_{index:05d}')
                for worker in (0,1):
                    pipe._emit('@ATLASMAP_PARALLEL '+json.dumps(dict(worker=worker,stage='日志检查',event='line',text=f'FULL_WORKER_{worker}')))
                pipe._emit('FULL_LOG_LAST')
            win.run_pipeline('完整日志界面检查',[Step('25050 行输出',[],action=many_lines)])
            ready=wait_for(lambda:not win.job.running and win._task_log.finished)
            target=Path(log_folder)/'full.txt'
            with patch('app.main_window.QFileDialog.getSaveFileName',return_value=(str(target),'文本日志 (*.txt)')):
                win.job_page.save_log_btn.click()
            saved=wait_for(target.exists)
            text=target.read_text(encoding='utf-8-sig') if saved else ''
            result['full_log_untruncated']=(ready and saved and text.count('FULL_OUTPUT_')==25050
                and 'FULL_LOG_FIRST_UNFILTERED' in text and 'FULL_LOG_LAST' in text and '退出码 0' in text)
            result['full_log_all_workers']=all(f'FULL_WORKER_{worker}' in text for worker in (0,1))
            log_group=win.show_export_overlay('完整日志按钮检查',parallel_count=2)
            second=Path(log_folder)/'from-worker.txt'
            with patch('app.main_window.QFileDialog.getSaveFileName',return_value=(str(second),'文本日志 (*.txt)')):
                log_group.windows[-1].btn_save_log.click()
            result['full_log_worker_button']=(wait_for(second.exists) and second.read_bytes()==target.read_bytes())
            log_group.close()
        # Check the actual GPU surface and its native controls in the packaged
        # application, including the default nonmodal export-preview lifecycle.
        import numpy as np
        from app.map_preview import MapPreview
        from app.map_viewport import GLViewport
        from core.map_preview import session,read_chunk
        from PySide6.QtTest import QTest
        from PySide6.QtGui import QWheelEvent
        source=os.environ.get('ATLASMAP_SELF_TEST_PREVIEW','')
        if source:
            preview_info=json.loads(Path(source).read_text(encoding='utf-8'))['preview']
            preview_data={i:read_chunk(Path(preview_info['folder'])/f'worker_{i}.npz',preview_info['run_id'],i) for i in range(preview_info['count'])}
        else:
            preview_info=session(str(Path(check_output).parent),'预览检查',2)
            vertices=np.array([[0,0,0,0,0,1,.6,.7,.8],[4,0,0,0,0,1,.6,.7,.8],[0,4,1,0,0,1,.6,.7,.8]],np.float32)
            preview_data={0:(vertices,{})}
        preview=MapPreview(preview_info);preview.data=preview_data;preview.states={i:'running' for i in preview_data}
        preview.show();QTimer.singleShot(600,loop.quit);loop.exec()
        canvas=preview.canvas
        result['preview_gpu_active']=isinstance(canvas,GLViewport)
        result['preview_nonmodal']=not preview.dialog.isModal()
        result['preview_native_controls']=type(preview.dialog) is fluent_widgets.FramelessDialog and type(preview.selector) is fluent_widgets.ComboBox
        preview.dialog.grab().save(os.path.splitext(check_output)[0]+'-map-preview.png')
        before=canvas.yaw
        QTest.mousePress(canvas,Qt.LeftButton,pos=QPoint(180,150));QTest.mouseMove(canvas,QPoint(270,190),30)
        QTest.mouseRelease(canvas,Qt.LeftButton,pos=QPoint(270,190))
        result['preview_rotation']=canvas.yaw!=before
        distance=canvas.distance
        event=QWheelEvent(QPoint(200,150),canvas.mapToGlobal(QPoint(200,150)),QPoint(),QPoint(0,120),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
        QApplication.sendEvent(canvas,event)
        result['preview_zoom']=canvas.distance<distance
        preview.selector.setCurrentIndex(1)
        result['preview_chunk_filter']=canvas.selected==0
        preview.close();preview.deleteLater()
        target=win.ue_page.cb_target.currentData()
        win.ue_page.cb_target.setCurrentIndex(win.ue_page.cb_target.findData('blender'))
        result['blender_export_native']=(type(win.ue_page.cb_target) is fluent_widgets.ComboBox
            and 'Blender' in win.ue_page.btn_auto.text() and win.ue_page.ed_engine.isHidden() and win.ue_page.ed_project.isHidden())
        win.ue_page.cb_target.setCurrentIndex(win.ue_page.cb_target.findData(target))
        # Cover downloaded WeGame maps in the actual packaged selector, using
        # the real inventory when supplied by release validation.
        from core import mapnames
        inventory=os.environ.get('ATLASMAP_SELF_TEST_MAP_INVENTORY','')
        inventory_text=Path(inventory).read_text(encoding='utf-8') if inventory else (
            '1 DeltaForce/Content/Maps/Brakkesh_Long3/Base.umap\n'
            '1 DeltaForce/Content/Maps/BuildMaps_HD/Collapse/Runtime/Cell.umap')
        found=exporter.parse_maps(inventory_text);win.ue_page._maps_scanned(found)
        result['wegame_maps_native']=all(win.ue_page.cb_map.findData(name)>=0 and
            cn in win.ue_page.cb_map.itemText(win.ue_page.cb_map.findData(name))
            for name,cn in [('Brakkesh_Long3','Brakkesh'),('Collapse','Collapse')])
        helper=os.path.join(runtime,'scripts','tools','scene-state','scene-state.exe')
        with tempfile.TemporaryDirectory(prefix='atlasmap-runtime-check-') as runtime_check:
            code,text=exporter.run_blocking([helper,'--check-runtime',os.path.dirname(exporter.find_exe()),
                exporter.exporter_config_path(),runtime_check,runtime_check],timeout=60)
            result['state_helper_codec']=code==0 and 'ZstdSharp 0.8.8.0 ready' in text
        from core import activation as licensing
        from app.activation import activation_dialog
        activation_config=licensing.public_config();activation_machine=licensing.machine_code()
        result['activation_verified']=licensing.saved_license(activation_machine,licensing.unb64(activation_config['public_key']))[0]
        activation_ui=activation_dialog(activation_machine,activation_config)
        activation_ui._prepare_geometry();activation_ui.show();app.processEvents()
        result['activation_native']=(type(activation_ui) is fluent_widgets.FramelessDialog
            and type(activation_ui.machine_edit) is fluent_widgets.LineEdit
            and type(activation_ui.code_edit) is fluent_widgets.TextEdit)
        activation_ui.code_edit.setPlainText('invalid activation code');activation_ui.yes_button.click()
        result['activation_invalid_blocked']=activation_ui.result()==0 and bool(activation_ui.notice.detail())
        activation_ui.code_edit.clear();F.set_warning(activation_ui.notice,'');app.processEvents()
        activation_ui.grab().save(os.path.splitext(check_output)[0]+'-activation.png')
        activation_ui.close();activation_ui.deleteLater()
        win.set_parallel_theme(win.ue_page.chk_parallel.isChecked())
        splash.close()
        result['complete'] = (result['project_file_tools'] and result['project_manager_native'] and result['simple_mode_toggle'] and result['runtime_scripts_complete'] and result['runtime_exporter_valid'] and result['runtime_exporter_selected'] and result['fluent_native_controls'] and result['full_log_untruncated'] and result['full_log_all_workers'] and result['full_log_worker_button']
                              and result['wizard_tutorial_screenshots'] and result['wizard_rows'] == 3 and result['wizard_intro_finished']
                              and result['ue_logo_valid'] and bool(result['map_exe'])
                              and result['manual_lighting_mode'] and result['splash_gradient'] and result['splash_flow']
                              and result['state_helper'] and result['exporter_pinned']
                              and result['export_shrink_animation'] and result['export_compact']
                              and result['export_debug_hidden'] and result['export_cpu_memory']
                              and result['parallel_tiling'] and result['parallel_log_routing']
                              and result['parallel_red_theme'] and result['parallel_single_origin']
                              and result.get('parallel_split_motion') and result['parallel_split_finished']
                              and result['parallel_independent_progress'] and result['parallel_common_log_not_duplicated']
                              and result['parallel_green_success'] and result['parallel_success_logs_accessible']
                              and result['island_collapsed'] and result['island_success_hidden'] and result['island_restored']
                              and result['island_blur_transition']
                              and all(result.get(k) for k in ('cleanup_failure_question','cleanup_cancel_question',
                                  'cleanup_keep_files','cleanup_delete_files','cleanup_success_quiet'))
                              and result['performance_effect_visible']
                              and all(result.get(k) for k in ('preview_nonmodal','preview_native_controls','preview_rotation',
                                  'preview_zoom','preview_chunk_filter','blender_export_native',
                                  'wegame_maps_native','state_helper_codec','activation_verified',
                                  'activation_native','activation_invalid_blocked')))
        with open(check_output, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        win.close()
        export.close()
        return 0 if result['complete'] else 1

    holder: dict = {}

    def first_wizard():
        from app import wizard
        if not wizard.needs_wizard():
            return
        window = wizard.WizardWindow()
        holder["wizard"] = window
        def done(_ok):
            holder.pop("wizard", None)
            window.deleteLater()
            if holder.get("win"):
                holder["win"].refresh_pages()
        window.finished.connect(done)
        window.start()

    def build() -> MapViewerWindow:
        win = MapViewerWindow()
        holder["win"] = win
        return win

    def target_rect(win: MapViewerWindow) -> QRect:
        want_w = max(win.width(), _ui.px(1200))
        want_h = max(win.height(), _ui.px(760))
        w, h = _ui.fit(want_w, want_h)
        screen = app.primaryScreen()
        area = screen.availableGeometry() if screen else QRect(0, 0, w, h)
        return QRect(area.center().x() - w // 2, area.center().y() - h // 2, w, h)

    if os.environ.get("ATLASMAP_NOSPLASH") == "1":
        win = build()
        rect = target_rect(win)
        win.setGeometry(rect)
        win.show()
        win.raise_()
        win.activateWindow()
        QTimer.singleShot(180, first_wizard)
        return app.exec()

    splash = SplashWindow("AtlasMap", subtitle="地图导出器")
    splash.set_status("正在准备界面…")
    splash.set_fraction(0.06)
    splash.center_on_screen()
    splash.show()

    state = {"started": time.monotonic(), "built": False, "rect": QRect()}

    def open_main() -> None:
        if state["built"]:
            return
        state["built"] = True
        splash.set_status("正在打开主界面…")
        splash.set_fraction(0.85)
        win = build()
        rect = target_rect(win)
        state["rect"] = rect
        QTimer.singleShot(120, lambda: _finish(win, rect))

    def _finish(win: MapViewerWindow, rect: QRect) -> None:
        win.setGeometry(rect)
        splash.set_fraction(1.0)
        splash.set_status("请享用这款软件吧！")
        def ready():
            win.show()
            win.raise_()
            win.activateWindow()
            QTimer.singleShot(180, first_wizard)
        splash.expand_to(rect, ready, duration=EXPAND_MS)

    def tick() -> None:
        # 这里没有真正的索引过程：只是让开屏把动画走完，避免一闪而过
        elapsed = (time.monotonic() - state["started"]) * 1000.0
        frac = min(0.8, 0.06 + elapsed / (MIN_SPLASH_MS * 1.6))
        if not state["built"]:
            splash.set_fraction(frac)
        if elapsed >= MIN_SPLASH_MS:
            open_main()

    timer = QTimer()
    timer.setInterval(60)
    timer.timeout.connect(tick)
    timer.start()
    QTimer.singleShot(int(MIN_SPLASH_MS) + 40, open_main)

    return app.exec()


def main() -> int:
    try:
        return run()
    except Exception:                                            # noqa: BLE001
        import tempfile

        log = os.path.join(tempfile.gettempdir(), "atlasmap_crash.txt")
        with open(log, "w", encoding="utf-8") as fh:
            fh.write(traceback.format_exc())
        if os.environ.get("ATLASMAP_DEBUG") == "1":
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
