"""Quality must reach every exporter; forecasts must keep evidence and uncertainty."""
import json,os,struct,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from fluentpy import widgets as W
from core import exporter,ue_pipeline,export_quality as Q
from core.blender_pipeline import build_steps as blender_steps
from app.ue_page import UePage
from app.export_quality import QualityPanel


class QualityTests(unittest.TestCase):
    def test_history_records_real_bytes_and_beats_guessing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'Map';root.mkdir();(root/'chunks').mkdir()
            (root/'chunks/_a.bin').write_bytes(b'x'*1000)
            (root/'chunks/_a.blend').write_bytes(b'y'*300)
            textures=root/'textures';textures.mkdir()
            (textures/'T.png').write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'+struct.pack('>II',1024,1024)+b'\x00'*4000)
            project=Path(folder)/'UE/Map.uproject';project.parent.mkdir()
            (project.parent/'Content').mkdir();(project.parent/'Content/map.umap').write_bytes(b'z'*700)
            with patch.object(Q,'_history_path',return_value=Path(folder)/'history.json'):
                self.assertTrue(Q.record_export('Map',root,project=str(project)))
                history=Q.evidence('MAP')
                self.assertEqual(history['kind'],'history')
                self.assertGreater(history['source_bytes'],4400)
                self.assertEqual(history['ue_bytes'],700)
                exact=Q.forecast(history,'standard','raw',1)
                self.assertFalse(exact['approximate'])
                self.assertLessEqual(exact['low'],history['source_bytes'])
                self.assertGreaterEqual(exact['high'],history['source_bytes'])
                ue=Q.forecast(history,'standard','ue',1)
                self.assertLessEqual(ue['low'],700);self.assertGreaterEqual(ue['high'],700)
                # 没有 project 时退回按源体积比例，不返回 0
                self.assertTrue(Q.record_export('Map',root))
                fallback=Q.forecast(Q.evidence('map'),'standard','ue',1)
                self.assertGreater(fallback['low'],0)
                coarse=Q.forecast(Q.evidence('map'),'draft','ue',1)
                self.assertLessEqual(coarse['high'],fallback['high'])

    def test_history_is_zero_when_the_folder_is_gone(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(Q,'_history_path',return_value=Path(folder)/'history.json'):
                self.assertFalse(Q.record_export('Map',Path(folder)/'missing'))
                self.assertIsNone(Q.evidence('Map',settings=dict(paks='P',game='GAME_DeltaForce')))

    def test_source_forecast_brackets_measured_exports(self):
        # SafeHouse：贴图 0.95GB、机匣几何 96MB，实测源 2.10GB / UE 0.99GB
        data=dict(kind='source',geometry=96*Q.MB,instances=2771,texture_bytes=1020*Q.MB,
                  reference=1024,images=1993,note='')
        raw=Q.forecast(data,'standard','raw',2);ue=Q.forecast(data,'standard','ue',2)
        self.assertLess(raw['low'],2.10*Q.GB);self.assertGreater(raw['high'],2.10*Q.GB)
        self.assertLess(ue['low'],0.99*Q.GB);self.assertGreater(ue['high'],0.99*Q.GB)
        # 质量档位越小，区间上界不会变大
        self.assertLessEqual(Q.forecast(data,'draft','raw',2)['high'],raw['high'])

    def parameters(self,folder,**extra):
        return dict(root=folder+'/raw',transfer=folder+'/work',map='Test',blender='Blender.exe',scripts=folder+'/scripts',
                    engine='UE.exe',cmd='UE-Cmd.exe',project=folder+'/Test.uproject',dest='/Game/Test',
                    exe='map-export.exe',config='config',parallel_export='0',**extra)

    def test_serial_blender_and_unreal_take_selected_quality_and_allow_explicit_override(self):
        with tempfile.TemporaryDirectory() as folder,patch('core.exporter.exporter_is_required',return_value=True):
            for preset in Q.QUALITIES:
                p=self.parameters(folder,export_quality=preset.key)
                for steps in (ue_pipeline.build_steps(p),blender_steps(p,'run')[0]):
                    cmd=steps[0].cmd
                    self.assertEqual(int(cmd[cmd.index('--max-tex')+1]),preset.max_tex)
                    self.assertIn('--keep-base-with-hd',cmd)
                self.assertEqual(ue_pipeline.export_command(p,256)[-1],'256')
            self.assertEqual(ue_pipeline.export_command(self.parameters(folder))[-1],'1024')

    def test_parallel_workers_preserve_quality_in_argument_files(self):
        from core.parallel_export import write
        with tempfile.TemporaryDirectory() as folder,patch('core.exporter.exporter_is_required',return_value=True):
            p=self.parameters(folder,export_quality='original',target='blender',parallel_processes='2')
            p['parallel_export']='1';steps,project=blender_steps(p,'run')
            raw=[Path(folder)/'chunk0',Path(folder)/'chunk1']
            run=Path(p['transfer'])/'parallel/run'
            write(run/'workspace.json',dict(run_id='run',raw=list(map(str,raw)),outputs=[str(Path(folder)/'out0'),str(Path(folder)/'out1')]))
            # Rebuild so the real closures use our isolated workspace.
            steps,project=blender_steps(p,'run')
            inventory=next(s for s in steps if s.log_path and s.log_path.endswith('inventory.log'))
            Path(inventory.log_path).parent.mkdir(parents=True,exist_ok=True)
            Path(inventory.log_path).write_text('100 DeltaForce/Content/Maps/Test/A.umap\n100 DeltaForce/Content/Maps/Test/B.umap\n')
            inventory.validate(0)
            extract=next(s for s in steps if '多进程提取源地图' in s.name)
            with patch('core.full_parallel_export.check_space'):
                jobs=extract.parallel_factory()
            self.assertEqual(len(jobs),2)
            for directory in raw:
                args=json.loads((directory/'export_arguments.json').read_text())
                self.assertEqual(args[args.index('--max-tex')+1],'0')

    def test_listing_is_case_insensitive_deduplicated_and_not_reused_for_another_game(self):
        with tempfile.TemporaryDirectory() as folder,patch('core.export_quality._cache_path',return_value=Path(folder)/'cache.json'):
            listing='100 DeltaForce/Content/Maps/Test/A.umap\n100 DeltaForce/Content/Maps/Test/A.umap\n200 DeltaForce/Content/Maps/BuildMaps_HD/Test/B.uexp\n300 DeltaForce/Content/Maps/Other/Z.umap\n'
            settings=dict(paks='Game-A',game='GAME_DeltaForce');Q.cache_inventory(listing,settings)
            evidence=Q.evidence('TEST',settings=settings)
            self.assertEqual(evidence['package_bytes'],300);self.assertEqual(evidence['files'],2)
            self.assertIsNone(Q.evidence('Missing',settings=settings))
            self.assertIsNone(Q.evidence('Test',settings=dict(paks='Game-B')))
            one=Q.forecast(evidence,'draft');two=Q.forecast(evidence,'ultra')
            self.assertLess(one['high'],two['high']);self.assertGreater(two['free_recommended'],two['high'])
            self.assertTrue(Q.forecast(evidence,'original')['original_unbounded'])

    def test_existing_png_headers_and_current_source_quality_are_used_without_image_decoding(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'textures').mkdir()
            (root/'merge_report.json').write_text(json.dumps(dict(MapRoot='DeltaForce/Content/Maps/Test/',Instances=50,Vertices=100,Triangles=80)))
            (root/'textures/T.png').write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'+struct.pack('>II',512,256))
            Q.record_quality(root,'draft')
            evidence=Q.evidence('Test',folder)
            self.assertEqual(evidence['kind'],'source');self.assertEqual(evidence['reference'],512)
            self.assertEqual(evidence['images'],1);self.assertEqual(evidence['texture_bytes'],24)
            self.assertNotEqual((Q.evidence('Other',folder) or {}).get('kind'),'source')


class QualityUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_basic_mode_shows_quality_and_selected_limit_survives_target_changes(self):
        saved=dict(ue_map='CollectionRoom',ue_export_base='C:/Export')
        host=SimpleNamespace(job=None,status=lambda *a:None)
        with patch.object(exporter,'load_settings',side_effect=lambda:dict(saved)),patch.object(exporter,'save_settings',side_effect=lambda d:saved.update(d)):
            page=UePage(host,host)
            try:
                self.assertIs(type(page.quality.combo),W.ComboBox)
                self.assertFalse(page.quality.card.isHidden())
                page.quality.combo.setCurrentIndex(page.quality.combo.findData('ultra'))
                self.assertEqual(saved['export_quality'],'ultra')
                self.assertIn("'4096'",page._cmd_export())
                page.cb_target.setCurrentIndex(page.cb_target.findData('blender'))
                self.assertEqual(page._paths()['max_tex'],'4096')
            finally:page.deleteLater()

    def test_previous_map_background_result_cannot_replace_current_map_estimate(self):
        pending=[];host=SimpleNamespace(run_async=lambda fn,cb:pending.append(cb))
        panel=QualityPanel(host,lambda:None)
        try:
            panel.set_context('A',files=10);panel.timer.stop();panel._load()
            panel.set_context('B',files=20);panel.timer.stop();panel._load()
            pending[1](dict(kind='count',files=20,levels=20,note='CURRENT_MAP'))
            pending[0](dict(kind='count',files=10,levels=10,note='STALE_MAP'))
            self.assertIn('CURRENT_MAP',panel.basis.text());self.assertNotIn('STALE_MAP',panel.basis.text())
        finally:panel.card.deleteLater();panel.deleteLater()
