import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.export_residue import ExportResidue,for_ue_export
from core.ue_pipeline import Pipeline,Step
from scripts.official.map_paths import io_path
from tests.test_long_paths import long_path_directory


class ResidueTests(unittest.TestCase):
    def test_long_path_capture_and_delete_preserve_existing_files_and_logs(self):
        with long_path_directory() as folder:
            root=folder/'export'
            deep=root/('source_'+'x'*110)/('textures_'+'y'*110)
            io_path(deep).mkdir(parents=True)
            existing=deep/'existing.uasset';io_path(existing).write_bytes(b'existing')
            plan=ExportResidue([root]);plan.capture()
            new=deep/'new.uasset';io_path(new).write_bytes(b'partial')
            log=deep/'process.log';io_path(log).write_text('diagnostics')
            plan.seal();events=[]
            self.assertGreater(len(str(new)),260)
            self.assertFalse(plan.warnings)
            self.assertEqual(len(plan.candidates),1)
            result=plan.delete(on_progress=events.append)
            self.assertEqual(result['removed'],1)
            self.assertEqual(events[-1]['done'],events[-1]['total'])
            self.assertEqual(events[-1]['removed_bytes'],7)
            self.assertFalse(io_path(new).exists())
            self.assertEqual(io_path(existing).read_bytes(),b'existing')
            self.assertTrue(io_path(log).exists())

    def test_locked_file_reports_reason_and_does_not_hide_other_successes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan=ExportResidue([root]);plan.capture()
            locked=root/'locked.fbx';locked.touch()
            other=root/'other.fbx';other.touch();plan.seal()
            unlink=Path.unlink
            def fail_one(path,*args,**kwargs):
                if path.name==locked.name:raise PermissionError('Sharing violation: file is in use')
                return unlink(path,*args,**kwargs)
            with patch.object(Path,'unlink',fail_one):result=plan.delete()
            self.assertTrue(locked.exists());self.assertFalse(other.exists())
            self.assertEqual(result['removed'],1)
            self.assertIn('Sharing violation',result['errors'][str(locked)])

    def test_only_new_unchanged_files_are_deleted_and_logs_are_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'Export';root.mkdir()
            old=root/'existing.blend';old.write_text('before')
            plan=ExportResidue([root]);plan.capture()
            old.write_text('changed by exporter')
            chunk=root/'chunks/one';chunk.mkdir(parents=True)
            new=chunk/'mesh.fbx';new.write_text('mesh')
            changed=chunk/'changed.fbx';changed.write_text('first')
            log=chunk/'process.log';log.write_text('failure details')
            plan.seal()
            self.assertEqual(len(plan.candidates),2)
            changed.write_text('user edited after the question appeared')
            result=plan.delete()
            self.assertEqual(result['removed'],1)
            self.assertFalse(new.exists())
            self.assertTrue(log.exists())
            self.assertTrue(changed.exists())
            self.assertTrue(old.exists())
            self.assertEqual(len(result['skipped']),1)
            with self.assertRaises(RuntimeError):plan.delete()

    def test_keeping_the_plan_does_not_remove_anything(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'new-export';plan=ExportResidue([root]);plan.capture()
            root.mkdir();file=root/'mesh.fbx';file.touch()
            plan.seal()
            self.assertTrue(file.exists())
            self.assertFalse(plan.deleted)

    def test_new_empty_directories_removed_existing_directories_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'existing';root.mkdir()
            plan=ExportResidue([root]);plan.capture()
            (root/'chunk').mkdir();(root/'chunk/file').touch()
            plan.seal();plan.delete()
            self.assertTrue(root.is_dir())
            self.assertFalse((root/'chunk').exists())

    def test_project_and_other_run_are_excluded_but_this_run_assets_are_included(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);project=root/'UE';project.mkdir()
            paths=dict(project=str(project/'Test.uproject'),root=str(root),transfer=str(root/'Map_ue'),
                       dest='/Game/AtlasMaps/Map',parallel_export='1')
            run='a'*32
            plan=for_ue_export(paths,[Step('master',[],env={'ATLASMAP_UE_RUN_ID':run})]);plan.capture()
            for relative in ('Test.uproject','Config/DefaultEngine.ini','Content/AtlasMaps/Map/mesh.uasset',
                             '.atlasmap-parallel/'+run+'/chunk/file.fbx','.atlasmap-parallel/other/file.fbx'):
                file=project/relative;file.parent.mkdir(parents=True,exist_ok=True);file.touch()
            plan.seal();plan.delete()
            self.assertTrue((project/'Test.uproject').exists())
            self.assertTrue((project/'Config/DefaultEngine.ini').exists())
            self.assertTrue((project/'.atlasmap-parallel/other/file.fbx').exists())
            self.assertFalse((project/'Content/AtlasMaps/Map/mesh.uasset').exists())
            self.assertFalse((project/'.atlasmap-parallel'/run/'chunk/file.fbx').exists())

    def test_replaced_file_is_kept_even_with_same_length(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan=ExportResidue([root]);plan.capture()
            file=root/'part';file.write_text('one');plan.seal()
            file.rename(root/'moved');file.write_text('two')
            result=plan.delete()
            self.assertEqual(result['removed'],0)
            self.assertTrue(file.exists())

    def test_failed_and_cancelled_pipeline_seals_after_work_and_does_not_delete(self):
        with tempfile.TemporaryDirectory() as folder:
            for cancel in (False,True):
                root=Path(folder)/str(cancel)
                plan=ExportResidue([root]);events=[]
                def work(pipe):
                    root.mkdir();(root/'part.fbx').touch()
                    if cancel:pipe.stop()
                    else:raise ValueError('failed')
                pipe=Pipeline([Step('worker',[],action=work)],residue=plan,
                    on_done=lambda code:events.append((code,plan.sealed)))
                pipe._run()
                self.assertEqual(events,[(-2 if cancel else -4,True)])
                self.assertTrue((root/'part.fbx').exists())
                self.assertEqual(len(plan.candidates),1)

    @unittest.skipUnless(os.name=='nt','Windows junction safety')
    def test_junction_created_after_prompt_never_deletes_outside_files(self):
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'export';outside=Path(folder)/'outside'
            root.mkdir();outside.mkdir()
            plan=ExportResidue([root]);plan.capture()
            part=root/'part';part.mkdir();(part/'mesh').write_text('mesh')
            plan.seal()
            (part/'mesh').unlink();part.rmdir()
            (outside/'mesh').write_text('important')
            result=subprocess.run(['cmd','/c','mklink','/J',str(part),str(outside)],capture_output=True,
                                  creationflags=0x08000000)
            if result.returncode:self.skipTest('Junction creation unavailable')
            try:
                result=plan.delete()
                self.assertEqual(result['removed'],0)
                self.assertEqual((outside/'mesh').read_text(),'important')
            finally:part.rmdir()


os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QLabel
from app.export_cleanup import cleanup_question


class CleanupQuestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_default_and_escape_keep_files_and_delete_requires_explicit_click(self):
        plan=SimpleNamespace(candidates={'file':None},size=1024,warnings=[])
        for code in (-2,-4):
            dialog=cleanup_question(None,plan,code)
            self.assertEqual(dialog.cancel_button.text(),'保留文件')
            self.assertTrue(dialog.cancel_button.isDefault())
            self.assertTrue(any(('取消' if code==-2 else '失败') in label.text() for label in dialog.findChildren(QLabel)))
            self.assertIs(dialog.delete_residue_button,dialog.yes_button)
            from PySide6.QtCore import Qt
            self.assertFalse(dialog.testAttribute(Qt.WA_QuitOnClose))
            dialog.deleteLater()

    def test_no_files_disables_delete(self):
        dialog=cleanup_question(None,SimpleNamespace(candidates={},size=0,warnings=[]),-1)
        self.assertFalse(dialog.delete_residue_button.isEnabled())
        dialog.deleteLater()
