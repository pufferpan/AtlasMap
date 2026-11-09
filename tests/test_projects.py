import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from core import projects


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'Project'
        (self.root / 'Content/AtlasMaps/SafeHouse').mkdir(parents=True)
        self.project = self.root / 'Project.uproject'
        self.project.write_text('{"FileVersion":3}', encoding='utf-8')
        (self.root / 'Content/data.bin').write_bytes(b'map asset\x00\xff')
        self.catalogue = projects.Catalogue(self.base / 'catalogue.json')

    def test_shared_project_has_one_record_with_all_maps(self):
        self.catalogue.register(self.project, 'CollectionRoom')
        self.catalogue.register(self.project, 'SafeHouse')
        records = self.catalogue.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(set(records[0]['maps']), {'SafeHouse', 'CollectionRoom'})
        self.assertIn('SafeHouse', projects.title(records[0]))

    def test_edit_preserves_map_assets_and_registry(self):
        self.catalogue.register(self.project)
        self.catalogue.edit(self.project, '我的CollectionRoom', '已修灯光')
        self.catalogue.register(self.project)
        record = self.catalogue.records()[0]
        self.assertEqual(projects.title(record), '我的CollectionRoom')
        self.assertEqual(record['note'], '已修灯光')
        self.assertTrue((self.root / 'Content/data.bin').is_file())

    def test_bad_registry_not_overwritten(self):
        self.catalogue.path.write_text('broken', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.catalogue.register(self.project)
        self.assertEqual(self.catalogue.path.read_text(), 'broken')

    def test_discover_configured_old_projects(self):
        found = projects.discover({'ue_project': str(self.project), 'ue_export_base': str(self.base)})
        self.assertEqual(found, [str(self.project)])

    @patch('core.projects.assert_idle')
    def test_move_keeps_whole_project_and_updates_record(self, idle):
        self.catalogue.register(self.project)
        dest = self.base / 'new';dest.mkdir()
        moved = projects.move(self.project, dest)
        self.catalogue.replace_path(self.project, moved)
        self.assertFalse(self.root.exists())
        self.assertEqual((Path(moved).parent / 'Content/data.bin').read_bytes(), b'map asset\x00\xff')
        self.assertEqual(self.catalogue.records()[0]['path'], moved)

    @patch('core.projects.assert_idle')
    def test_move_rejects_existing_or_nested_target(self, idle):
        for dest in (self.base, self.root / 'Content'):
            with self.assertRaises(ValueError):
                projects.move(self.project, dest)
        self.assertTrue(self.project.is_file())

    @patch('core.projects.assert_idle')
    def test_move_preserves_long_nested_asset_path(self, idle):
        relative = Path(*(['nested-assets-' * 3] * 7)) / 'texture.bin'
        asset = Path(projects._io_path(self.root / relative))
        asset.parent.mkdir(parents=True)
        asset.write_bytes(b'long-path-texture')
        dest = self.base / 'other';dest.mkdir()
        moved = projects.move(self.project, dest)
        result = Path(projects._io_path(Path(moved).parent / relative))
        self.assertEqual(result.read_bytes(), b'long-path-texture')

    @patch('core.projects.assert_idle')
    def test_cross_volume_move_verifies_copy_before_removing_source(self, idle):
        import errno
        dest = self.base / 'second-drive';dest.mkdir()
        with patch('core.projects.os.rename', side_effect=OSError(errno.EXDEV, 'different drive')):
            moved = projects.move(self.project, dest)
        self.assertTrue(Path(moved).exists())
        self.assertFalse(self.root.exists())
        self.assertEqual((Path(moved).parent/'Content/data.bin').read_bytes(), b'map asset\x00\xff')

    @patch('core.projects.assert_idle')
    def test_cross_volume_failed_copy_keeps_original(self, idle):
        import errno
        dest = self.base / 'second-drive';dest.mkdir()
        with patch('core.projects.os.rename', side_effect=OSError(errno.EXDEV, 'different drive')), patch('core.projects.shutil.copytree', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                projects.move(self.project, dest)
        self.assertTrue(self.project.exists())

    def test_running_editor_blocks_changes(self):
        from types import SimpleNamespace
        with patch('psutil.process_iter', return_value=[SimpleNamespace(info={'name':'UnrealEditor.exe'})]):
            with self.assertRaises(ValueError):
                projects.assert_idle()

    def test_multi_project_root_cannot_be_deleted(self):
        (self.root / 'Other.uproject').touch()
        with self.assertRaises(ValueError):
            projects.managed_root(self.project)

    @patch('core.projects.assert_idle')
    @patch('send2trash.send2trash')
    def test_delete_uses_recycle_bin_for_exact_project_root(self, trash, idle):
        trash.__module__ = 'send2trash.win.modern'
        projects.recycle(self.project)
        trash.assert_called_once_with(str(self.root))

    @patch('core.projects.assert_idle')
    @patch('send2trash.send2trash', side_effect=OSError('busy'))
    def test_recycle_failure_never_removes_catalogue(self, trash, idle):
        trash.__module__ = 'send2trash.win.modern'
        self.catalogue.register(self.project)
        with self.assertRaises(OSError):
            projects.recycle(self.project)
        self.assertEqual(len(self.catalogue.records()), 1)
        self.assertTrue(self.project.exists())
