import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from core.parallel_export import checked_file,copy_file,read,write
from scripts.official.map_io import share_file,atomic_json
from scripts.official.map_paths import io_path,display_path
from scripts.official.ue_asset_inputs import prepare
from tests.test_long_paths import long_path_directory


class NativeLongPathTests(unittest.TestCase):
    def test_long_file_validation_atomic_copy_and_receipt(self):
        with long_path_directory() as directory:
            root=Path(directory)
            relative='/'.join(['长路径分块校验'+str(i)+'x'*35 for i in range(6)])+'/PreBakeShadow.uasset'
            source=io_path(root/relative)
            self.assertGreater(len(display_path(source)),316)
            source.parent.mkdir(parents=True)
            data=b'complete-preserved-lighting'*64;source.write_bytes(data)
            verified=checked_file(root,relative)
            self.assertEqual(verified.read_bytes(),data)
            target=root/'output'/relative
            copy_file(verified,target,SimpleNamespace(_cancelled=False))
            self.assertEqual(io_path(target).read_bytes(),data)
            rows,stats=prepare(root,[{'id':'absolute-long','file':display_path(target),'sha256':hashlib.sha256(data).hexdigest()}],[])
            self.assertEqual(stats['files'],1)
            self.assertIn('Textures/absolute-long',rows)
            receipt=target.with_suffix('.json')
            atomic_json(receipt,{'size':len(data)})
            self.assertEqual(read(receipt),{'size':len(data)})
            write(receipt,{'sha256':hashlib.sha256(data).hexdigest()})
            self.assertEqual(read(receipt)['sha256'],hashlib.sha256(data).hexdigest())

    def test_long_path_copy_fallback_is_atomic_and_cancel_safe(self):
        with long_path_directory() as directory:
            root=Path(directory)
            source=root/'source';source.write_bytes(b'new bytes'*1024)
            target=root/('a'*90)/('b'*90)/('c'*90)/'copied.uasset'
            with patch('scripts.official.map_io.os.link',side_effect=OSError('cross volume')):
                share_file(source,target)
                self.assertEqual(io_path(target).read_bytes(),source.read_bytes())
                with self.assertRaises(InterruptedError):share_file(source,target,lambda:True)
                self.assertEqual(io_path(target).read_bytes(),source.read_bytes())
                self.assertFalse(list(io_path(target).parent.glob('*.partial')))

    def test_traversal_and_missing_are_still_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'root';root.mkdir()
            (root.parent/'outside').write_text('private')
            for path in ('../outside','missing.uasset'):
                with self.assertRaises(ValueError):checked_file(root,path)

    @unittest.skipUnless(os.name=='nt','Windows extended path spelling')
    def test_windows_prefix_and_unc_roundtrip(self):
        for value in ('C:/Export/Chunk_001/../file.uasset',r'\\server\share\a\b.uasset'):
            result=io_path(value)
            self.assertTrue(str(result).startswith('\\\\?\\'))
            self.assertEqual(io_path(result),result)
            self.assertFalse(display_path(result).startswith('\\\\?\\'))
