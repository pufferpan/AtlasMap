from pathlib import Path
import tempfile,unittest,json
from unittest.mock import patch
from core.blender_pipeline import build_steps
from core import projects


class BlenderPipelineTests(unittest.TestCase):
    def test_blender_preparation_preserves_completed_unreal_result(self):
        from core.ue_pipeline import prepare_dirs
        with tempfile.TemporaryDirectory() as folder:
            raw=Path(folder)/'Map';ue=Path(str(raw)+'_ue');ue.mkdir()
            marker=ue/'ue_import_result.json';marker.write_text('{"complete":true}')
            prepare_dirs(str(raw),target='blender')
            self.assertEqual(marker.read_text(),'{"complete":true}')
            self.assertTrue(Path(str(raw)+'_blender_work').is_dir())

    def parameters(self,folder,parallel):
        return dict(root=folder+'/raw',transfer=folder+'/work',map='SafeHouse',blender='Blender.exe',scripts=folder+'/scripts',
            engine='',cmd='',project='',dest='/Game/Maps/SafeHouse',exe='map-export.exe',config='config',parallel_export=parallel,parallel_processes='3')

    def test_serial_and_parallel_blender_exports_require_no_unreal_commands(self):
        with tempfile.TemporaryDirectory() as folder,patch('core.exporter.exporter_is_required',return_value=True):
            for parallel in ('0','1'):
                steps,project=build_steps(self.parameters(folder,parallel),'a'*32)
                self.assertTrue(project.endswith('SafeHouse.blend'))
                self.assertFalse(any('UnrealEditor' in str(step.cmd) or 'ue_run_headless.py' in str(step.cmd) for step in steps))
                self.assertTrue(any('blender_assemble_project.py' in str(step.cmd) for step in steps))
                self.assertTrue(any('打包贴图' in step.name for step in steps))
                if parallel=='1':self.assertEqual(len(steps),12)
                else:self.assertEqual(len(steps),6)

    def test_new_exports_do_not_overwrite_an_existing_blender_project(self):
        with tempfile.TemporaryDirectory() as folder,patch('core.exporter.exporter_is_required',return_value=True):
            _,one=build_steps(self.parameters(folder,'0'),'a'*32)
            _,two=build_steps(self.parameters(folder,'0'),'b'*32)
            self.assertNotEqual(Path(one).parent,Path(two).parent)

    def test_blender_catalogue_and_directory_guard_require_completed_portable_project(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'BlenderMap';(root/'assets').mkdir(parents=True)
            project=root/'SafeHouse.blend';project.write_bytes(b'BLENDER')
            catalogue=projects.Catalogue(Path(folder)/'catalogue.json')
            catalogue.register(project,'SafeHouse')
            self.assertEqual(catalogue.records()[0]['maps'],['SafeHouse'])
            with self.assertRaises(ValueError):projects.managed_root(project)
            (root/'blender_project.json').write_text(json.dumps(dict(complete=True,map='SafeHouse',file=project.name)),encoding='utf-8')
            self.assertEqual(projects.managed_root(project),root)
            self.assertIn(str(project),projects.discover({'outdir':folder}))
            (root/'blender_project.json').write_text(json.dumps(dict(complete=False,file=project.name)),encoding='utf-8')
            with self.assertRaises(ValueError):projects.managed_root(project)
