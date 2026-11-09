import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from core import exporter


class RuntimePayloadTests(unittest.TestCase):
    def test_singlefile_uses_its_extracted_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'scripts/official').mkdir(parents=True)
            with patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS',directory,create=True),patch.object(sys,'executable',str(root/'portable/App.exe')):
                self.assertEqual(exporter.runtime_root(),directory)
                command=exporter.source_state_command(['map-export.exe','--config','settings.json','merge','SafeHouse',str(root/'out')])
                self.assertEqual(Path(command[0]),root/'scripts/tools/scene-state/scene-state.exe')

    def test_directory_build_keeps_external_scripts(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS',str(root/'_internal'),create=True),patch.object(sys,'executable',str(root/'App.exe')):
                self.assertEqual(Path(exporter.runtime_root()),root)

    def test_bundled_exporter_wins_over_machine_specific_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'runtime').mkdir();(root/'runtime/map-export.exe').touch()
            with patch.object(exporter,'_meipass',return_value=directory),patch.object(exporter,'exporter_is_required',return_value=True):
                self.assertEqual(Path(exporter.find_exe()),root/'runtime/map-export.exe')

    def test_source_build_uses_repository_root(self):
        with patch.object(sys,'frozen',False,create=True):
            self.assertEqual(exporter.runtime_root(),exporter._src_root())
